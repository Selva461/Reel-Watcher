package app.reelshelf;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.IntSupplier;

/**
 * The thin part of the temp sweep (see {@link TempSweep} for what may be deleted, and why nothing else is). It lists the
 * few allowlisted folders, asks the planner, and deletes only what the planner said, after looking at each file once more.
 * It errs on the side of keeping:
 * - a folder is read lazily, at most {@link #MAX_ENTRIES} entries; the rest wait for the next run;
 * - nothing is followed: a folder that is a link is not entered, and a link inside a folder is never deleted;
 * - any IOException or other exception while a folder is read keeps the whole folder (nothing in it is deleted);
 * - just before a file is deleted it is looked at again: still a regular file, same size, same modified time as when it was
 *   listed. A file that appeared after the listing was never listed, so it is never touched;
 * - an exception while deleting stops the sweep of that folder.
 * What it records: how many files and bytes went, how many entries it found that are not on the list (counts, never a file
 * name: not in the log, not in the preferences). Runs once per process, 20 seconds after the app starts, on its own
 * thread, and never while a job or the nightly run is working.
 */
final class TempSweeper {
    private TempSweeper() {
    }

    /** The most entries read from one folder. */
    static final int MAX_ENTRIES = 2000;
    static final long START_DELAY_MS = 20_000;
    /** The preference that keeps the last result: {at, files, bytes, left_unknown}. */
    static final String LAST_SWEEP = "last_sweep";
    private static final String TAG = "TempSweep";
    private static final AtomicBoolean STARTED = new AtomicBoolean();

    interface Clock {
        long now();
    }

    /** Seams for tests: how a folder is opened, and a moment between the listing and the deleting. */
    interface Io {
        default DirectoryStream<Path> open(Path dir) throws IOException {
            return Files.newDirectoryStream(dir);
        }

        default void afterListing(TempSweep.Folder folder) {
        }
    }

    private static final Io REAL = new Io() {
    };

    /** What a sweep did. Counts only. */
    static final class Result {
        /** Files deleted. */
        int files;
        long bytes;
        /** Entries seen that are not on the list (kept, whatever they are). */
        int leftUnknown;
    }

    /**
     * Once per process, from MainActivity.onCreate: waits, then sweeps unless a job or the nightly run is working. The
     * nightly run is a WorkService run too (WorkService.startNight), so WorkService.isRunning() covers both. Does nothing
     * on the calling thread.
     */
    static void startOnce(Context c) {
        if (!STARTED.compareAndSet(false, true)) return;
        Context app = c.getApplicationContext();
        Thread t = new Thread(() -> {
            try {
                Thread.sleep(START_DELAY_MS);
            } catch (InterruptedException e) {
                return;
            }
            if (WorkService.isRunning()) return;
            run(app, System::currentTimeMillis);
        }, "temp-sweep");
        t.setDaemon(true);
        t.start();
    }

    /** One sweep of this app's folders. Never throws (this runs on a thread of its own: an exception would end the app). */
    static Result run(Context c, Clock clock) {
        Result r = new Result();
        long now = clock.now();
        try {
            r = sweep(c.getFilesDir(), c.getCacheDir(), now, ReelVideo.BUSY::get);
            JSONObject last = new JSONObject().put("at", now).put("files", r.files).put("bytes", r.bytes).put("left_unknown", r.leftUnknown);
            SharedPreferences p = c.getSharedPreferences("reelshelf", Context.MODE_PRIVATE);
            p.edit().putString(LAST_SWEEP, last.toString()).apply();
            Log.i(TAG, "removed " + r.files + " leftover temporary files (" + r.bytes + " bytes), left " + r.leftUnknown + " other items alone");
        } catch (Throwable t) {
            Log.w(TAG, "stopped early: " + t.getClass().getSimpleName());  // the class only: a message could hold a file name
        }
        return r;
    }

    /** The sweep itself, on plain folders (no Android): what the tests run. videoReads: how many reel videos are being read now. */
    static Result sweep(File filesDir, File cacheDir, long now, IntSupplier videoReads) {
        return sweep(filesDir, cacheDir, now, videoReads, REAL);
    }

