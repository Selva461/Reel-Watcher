package app.reelshelf;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * A model that comes as a ZIP (the offline speech model): it is downloaded and checked by ModelVerifier, and only then
 * looked at. It is unpacked into a temporary folder next to its final place, every entry is checked first (a name that
 * leaves the folder, a link or other special file, a repeated name, too many entries, too much data), and the finished
 * folder replaces the old one with one rename. An existing model folder is set aside first and deleted only when the new
 * one is in place; if anything fails before that, the old folder is exactly as it was. Whatever a failed or killed
 * attempt leaves in the root (".unpack-*" and ".old-*") is its own and is cleaned up, or put back, by recover() at the
 * next download. Pure Java (files only), tested on a computer.
 */
final class ModelZip {
    private ModelZip() {
    }

    /** What may be unpacked: every entry lives under one top folder, and the unpack stays inside these limits. */
    static final class Plan {
        /** The one folder every entry must be inside; it becomes root/folder. */
        final String folder;
        final int maxEntries;
        final long maxBytes;
        /** At least one of these sub-folders must exist in the unpacked folder, or it is not a usable model. */
        final List<String> oneOf;

        Plan(String folder, int maxEntries, long maxBytes, String... oneOf) {
            this.folder = folder;
            this.maxEntries = maxEntries;
            this.maxBytes = maxBytes;
            this.oneOf = Arrays.asList(oneOf);
        }
    }

    static final String UNSAFE = "The downloaded file is not a safe model package (it holds a path outside its folder, a link or an unusual file). Nothing was installed.";
    static final String TOO_BIG = "The downloaded file holds more than the published model should (too many files or too much data). Nothing was installed.";
    static final String BROKEN = "The downloaded file could not be unpacked (it is damaged or incomplete). Nothing was installed.";
    static final String FULL = "Phone storage is full. Free some space and try again. Nothing was installed.";
    static final String NOT_SAVED = "Could not save the unpacked model. The model that was installed before is unchanged.";

    static final String UNPACK = ".unpack-";
    static final String OLD = ".old-";

    /** A refusal that has its own plain message (other IOExceptions from the unpack are explained by explain()). */
    private static final class Refused extends IOException {
        Refused(String message) {
            super(message);
        }
    }

    /** Moves a folder; the one place a test can make the last step fail. */
    interface Mover {
        void move(File from, File to) throws IOException;
    }

    private static final Mover ATOMIC = (from, to) -> Files.move(from.toPath(), to.toPath(), StandardCopyOption.ATOMIC_MOVE);

    // ------------------------------------------------------------------ the whole job

    /**
     * Downloads the ZIP (size, SHA-256 and the MD5 must match: see ModelVerifier), unpacks it and swaps the folder in. The
     * ZIP is deleted at the end, whatever happened; an unfinished download (".part") is kept for the next try, and a
     * download that failed the check has already lost only its own ".part". A ZIP that fails the check is never unpacked.
     */
    static void fetch(ModelVerifier verifier, ModelCatalog.Entry e, File zip, File root, Plan plan, ModelVerifier.Progress p) throws IOException {
        recover(root, plan.folder);
        deleteTree(zip.toPath());  // the ZIP of an earlier attempt that was killed
        try {
            verifier.download(e, zip, p);
            install(zip, root, plan);
        } finally {
            deleteTree(zip.toPath());
        }
    }

    /** Unpacks an already checked ZIP into a temporary folder under root and swaps root/plan.folder for it. */
    static void install(File zip, File root, Plan plan) throws IOException {
        install(zip, root, plan, ATOMIC);
    }

    static void install(File zip, File root, Plan plan, Mover mover) throws IOException {
        try {
            Files.createDirectories(root.toPath());
        } catch (IOException x) {
            throw explain(x);
        }
        Path tmp;
        try {
            tmp = Files.createTempDirectory(root.toPath(), UNPACK);
        } catch (IOException x) {
            throw explain(x);
        }
        try {
            unpack(zip, tmp.toFile(), plan);
            File made = new File(tmp.toFile(), plan.folder);
            boolean usable = plan.oneOf.isEmpty();
            for (String m : plan.oneOf) if (new File(made, m).isDirectory()) usable = true;
            if (!made.isDirectory() || !usable) throw new Refused(BROKEN);  // nothing is swapped in that is not a model
            swap(made, new File(root, plan.folder), root, mover);
        } finally {
            deleteTree(tmp);  // the unpack's own folder: empty after a good swap, half-filled after a refusal
        }
    }

