package app.reelshelf;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * Copies ONE shared picture or video into an inbox so that a half-written file can never be taken for a finished one:
 * the data goes to a staging file (another folder, never listed), is counted, hashed and synced to disk, and only then
 * renamed into the inbox. The inbox name comes from the content (its SHA-256), so sharing the same picture or video again
 * finds it already there instead of keeping a second copy, and a retry after a failure or a stop is harmless.
 * The staging file is always removed again: after success, failure, stop or an exception. One buffer, no matter how big
 * the video is. Pure Java (files only), tested on a computer.
 */
final class MediaCopy {
    private static final int BUFFER = 64 * 1024;
    /** While copying, free space is looked at again after every this many bytes (a size that was not said, or was wrong). */
    private static final long SPACE_CHECK_EVERY = 4L * 1024 * 1024;
    /** Name characters taken from the hash: 24 hex digits = 96 bits, so two different files never share a name in practice. */
    private static final int HASH_CHARS = 24;

    enum Kind {
        /** Nothing in it. */ EMPTY,
        /** Over the size limit. */ TOO_BIG,
        /** The phone does not have room (the copy would leave too little for the library itself). */ NO_SPACE,
        /** Could not be opened, or Reel Shelf may not read it (any more). */ UNREADABLE,
        /** Not a picture / not a video. */ UNSUPPORTED,
        /** Any other read or write problem. */ FAILED,
        /** Stopped on purpose. */ CANCELLED;

        /** Worth offering "Try again": the cause may go away (space freed, the other app answers). */
        boolean retryable() {
            return this == NO_SPACE || this == UNREADABLE || this == FAILED;
        }
    }

    /** A copy that did not happen. getMessage() is the reason in plain words, fit to show: "too big (over 30 MB)". */
    static final class CopyException extends IOException {
        final Kind kind;

        CopyException(Kind kind, String why) {
            super(why);
            this.kind = kind;
        }
    }

    /** Where the data comes from. */
    interface Source {
        /** A new stream each call; null when the provider has nothing. */
        InputStream open() throws IOException;

        /** Size in bytes when the provider says so, else -1. Not trusted: the copy counts what it reads. */
        long size();

        /**
         * Asked after the stream was read: the number of bytes this very stream promised to deliver (an asset's length), else
         * -1. Fewer bytes than that means it was cut short (the other app died mid-transfer and the reader saw a plain end).
         * Unlike size() this is not the size of the original: a provider that converts the file does not promise the old size.
         */
        default long exactSize() {
            return -1;
        }
    }

    /** What the caller wants to know and may decide while the copy runs. */
    interface Control {
        boolean cancelled();

        /** Bytes copied so far of this file. */
        default void progress(long copied) {
        }

        default long freeSpace(File dir) {
            return dir.getUsableSpace();
        }

        /**
         * The stream that is being read (null again when it is done). Closing it from another thread ends a read that never
         * returns (the other app stalls): the copy then stops as cancelled, if cancelled() says so.
         */
        default void opened(java.io.Closeable stream) {
        }
    }

    /** Where it goes and how big it may be. */
    static final class Rules {
        final File inbox;
        final File staging;
        final String prefix;
        final String ext;
        final long maxBytes;
        /** Free space that must stay after the copy, so the library can still be saved. */
        final long reserveBytes;

        Rules(File inbox, File staging, String prefix, String ext, long maxBytes, long reserveBytes) {
            this.inbox = inbox;
            this.staging = staging;
            this.prefix = prefix;
            this.ext = ext;
            this.maxBytes = maxBytes;
            this.reserveBytes = reserveBytes;
        }
    }

    static final class Result {
        /** The finished file in the inbox. */
        final File file;
        /** The same content was in the inbox already: nothing new was kept. */
        final boolean alreadyThere;
        final long bytes;

        Result(File file, boolean alreadyThere, long bytes) {
            this.file = file;
            this.alreadyThere = alreadyThere;
            this.bytes = bytes;
        }
    }

    private MediaCopy() {
    }

