package app.reelshelf;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/**
 * The parts of "Back up now" (LocalBridge.backupLibrary) that need no phone: the file name, the free space it needs, the
 * counts that go in the manifest, the answer sent to the page, and the plain sentences for every way it can fail. Pure Java,
 * tested on a computer. A sentence never has a path, an exception message or any part of the library in it.
 */
final class BackupNow {
    private BackupNow() {
    }

    static final String BUSY = "Another backup is already running. Wait for it to finish.";
    /**
     * The library is locked, so there is no backup. These two name the button that really is on the screen shown then
     * (lockedScreen: "Save the unreadable file to Downloads", newerScreen: "Save a copy to Downloads"); a test checks that
     * both names are on those screens. The name is the text between the escaped quotes after "Use".
     */
    static final String LOCKED = "Your library could not be read, so it cannot be backed up. Use \"Save the unreadable file to Downloads\" instead.";
    static final String LOCKED_NEWER = "Your library was saved by a newer Reel Shelf, so this version cannot back it up. Use \"Save a copy to Downloads\", and install the newest Reel Shelf.";
    static final String NOTHING = "There is nothing to back up yet.";
    static final String READ_BACK = "The backup was saved but could not be read back correctly, so it was deleted. Your library was not changed. Please try again.";
    static final String OUT_OF_MEMORY = "The phone ran out of memory while making or checking the backup, so it was not kept. Close other apps and try again. Your library was not changed.";
    static final String DISK_FULL = "The phone ran out of space while saving the backup, so it was deleted. Free up space and try again. Your library was not changed.";
    static final String GENERIC = "The backup could not be saved. Your library was not changed. Please try again.";
    /** What a writer that has nothing to write says (see LocalBridge.saveToDownloads). */
    static final String EMPTY = "There is nothing to back up";

    /** The most a count in the manifest can say: counts are for the screen only, and a wrong page cannot put anything else in. */
    static final long MAX_COUNT = 1_000_000_000L;