    /**
     * Cleans up what a failed or killed install left in root. First, if the model folder is missing and an old one was set
     * aside, the old one is put back (the swap was cut between its two renames); then every ".unpack-*" and ".old-*" is removed.
     */
    static void recover(File root, String folder) {
        File[] kids = root.listFiles();
        if (kids == null) return;
        Arrays.sort(kids);
        File target = new File(root, folder);
        if (!Files.exists(target.toPath(), LinkOption.NOFOLLOW_LINKS)) {
            for (int i = kids.length - 1; i >= 0; i--) {  // the newest set-aside is the model that was in use
                File k = kids[i];
                if (k.getName().startsWith(OLD) && k.isDirectory()) {
                    try {
                        ATOMIC.move(k, target);
                        break;
                    } catch (IOException ignored) {
                        // kept where it is: nothing here deletes it
                    }
                }
            }
        }
        boolean modelThere = Files.exists(target.toPath(), LinkOption.NOFOLLOW_LINKS);
        for (File k : kids) {
            String n = k.getName();
            if (n.startsWith(UNPACK) || (n.startsWith(OLD) && modelThere)) deleteTree(k.toPath());
        }
    }

    // ------------------------------------------------------------------ the swap

    private static void swap(File made, File target, File root, Mover mover) throws IOException {
        File aside = null;
        if (Files.exists(target.toPath(), LinkOption.NOFOLLOW_LINKS)) {
            aside = new File(root, OLD + System.currentTimeMillis() + "-" + System.nanoTime());
            try {
                mover.move(target, aside);
            } catch (IOException x) {
                throw new IOException(NOT_SAVED, x);  // nothing moved yet
            }
        }
        try {
            mover.move(made, target);
        } catch (IOException x) {
            if (aside != null) {
                try {
                    mover.move(aside, target);  // put the old model back
                } catch (IOException y) {
                    x.addSuppressed(y);  // it stays as ".old-*"; recover() puts it back
                }
            }
            throw new IOException(NOT_SAVED, x);
        }
        if (aside != null) deleteTree(aside.toPath());  // the new model is in place: only now may the old one go
    }

    // ------------------------------------------------------------------ checking and unpacking

    private static final class Item {
        final String name;
        final boolean dir;
        final long size;

        Item(String name, boolean dir, long size) {
            this.name = name;
            this.dir = dir;
            this.size = size;
        }
    }

    private static void unpack(File zip, File into, Plan plan) throws IOException {
        try {
            List<Item> items = scan(zip, plan);
            Path base = into.toPath().toAbsolutePath().normalize();
            long total = 0;
            try (ZipFile z = new ZipFile(zip)) {
                for (Item it : items) {
                    Path out = base.resolve(it.name).normalize();
                    if (!out.startsWith(base) || out.equals(base)) throw new Refused(UNSAFE);
                    if (it.dir) {
                        Files.createDirectories(out);
                        continue;
                    }
                    ZipEntry ze = z.getEntry(it.name);
                    if (ze == null) throw new Refused(BROKEN);
                    Files.createDirectories(out.getParent());
                    long wrote = 0;
                    try (InputStream in = z.getInputStream(ze); OutputStream o = Files.newOutputStream(out, StandardOpenOption.CREATE_NEW)) {
                        byte[] buf = new byte[64 * 1024];
                        int n;
                        while ((n = in.read(buf)) > 0) {
                            wrote += n;
                            total += n;
                            if (total > plan.maxBytes) throw new Refused(TOO_BIG);  // counted as it is written: a ZIP cannot lie about its size
                            o.write(buf, 0, n);
                        }
                    }
                    if (wrote != it.size) throw new Refused(BROKEN);
                }
            }
        } catch (IOException x) {
            throw explain(x);
        }
    }

    /** Our own refusals pass as they are; anything else (a full phone, a damaged stream) gets a plain sentence. */
    private static IOException explain(IOException x) {
        if (x instanceof Refused) return x;
        if (String.valueOf(x.getMessage()).contains("No space left")) return new IOException(FULL, x);
        return new IOException(BROKEN, x);
    }