    static Result copy(Source src, Rules rules, Control ctl) throws CopyException {
        long declared = src.size();
        if (declared > rules.maxBytes) throw new CopyException(Kind.TOO_BIG, "too big (over " + mb(rules.maxBytes) + ")");
        // (a declared size of 0 is not believed: some providers say 0 for "unknown". An empty source is found when it is read.)
        if (!rules.inbox.isDirectory() && !rules.inbox.mkdirs() && !rules.inbox.isDirectory()) throw new CopyException(Kind.FAILED, "the app's folder cannot be used");
        if (!rules.staging.isDirectory() && !rules.staging.mkdirs() && !rules.staging.isDirectory()) throw new CopyException(Kind.FAILED, "the app's folder cannot be used");
        if (ctl.freeSpace(rules.staging) < Math.max(declared, 0) + rules.reserveBytes) {
            File same = keptAlready(src, rules, ctl);  // short of room is no reason to refuse what is already here
            if (same != null) return new Result(same, true, same.length());
            throw noSpace();
        }
        if (ctl.cancelled()) throw new CopyException(Kind.CANCELLED, "stopped");

        File part;
        try {
            part = File.createTempFile("copy-", ".part", rules.staging);
        } catch (IOException e) {
            throw failed(e);
        }
        try {
            long total = 0;
            long nextSpaceCheck = SPACE_CHECK_EVERY;
            MessageDigest sha = digest();
            try (InputStream in = src.open()) {
                if (in == null) throw new CopyException(Kind.UNREADABLE, "it could not be opened");
                ctl.opened(in);
                if (ctl.cancelled()) throw new CopyException(Kind.CANCELLED, "stopped");  // stopped while it was opening: nothing was read yet
                try (FileOutputStream out = new FileOutputStream(part)) {
                    byte[] buf = new byte[BUFFER];
                    int n;
                    while ((n = in.read(buf)) != -1) {
                        if (ctl.cancelled() || Thread.currentThread().isInterrupted()) throw new CopyException(Kind.CANCELLED, "stopped");
                        total += n;
                        if (total > rules.maxBytes) throw new CopyException(Kind.TOO_BIG, "too big (over " + mb(rules.maxBytes) + ")");
                        out.write(buf, 0, n);
                        sha.update(buf, 0, n);
                        ctl.progress(total);
                        if (total >= nextSpaceCheck) {  // the reserve is kept while copying, not only before it
                            nextSpaceCheck = total + SPACE_CHECK_EVERY;
                            if (ctl.freeSpace(rules.staging) < rules.reserveBytes) throw noSpace();
                        }
                    }
                    out.flush();
                    out.getFD().sync();  // on the disk before it is renamed into the inbox
                }
            } finally {
                ctl.opened(null);
            }
            if (ctl.cancelled()) throw new CopyException(Kind.CANCELLED, "stopped");  // a closed stream may end with a plain end of file
            long promised = src.exactSize();
            if (promised > 0 && total < promised) throw new CopyException(Kind.FAILED, "it was cut short (the other app stopped sending it)");
            if (total == 0) throw new CopyException(Kind.EMPTY, "it is empty");
            if (part.length() != total) throw new CopyException(Kind.FAILED, "it could not be copied completely");
            File target = new File(rules.inbox, rules.prefix + hex(sha.digest()).substring(0, HASH_CHARS) + rules.ext);
            if (target.isFile() && target.length() == total) return new Result(target, true, total);  // the same content, kept earlier
            move(part, target);
            return new Result(target, false, total);
        } catch (CopyException e) {
            throw e;
        } catch (SecurityException e) {
            throw new CopyException(Kind.UNREADABLE, "Reel Shelf is not allowed to read it (any more)");
        } catch (IOException e) {
            if (ctl.cancelled()) throw new CopyException(Kind.CANCELLED, "stopped");  // the stream was closed to stop a stalled read
            throw failed(e);
        } finally {
            part.delete();  // already renamed on success: nothing is left here after any outcome
        }
    }

    /**
     * Reads the source without writing anything (used when the phone is short of room): the file of this content that is in
     * the inbox already, or null when it is not there. Says what is really wrong (too big, empty, cannot be read) instead of
     * "no space" when it finds that.
     */
    private static File keptAlready(Source src, Rules rules, Control ctl) throws CopyException {
        MessageDigest sha = digest();
        long total = 0;
        try (InputStream in = src.open()) {
            if (in == null) throw new CopyException(Kind.UNREADABLE, "it could not be opened");
            ctl.opened(in);
            if (ctl.cancelled()) throw new CopyException(Kind.CANCELLED, "stopped");
            byte[] buf = new byte[BUFFER];
            int n;
            while ((n = in.read(buf)) != -1) {
                if (ctl.cancelled() || Thread.currentThread().isInterrupted()) throw new CopyException(Kind.CANCELLED, "stopped");
                total += n;
                if (total > rules.maxBytes) throw new CopyException(Kind.TOO_BIG, "too big (over " + mb(rules.maxBytes) + ")");
                sha.update(buf, 0, n);
                ctl.progress(total);
            }
        } catch (CopyException e) {
            throw e;
        } catch (SecurityException e) {
            throw new CopyException(Kind.UNREADABLE, "Reel Shelf is not allowed to read it (any more)");
        } catch (IOException e) {
            if (ctl.cancelled()) throw new CopyException(Kind.CANCELLED, "stopped");
            throw failed(e);
        } finally {
            ctl.opened(null);
        }
        if (ctl.cancelled()) throw new CopyException(Kind.CANCELLED, "stopped");
        long promised = src.exactSize();
        if (promised > 0 && total < promised) throw new CopyException(Kind.FAILED, "it was cut short (the other app stopped sending it)");
        if (total == 0) throw new CopyException(Kind.EMPTY, "it is empty");
        File target = new File(rules.inbox, rules.prefix + hex(sha.digest()).substring(0, HASH_CHARS) + rules.ext);
        return target.isFile() && target.length() == total ? target : null;
    }

    private static CopyException failed(IOException e) {
        String m = String.valueOf(e.getMessage());
        if (m.contains("ENOSPC") || m.contains("No space left")) return noSpace();
        if (e instanceof java.io.FileNotFoundException) return new CopyException(Kind.UNREADABLE, "it could not be opened");
        return new CopyException(Kind.FAILED, "it could not be copied");
    }

    private static CopyException noSpace() {
        return new CopyException(Kind.NO_SPACE, "not enough storage space on the phone");
    }

    private static void move(File from, File to) throws IOException {
        try {
            Files.move(from.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE);
        } catch (AtomicMoveNotSupportedException e) {
            Files.move(from.toPath(), to.toPath(), StandardCopyOption.REPLACE_EXISTING);
        }
    }

    private static MessageDigest digest() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);  // every Java has SHA-256
        }
    }

    private static String hex(byte[] b) {
        StringBuilder s = new StringBuilder();
        for (byte x : b) s.append(Character.forDigit((x >> 4) & 15, 16)).append(Character.forDigit(x & 15, 16));
        return s.toString();
    }

    static String mb(long bytes) {
        return (bytes + 1024 * 1024 - 1) / (1024 * 1024) + " MB";
    }
}
