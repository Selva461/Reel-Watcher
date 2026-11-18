package app.reelshelf;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.util.UUID;
import java.util.function.Supplier;

/**
 * The parts of "Restore from a backup" (LocalBridge.chooseBackup, restoreBackup, cancelRestore) that need no phone: the
 * sentences for every way it can be refused, how much a backup may unpack to, the preview the page shows before anything is
 * replaced, the token that ties a restore to the file that was checked, and the install itself (reels, then shots). Pure Java,
 * tested on a computer. A sentence never has a path, an exception message or any part of the library in it, and every refusal
 * says that nothing was changed (except the one case where the reels were restored and the screenshot list was not: then the
 * page is told exactly that, see {@link #install}).
 */
final class RestoreNow {
    private RestoreNow() {
    }

    /** A backup may unpack to at most this much, whatever the free space (the files are read into memory to be checked). */
    static final long MAX_UNPACKED_BYTES = 1L << 30;

    static final String BUSY = "Another backup or restore is already running. Wait for it to finish, then try again. Nothing was changed.";
    static final String WORK = "Reel Shelf is busy with a job (writing notes, reading screenshots, an online check, a download or the nightly run). Stop it, or wait until it is done, then try again. Nothing was changed.";
    static final String NO_FILE = "No file was chosen. Nothing was changed.";
    static final String CANNOT_OPEN = "The file could not be opened. Nothing was changed.";
    static final String NOT_READY = "That backup is no longer ready (it was cancelled, another file was chosen, or Reel Shelf was restarted). Choose the file again. Nothing was changed.";
    static final String NEWER_LIBRARY = "Your current library was saved by a newer Reel Shelf, so this version will not replace it. Install the newest Reel Shelf first. Nothing was changed.";
    static final String NEWER_SHOTS = "Your list of read screenshots was saved by a newer Reel Shelf, so this version will not replace it. Install the newest Reel Shelf first. Nothing was changed.";
    static final String NOT_INSTALLED = "The backup could not be installed. Your library was not changed.";
    static final String OUT_OF_MEMORY = "The phone ran out of memory while checking the backup, so nothing was restored. Close other apps and try again. Your library was not changed.";
    static final String DISK_FULL = "The phone ran out of space while checking the backup, so nothing was restored. Free up space and try again. Your library was not changed.";
    static final String GENERIC = "The backup could not be restored. Your library was not changed. Please try again.";

    /** What the page is told about the screenshot list after the install. */
    static final String SHOTS_RESTORED = "restored", SHOTS_KEPT = "kept", SHOTS_FAILED = "failed";

    /**
     * The most a backup may unpack to: the free space, less the reserve that must stay free so the library itself can still be
     * saved, less the size of the library files now (a set-aside copy of them is needed when a hard link is not possible), and
     * never more than {@link #MAX_UNPACKED_BYTES}. 0 (or less) means there is no room: refuse before reading anything.
     */
    static long maxBytes(long freeBytes, long reserve, long currentLibraryBytes) {
        long free = Math.max(0, freeBytes), keep = Math.max(0, reserve), library = Math.max(0, currentLibraryBytes);
        if (free <= keep) return 0;  // each step is checked before it subtracts: nothing can wrap round to "there is room"
        long room = free - keep;
        if (room <= library) return 0;
        return Math.min(MAX_UNPACKED_BYTES, room - library);
    }

    static String notEnoughSpace(long freeBytes, long reserve, long currentLibraryBytes) {
        long needMb = (Math.max(0, reserve) + Math.max(0, currentLibraryBytes) + 1048575) / 1048576;
        long freeMb = Math.max(0, freeBytes) / 1048576;
        return "There is not enough free space on the phone to restore a backup: more than " + needMb + " MB must stay free for your library and only "
                + freeMb + " MB are free. Free up some space and try again. Nothing was changed.";
    }

    /** The sentence for something that went wrong: only a full disk and running out of memory are told apart; the exception's text is never passed on. */
    static String sentenceFor(Throwable e) {
        int depth = 0;
        for (Throwable t = e; t != null && depth < 6; t = t.getCause(), depth++) {
            if (t instanceof OutOfMemoryError) return OUT_OF_MEMORY;
            String m = t.getMessage();
            if (m != null && (m.contains("ENOSPC") || m.contains("No space left"))) return DISK_FULL;
        }
        return GENERIC;
    }

    private static String clip(String s) {
        return s == null ? "" : s.length() > 64 ? s.substring(0, 64) : s;
    }