    /**
     * Reads the ZIP's list of entries (its central directory) and refuses it before a single byte is written: a name that is
     * not a plain path inside plan.folder, a repeated name, anything but a regular file or a folder, an encrypted entry,
     * more entries than plan.maxEntries, or more data than plan.maxBytes. The list is read here, not through ZipFile, so the
     * checks are the same on every Java and Android.
     */
    private static List<Item> scan(File zip, Plan plan) throws IOException {
        try (RandomAccessFile f = new RandomAccessFile(zip, "r")) {
            long len = f.length();
            int tail = (int) Math.min(len, 22L + 65535);
            if (tail < 22) throw new Refused(BROKEN);
            byte[] t = new byte[tail];
            f.seek(len - tail);
            f.readFully(t);
            int eocd = -1;
            for (int i = tail - 22; i >= 0; i--) {
                if (le32(t, i) == 0x06054b50L) {
                    eocd = i;
                    break;
                }
            }
            if (eocd < 0) throw new Refused(BROKEN);  // a cut-off ZIP has no end record
            int count = le16(t, eocd + 10);
            long cdSize = le32(t, eocd + 12);
            long cdOffset = le32(t, eocd + 16);
            if (count == 0xFFFF || cdSize == 0xFFFFFFFFL || cdOffset == 0xFFFFFFFFL) throw new Refused(TOO_BIG);  // ZIP64: beyond any limit here
            if (count > plan.maxEntries) throw new Refused(TOO_BIG);
            long eocdAt = len - tail + eocd;
            if (cdSize > 4L * 1024 * 1024 || cdOffset + cdSize > eocdAt) throw new Refused(BROKEN);
            byte[] cd = new byte[(int) cdSize];
            f.seek(cdOffset);
            f.readFully(cd);

            List<Item> items = new ArrayList<>();
            Set<String> seen = new HashSet<>();
            long declared = 0;
            int p = 0;
            for (int i = 0; i < count; i++) {
                if (p + 46 > cd.length || le32(cd, p) != 0x02014b50L) throw new Refused(BROKEN);
                int madeBy = le16(cd, p + 4);
                int flags = le16(cd, p + 8);
                long size = le32(cd, p + 24);
                int nameLen = le16(cd, p + 28), extraLen = le16(cd, p + 30), commentLen = le16(cd, p + 32);
                long attr = le32(cd, p + 38);
                if (p + 46L + nameLen + extraLen + commentLen > cd.length) throw new Refused(BROKEN);
                if ((flags & 1) != 0) throw new Refused(BROKEN);  // encrypted: cannot be a published model
                if (size == 0xFFFFFFFFL) throw new Refused(TOO_BIG);
                String name = new String(cd, p + 46, nameLen, StandardCharsets.ISO_8859_1);
                int host = madeBy >> 8;
                if (host == 3 || host == 19) {  // made on Unix or macOS: the high bits of the attributes are the file mode
                    int type = (int) ((attr >>> 16) & 0170000);
                    if (type != 0 && type != 0100000 && type != 040000) throw new Refused(UNSAFE);  // a link, device, pipe or socket
                }
                boolean dir = name.endsWith("/");
                if (!safeName(name, plan.folder)) throw new Refused(UNSAFE);
                if (!seen.add(dir ? name.substring(0, name.length() - 1) : name)) throw new Refused(UNSAFE);  // the same name twice
                if (dir && size != 0) throw new Refused(BROKEN);
                declared += size;
                if (declared > plan.maxBytes) throw new Refused(TOO_BIG);
                items.add(new Item(name, dir, size));
                p += 46 + nameLen + extraLen + commentLen;
            }
            return items;
        }
    }

    /**
     * A plain path inside the one folder: it starts with "folder/", has only visible ASCII (no backslash, no colon), and no
     * empty, "." or ".." part. Absolute paths and anything that climbs out fail the first test or the last.
     */
    static boolean safeName(String name, String folder) {
        if (!name.startsWith(folder + "/")) return false;
        for (int i = 0; i < name.length(); i++) {
            char c = name.charAt(i);
            if (c < 0x20 || c > 0x7e || c == '\\' || c == ':') return false;
        }
        String body = name.endsWith("/") ? name.substring(0, name.length() - 1) : name;
        for (String part : body.split("/", -1)) {
            if (part.isEmpty() || part.equals(".") || part.equals("..")) return false;
        }
        return true;
    }

    private static int le16(byte[] b, int at) {
        return (b[at] & 0xFF) | (b[at + 1] & 0xFF) << 8;
    }

    private static long le32(byte[] b, int at) {
        return (b[at] & 0xFFL) | (b[at + 1] & 0xFFL) << 8 | (b[at + 2] & 0xFFL) << 16 | (b[at + 3] & 0xFFL) << 24;
    }

    // ------------------------------------------------------------------ deleting our own leftovers

    /** Deletes a file or folder tree without following links (a link is removed, never what it points to). Best effort. */
    static void deleteTree(Path p) {
        try {
            Files.walkFileTree(p, new SimpleFileVisitor<Path>() {
                @Override
                public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) throws IOException {
                    Files.delete(file);
                    return FileVisitResult.CONTINUE;
                }

                @Override
                public FileVisitResult postVisitDirectory(Path dir, IOException exc) throws IOException {
                    Files.delete(dir);
                    return FileVisitResult.CONTINUE;
                }
            });
        } catch (IOException | java.io.UncheckedIOException ignored) {
            // not there, or left for recover() at the next download
        }
    }
}