    static Result sweep(File filesDir, File cacheDir, long now, IntSupplier videoReads, Io io) {
        Result out = new Result();
        LibraryFile reels = LibraryFile.reels(filesDir);
        LibraryFile shots = LibraryFile.shots(filesDir);
        for (TempSweep.Folder folder : TempSweep.Folder.values()) {
            File dir = dirOf(folder, filesDir, cacheDir);
            TempSweep.Busy busy = new TempSweep.Busy(true, videoReads.getAsInt(), isOk(reels), isOk(shots));
            if (folder == TempSweep.Folder.STAGING) {
                // under the copying lock, and only when it is free right now: a share that is copying is never disturbed
                MediaBatch.trySweepStaging(() -> sweepFolder(folder, dir, now, busy.holdingStagingLock(), reels, shots, io, out));
            } else {
                sweepFolder(folder, dir, now, busy, reels, shots, io, out);
            }
        }
        return out;
    }

    private static File dirOf(TempSweep.Folder folder, File filesDir, File cacheDir) {
        switch (folder) {
            case STAGING:
                return new File(filesDir, "share-staging");
            case CACHE:
                return cacheDir;
            case REEL_MEDIA:
                return new File(cacheDir, "reel-media");
            default:
                return filesDir;
        }
    }

    private static boolean isOk(LibraryFile f) {
        return f.state() == LibraryFile.State.OK && !f.locked();
    }

    private static void sweepFolder(TempSweep.Folder folder, File dir, long now, TempSweep.Busy busy, LibraryFile reels, LibraryFile shots, Io io, Result out) {
        List<TempSweep.Entry> listed = list(folder, dir, io);
        if (listed == null) return;  // missing, a link, or not readable: the whole folder is kept
        List<TempSweep.Verdict> verdicts = TempSweep.plan(listed, now, busy);
        for (TempSweep.Verdict v : verdicts) if (v.reason == TempSweep.Reason.UNKNOWN_NAME) out.leftUnknown++;
        io.afterListing(folder);
        Path base = dir.toPath();
        for (TempSweep.Verdict v : verdicts) {
            if (!v.delete()) continue;
            TempSweep.Entry e = v.entry;
            try {
                boolean gone;
                switch (v.rule.guard) {
                    case REELS_LIBRARY:
                        gone = reels.dropTmp(f -> deleteIfUnchanged(f.toPath(), e.size, e.mtimeMs));
                        break;
                    case SHOTS_LIBRARY:
                        gone = shots.dropTmp(f -> deleteIfUnchanged(f.toPath(), e.size, e.mtimeMs));
                        break;
                    default:
                        gone = deleteIfUnchanged(base.resolve(e.name), e.size, e.mtimeMs);
                }
                if (gone) {
                    out.files++;
                    out.bytes += e.size;
                }
            } catch (IOException | RuntimeException x) {
                return;  // trouble in this folder: nothing more is deleted in it
            }
        }
    }

    /**
     * The entries of dir (at most {@link #MAX_ENTRIES}), each looked at without following links, or null when the folder is
     * to be left alone: it is missing, it is a link, it is not a folder, or anything at all went wrong reading it.
     */
    static List<TempSweep.Entry> list(TempSweep.Folder folder, File dir, Io io) {
        Path p = dir.toPath();
        try {
            BasicFileAttributes own = Files.readAttributes(p, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (own.isSymbolicLink() || !own.isDirectory()) return null;
            List<TempSweep.Entry> out = new ArrayList<>();
            try (DirectoryStream<Path> stream = io.open(p)) {
                for (Path child : stream) {
                    if (out.size() >= MAX_ENTRIES) break;  // the rest wait for the next run
                    BasicFileAttributes a;
                    try {
                        a = Files.readAttributes(child, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                    } catch (NoSuchFileException gone) {
                        continue;  // the app removed it itself while we were listing
                    }
                    out.add(new TempSweep.Entry(folder, child.getFileName().toString(), a.isRegularFile(), a.isSymbolicLink(),
                            a.lastModifiedTime().toMillis(), a.size()));
                }
            }
            return out;
        } catch (IOException | RuntimeException e) {  // a SecurityException and a DirectoryIteratorException are RuntimeExceptions
            return null;
        }
    }

    /**
     * Deletes path only when it is still the file that was listed: a regular file (not a link), the same size and the same
     * modified time. False when it changed, is not a regular file, or is already gone. Never follows a link.
     */
    static boolean deleteIfUnchanged(Path path, long size, long mtimeMs) throws IOException {
        try {
            BasicFileAttributes a = Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (!a.isRegularFile() || a.isSymbolicLink() || a.size() != size || a.lastModifiedTime().toMillis() != mtimeMs) return false;
            Files.delete(path);
            return true;
        } catch (NoSuchFileException gone) {
            return false;
        }
    }
}