    /**
     * What the page shows before anything is replaced: the token to restore this file with, and what the backup says it holds.
     * The counts, date and version are the backup's own words (its manifest, which no hash covers): they are for the screen only
     * and the page shows them as text. bytes: the size of the staged library files.
     */
    static BackupNow.Outcome preview(String token, LibraryBackup.Checked c, long bytes) {
        JSONObject o = new JSONObject();
        try {
            o.put("token", token);
            o.put("created_at", clip(c.createdAt));
            o.put("app_version", clip(c.appVersionName));
            o.put("reels", BackupNow.count(c.counts, "reels"));
            o.put("titles", BackupNow.count(c.counts, "titles"));
            o.put("screenshots", BackupNow.count(c.counts, "screenshots"));
            o.put("has_shots", c.hasShots());
            o.put("bytes", Math.max(0, bytes));
        } catch (JSONException e) {
            throw new IllegalStateException(e);  // not reachable: no null keys
        }
        return new BackupNow.Outcome(true, o.toString());
    }

    /**
     * The one backup that was checked and is waiting in the staging folder, and the token that goes with it. A new token for each
     * check; a restore needs the token of the file the page was shown, and uses it once. Whoever puts a new one, or clears it,
     * must have emptied (or be emptying) the staging folder as well: a valid token always means "these staged files".
     */
    static final class Stage {
        private final Supplier<String> tokens;
        private String token;
        private LibraryBackup.Checked checked;

        Stage() {
            this(() -> UUID.randomUUID().toString());
        }

        Stage(Supplier<String> tokens) {
            this.tokens = tokens;
        }

        /** Remembers c (an OK check) and returns its token. Whatever was staged before is forgotten. */
        synchronized String put(LibraryBackup.Checked c) {
            if (c == null || !c.ok()) throw new IllegalArgumentException("only a backup that passed the check can be staged");
            token = tokens.get();
            checked = c;
            return token;
        }

        /** Whether t is the token of the staged backup (no side effect). */
        synchronized boolean matches(String t) {
            return token != null && t != null && token.equals(t);
        }

        /** The staged backup when t is its token, and then it is gone (single use); else null and nothing changes. */
        synchronized LibraryBackup.Checked take(String t) {
            if (!matches(t)) return null;
            LibraryBackup.Checked c = checked;
            token = null;
            checked = null;
            return c;
        }

        synchronized void clear() {
            token = null;
            checked = null;
        }

        synchronized boolean staged() {
            return token != null;
        }
    }

    /**
     * Installs a checked backup: the reels, then (when the backup has one) the screenshot list. Nothing is deleted: the library in
     * place is kept next to it as NAME.before-restore-STAMP. Order and rules:
     * 1. Both files are asked whether a newer Reel Shelf saved them; if so the restore is refused before anything is changed
     *    (a newer library is never replaced by an older Reel Shelf, and the second file cannot refuse after the first was replaced).
     * 2. reels: {@link LibraryFile#replaceWith}. It works while the library is unreadable (that is a way back) and leaves the
     *    old file, the .bak and the revision rules as S4-1 made them. A failure leaves the library exactly as it was.
     * 3. shots, when the backup has them. When the backup has none, the screenshot list in place stays (it can be read again from
     *    the pictures). If this fails AFTER the reels were replaced, the answer is still a success for the reels and says "failed"
     *    for the list: exactly that, no more and no less.
     * Answers with JSON {set_aside, shots, shots_set_aside}: the names of the files kept ("" when there was none) and
     * "restored", "kept" or "failed" for the screenshot list; or, when nothing was changed, one sentence.
     * The staged files are moved away; the caller clears the staging folder afterwards, whatever this returns.
     */
    static BackupNow.Outcome install(LibraryFile reels, LibraryFile shots, LibraryBackup.Checked c) {
        if (c == null || !c.ok() || c.reels == null || !c.reels.isFile() || (c.hasShots() && !c.shots.isFile())) return BackupNow.fail(NOT_READY);
        if (reels.savedByNewer()) return BackupNow.fail(NEWER_LIBRARY);
        if (c.hasShots() && shots.savedByNewer()) return BackupNow.fail(NEWER_SHOTS);
        File reelsAside;
        try {
            reelsAside = reels.replaceWith(c.reels);
        } catch (IOException e) {
            return BackupNow.fail(NOT_INSTALLED);  // the reels file is as it was
        }
        String shotsState = SHOTS_KEPT;
        File shotsAside = null;
        if (c.hasShots()) {
            try {
                shotsAside = shots.replaceWith(c.shots);
                shotsState = SHOTS_RESTORED;
            } catch (IOException | RuntimeException | Error e) {
                shotsState = SHOTS_FAILED;  // the reels are restored: say so, and that the list is as it was
            }
        }
        JSONObject o = new JSONObject();
        try {
            o.put("set_aside", reelsAside == null ? "" : reelsAside.getName());
            o.put("shots", shotsState);
            o.put("shots_set_aside", shotsAside == null ? "" : shotsAside.getName());
        } catch (JSONException e) {
            throw new IllegalStateException(e);  // not reachable: no null keys
        }
        return new BackupNow.Outcome(true, o.toString());
    }
}