    /** ReelShelf-backup-YYYYMMDD-HHMMSS.zip, in the given time zone (the phone's own, so it matches the clock the user sees). */
    static String fileName(long millis, TimeZone tz) {
        SimpleDateFormat f = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT);
        f.setTimeZone(tz);
        return "ReelShelf-backup-" + f.format(new Date(millis)) + ".zip";
    }

    /**
     * The moment a backup's name is made from: now, but never within the same second as the last one (the name only has
     * seconds, and a second backup must never take the name, and on Android 8 and 9 the file, of the first).
     */
    static long nameTime(long now, long lastNameTime) {
        return lastNameTime > 0 && now < lastNameTime + 1000 ? lastNameTime + 1000 : now;
    }

    /**
     * The free space a backup needs before anything is written: the ZIP (taken as big as the raw files, though JSON
     * usually compresses several times smaller) plus the staged copy the read-back makes (the raw files again), plus the
     * reserve that must stay free so the library itself can still be saved. A snapshot that had to be copied (no hard link)
     * is already on the disk when this is asked, so it is already out of the free space.
     */
    static long neededBytes(long reelsBytes, long shotsBytes, long reserve) {
        long keep = Math.max(0, reserve);
        long raw = Math.max(0, reelsBytes) + Math.max(0, shotsBytes);
        if (raw < 0 || raw > (Long.MAX_VALUE - keep) / 2) return Long.MAX_VALUE;  // not reachable for a real file; never wraps round to "fits"
        return raw * 2 + keep;
    }

    static String notEnoughSpace(long needed, long free) {
        long needMb = (needed + 1048575) / 1048576;
        long freeMb = Math.max(0, free) / 1048576;
        return "There is not enough free space on the phone for a backup: about " + needMb + " MB are needed and " + freeMb
                + " MB are free. Free up some space and try again. Your library was not changed.";
    }

    /**
     * What the manifest says was in the library, for the screen only: just these three numbers, taken from what the page sent,
     * never anything else of it. They are never checked against the files and nothing relies on them. A 0 for "screenshots"
     * means "not counted" (the page only counts a screenshot list it has already loaded, and 0 is also sent when the list was
     * left out of the backup), not "there are none": shots.json can be in the ZIP with 0 here.
     */
    static JSONObject counts(String pageJson, boolean withShots) {
        JSONObject page;
        try {
            page = new JSONObject(pageJson == null || pageJson.isEmpty() ? "{}" : pageJson);
        } catch (JSONException e) {
            page = new JSONObject();
        }
        JSONObject c = new JSONObject();
        try {
            c.put("reels", count(page, "reels"));
            c.put("titles", count(page, "titles"));
            c.put("screenshots", withShots ? count(page, "screenshots") : 0);
        } catch (JSONException e) {
            throw new IllegalStateException(e);  // not reachable: the keys are not null
        }
        return c;
    }

    static long count(JSONObject o, String key) {
        Object v = o.opt(key);
        if (!(v instanceof Number)) return 0;
        double d = ((Number) v).doubleValue();
        return d >= 1 ? (long) Math.min(d, MAX_COUNT) : 0;
    }

    /** Where the file is, for the screen: never a full internal path. appFolder: Android 8 and 9, which save to the app's own folder. */
    static String where(boolean appFolder, String packageName, String name) {
        return appFolder ? "Android/data/" + packageName + "/files/Download/ReelShelf/" + name : "Downloads/ReelShelf/" + name;
    }

    /** The answer for the page. */
    static Outcome ok(String name, String where, long bytes, JSONObject counts, boolean appFolder, boolean shotsSkipped) {
        JSONObject o = new JSONObject();
        try {
            o.put("name", name);
            o.put("where", where);
            o.put("bytes", bytes);
            o.put("counts", counts);
            o.put("uninstall_warning", appFolder);  // Android 8 and 9: the app's own folder, deleted when the app is uninstalled
            o.put("shots_skipped", shotsSkipped);
        } catch (JSONException e) {
            throw new IllegalStateException(e);  // not reachable: no null keys
        }
        return new Outcome(true, o.toString());
    }

    /** The sentence when the library is locked: newer is true when a newer Reel Shelf saved it (the screen then has another button). */
    static String locked(boolean newer) {
        return newer ? LOCKED_NEWER : LOCKED;
    }

    static Outcome fail(String sentence) {
        return new Outcome(false, sentence);
    }

    /** What the page is told: done, and the JSON (success) or the sentence (failure). */
    static final class Outcome {
        final boolean ok;
        final String text;

        Outcome(boolean ok, String text) {
            this.ok = ok;
            this.text = text;
        }
    }

    /** A failure whose message is already the sentence for the page. */
    static final class Failure extends IOException {
        Failure(String sentence) {
            super(sentence);
        }
    }

    /** The sentence for something that went wrong while saving. Only a Failure's own sentence, or a full disk, is told apart; the exception's text is never passed on. */
    static String sentenceFor(Throwable e) {
        int depth = 0;
        for (Throwable t = e; t != null && depth < 6; t = t.getCause(), depth++) {
            if (t instanceof Failure) return t.getMessage();
            if (t instanceof OutOfMemoryError) return OUT_OF_MEMORY;
            String m = t.getMessage();
            if (m != null && (m.contains("ENOSPC") || m.contains("No space left"))) return DISK_FULL;
        }
        return GENERIC;
    }

    /** NAME-2.ext, NAME-3.ext ...: the next name to try when one is taken. */
    static String numbered(String name, int n) {
        int dot = name.lastIndexOf('.');
        return dot > 0 ? name.substring(0, dot) + "-" + n + name.substring(dot) : name + "-" + n;
    }

    /** What is written to a file: returns the number of bytes, or -1 for "nothing to write". */
    interface Source {
        long to(OutputStream out) throws IOException;
    }

    /** Looks at a file that is complete and throws when it is not good. */
    interface Proof {
        void check(InputStream in) throws IOException;
    }

    /**
     * Android 8 and 9 (and tests): saves into dir so that a file with the final name is only ever a good one. It is written
     * as NAME.part, read back with proof, and only then renamed to NAME; it never replaces a file that is already there (the
     * next free name, NAME-2.ext and so on, is taken instead). When anything fails, even an Error, the .part is deleted and
     * the exception is rethrown. Returns the file with its final name.
     */
    static File saveProven(File dir, String name, Source w, String emptyMessage, Proof proof) throws IOException {
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        File fin = new File(dir, name);
        for (int i = 2; fin.exists() || new File(dir, fin.getName() + ".part").exists(); i++) fin = new File(dir, numbered(name, i));
        File part = new File(dir, fin.getName() + ".part");
        try {
            try (OutputStream out = new FileOutputStream(part)) {
                if (w.to(out) < 0) throw new IOException(emptyMessage);
            }
            try (InputStream in = new FileInputStream(part)) {
                proof.check(in);
            }
            Files.move(part.toPath(), fin.toPath());  // without REPLACE_EXISTING: it throws rather than overwrite
            return fin;
        } catch (Throwable t) {
            //noinspection ResultOfMethodCallIgnored
            part.delete();
            throw t;
        }
    }

    /** Counts the bytes that go through to out (the size of the saved file). Does not close out. */
    static final class Counter extends OutputStream {
        private final OutputStream out;
        private long n;

        Counter(OutputStream out) {
            this.out = out;
        }

        @Override
        public void write(int b) throws IOException {
            out.write(b);
            n++;
        }

        @Override
        public void write(byte[] b, int off, int len) throws IOException {
            out.write(b, off, len);
            n += len;
        }

        @Override
        public void flush() throws IOException {
            out.flush();
        }

        long count() {
            return n;
        }
    }
}
