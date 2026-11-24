package app.reelshelf;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.webkit.JavascriptInterface;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * window.RN: what the built-in Reel Shelf page (assets/local) can ask the phone to do.
 * Only that page may use it (never a web site shown in the app). Long jobs run on one worker thread and report back
 * with rnDone(id, ok, text) and rnProgress(kind, done, total). Nothing here runs once the app is in the background.
 */
final class LocalBridge {
    static final String SHARED_KEY = "shared_queue";
    private static final Object SHARED_LOCK = new Object();

    private static final Object SETTINGS_LOCK = new Object();
    /** One library backup (or, later, restore) at a time in the whole app: the staging folders are shared. */
    private static final java.util.concurrent.atomic.AtomicBoolean LIBRARY_JOB = new java.util.concurrent.atomic.AtomicBoolean();
    /** The moment the last backup's name was made from (see BackupNow.nameTime). Only read and written while LIBRARY_JOB is held. */
    private static long lastBackupNameTime;
    /** The backup that was checked and waits in filesDir/restore-staging to be restored (see RestoreNow.Stage). Put and cleared only while LIBRARY_JOB is held. */
    private static final RestoreNow.Stage STAGE = new RestoreNow.Stage();
    /** The one pending confirmation of a delete of a kept file (see KeptFiles.Confirm). */
    private static final KeptFiles.Confirm KEPT_CONFIRM = new KeptFiles.Confirm();

    private final Host act;
    private final SharedPreferences prefs;
    private final LocalModel model;
    private final ScreenshotReader shots;
    private final ExecutorService ocr = Executors.newSingleThreadExecutor();
    private final ExecutorService work = Executors.newSingleThreadExecutor();
    private final ExecutorService net = Executors.newSingleThreadExecutor();
    private volatile boolean downloading;
    /** True while the app is on screen (MainActivity says so): a model check runs only then, and never at night. */
    private volatile boolean onScreen;
    /** True from the start of a picked file's copy to its end; guarded with pickLock so deleteModel never removes a copy in progress. */
    private volatile boolean picking;
    private final Object pickLock = new Object();
    /** Jobs queued or running on the worker thread (generate, saving files): a model check gives way to them. */
    private final java.util.concurrent.atomic.AtomicInteger jobs = new java.util.concurrent.atomic.AtomicInteger();
    /** The revision of each library file this page has loaded or last saved (see LibraryFile): a save is refused when the file has moved on. */
    private volatile long reelsRev = -1, shotsRev = -1;
    private final ExecutorService verifyWork = Executors.newSingleThreadExecutor();
    private final java.util.concurrent.atomic.AtomicBoolean verifyStop = new java.util.concurrent.atomic.AtomicBoolean(false);

    LocalBridge(Host act, SharedPreferences prefs) {
        this.act = act;
        this.prefs = prefs;
        this.model = new LocalModel(act.ctx());
        this.shots = new ScreenshotReader(act.ctx(), prefs);
    }

    /** Called when the app leaves the screen: stop downloads and answers, free the model's memory. */
    void pause() {
        model.stopAll();
        shots.stop();
        act.keepScreenOn(false);
        verifyStop.set(true);  // the online check (Process) only runs while the app is on screen
    }

    /** MainActivity: the app is on screen (true) or has left it (false). Leaving stops a model check, even while a job you started goes on. */
    void screen(boolean on) {
        onScreen = on;
        if (!on) model.checks.cancel();
    }

    /** The one worker thread for jobs. A model check on it gives way: it is stopped first, so a job never waits behind it. */
    private void runWork(Runnable r) {
        jobs.incrementAndGet();  // first: a check that is about to start sees the job and does not start
        model.checks.cancel();
        work.execute(() -> {
            try {
                r.run();
            } finally {
                jobs.decrementAndGet();
            }
        });
    }

    /** Adds shared text to the queue the page reads when it opens (used by ShareActivity, which has no page). */
    static void queueShared(Context ctx, String text) {
        if (text == null || text.trim().isEmpty()) return;
        synchronized (SHARED_LOCK) {
            SharedPreferences p = ctx.getSharedPreferences("reelshelf", Context.MODE_PRIVATE);
            String next = SharedQueue.append(p.getString(SHARED_KEY, "[]"), text, System.currentTimeMillis(), java.util.UUID.randomUUID().toString());
            p.edit().putString(SHARED_KEY, next).commit();
        }
    }

    private boolean ok() {
        return act.localPageTrusted();
    }

    private void done(int id, boolean success, String text) {
        act.callPage("window.rnDone && rnDone(" + id + "," + success + "," + JSONObject.quote(text == null ? "" : text) + ")");
    }

    private void progress(String kind, long doneBytes, long total) {
        act.callPage("window.rnProgress && rnProgress(" + JSONObject.quote(kind) + "," + doneBytes + "," + total + ")");
    }

    // ------------------------------------------------------------------ library (one JSON file in the app's storage)

    private LibraryFile reelsFile() {
        return LibraryFile.reels(act.ctx().getFilesDir());
    }

    private LibraryFile shotsFile() {
        return LibraryFile.shots(act.ctx().getFilesDir());
    }

    private LibraryFile fileOf(String which) {
        return "shots".equals(which) ? shotsFile() : reelsFile();
    }

    /**
     * The library text. "" for a new library, and also when the file cannot be read: then libraryInfo says "unreadable",
     * every save is refused and the file is left exactly as it is (see LibraryFile). A good backup is restored first.
     */
    @JavascriptInterface
    public String load() {
        if (!ok()) return "";
        LibraryFile.Loaded l = reelsFile().load();
        reelsRev = l.revision;  // saves from this page are for this version of the file
        return l.text;
    }

    @JavascriptInterface
    public boolean store(String json) {
        if (!ok() || json == null) return false;
        LibraryFile.Result r = reelsFile().write(json, reelsRev);  // refused when another page saved since this one loaded
        if (r.ok) reelsRev = r.revision;
        return r.ok;
    }

    private long revOf(String which) {
        return "shots".equals(which) ? shotsRev : reelsRev;
    }

    private void adopt(String which, long rev) {
        if ("shots".equals(which)) shotsRev = rev;
        else reelsRev = rev;
    }

    /**
     * True when this page's copy of the library file (which: "reels" or "shots") is out of date because another page
     * saved it, restored it or set it aside since this page loaded or last saved it. The page then reloads.
     */
    @JavascriptInterface
    public boolean libraryStale(String which) {
        if (!ok()) return false;
        return fileOf(which).revision() != revOf(which);
    }

    /**
     * {"state": ok|missing|recovered|unreadable|started_new|newer, "bad": name of the damaged file set aside, "notice": ...}.
     * "newer" (saved by a newer Reel Shelf, locked and untouched) adds "found" (its schema number) and "supported" (the
     * newest this build reads). which: "reels" or "shots".
     */
    @JavascriptInterface
    public String libraryInfo(String which) {
        if (!ok()) return "{}";
        LibraryFile f = fileOf(which);
        JSONObject o = new JSONObject();
        try {
            o.put("state", f.state().name().toLowerCase(java.util.Locale.ROOT));
            o.put("bad", f.badName());
            o.put("notice", act.isNight() ? "" : f.takeNotice());  // the nightly run has no screen to say it on
            if (f.state() == LibraryFile.State.NEWER) {
                o.put("found", f.found());
                o.put("supported", f.supported());
            }
        } catch (JSONException ignored) {
            // not reachable
        }
        return o.toString();
    }

    /** This app's version name (versionName in build.gradle), for the screen that says a newer library cannot be opened. "" when unknown. */
    @JavascriptInterface
    @SuppressWarnings("deprecation")
    public String appVersion() {
        if (!ok()) return "";
        try {
            String v = act.ctx().getPackageManager().getPackageInfo(act.ctx().getPackageName(), 0).versionName;
            return v == null ? "" : v;
        } catch (Exception e) {
            return "";
        }
    }

    /** Sets the damaged file aside (renamed, kept) and unlocks for a new one. False when that did not work: nothing is then changed. */
    @JavascriptInterface
    public boolean libraryStartNew(String which) {
        if (!ok()) return false;
        LibraryFile f = fileOf(which);
        try {
            synchronized (f) {
                f.startNew();
                adopt(which, f.revision());  // this page did it: its copy is not out of date
            }
            return true;
        } catch (IOException e) {
            return false;
        }
    }

    /** Deletes the backup copy (only after "Delete all reels and notes"). */
    @JavascriptInterface
    public boolean dropBackup(String which) {
        if (!ok()) return false;
        return fileOf(which).dropBackup();
    }

    /**
     * Saves the unreadable library file as it is to Downloads/ReelShelf (the same place as the exports), so it can be
     * sent to someone who can repair it. Copied byte for byte, never changed or deleted.
     */
    @JavascriptInterface
    public void saveUnreadable(int id, String which) {
        if (!ok()) return;
        runWork(() -> {
            LibraryFile f = fileOf(which);
            String name = ("shots".equals(which) ? "shots" : "reels") + "-unreadable-"
                    + new java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.ROOT).format(new java.util.Date()) + ".txt";
            try {
                if (f.unreadableFile() == null) {
                    done(id, false, "There is no unreadable file to save");
                    return;
                }
                done(id, true, saveToDownloads(name, "text/plain", f::copyUnreadableTo));
            } catch (Exception e) {
                done(id, false, "Could not save: " + e.getMessage());
            }
        });
    }

    private interface Writer {
        long to(OutputStream out) throws IOException;
    }

    /** Looks at a saved file once it is complete (a backup is read back). Throws when it is not good: the file is then deleted. */
    private interface ReadBack {
        void check(InputStream in) throws IOException;
    }

    /** Android's own way to save into Downloads (MediaStore, no permission needed); before Android 10 the app's Downloads folder. */
    private String saveToDownloads(String name, String mime, Writer w) throws IOException {
        return saveToDownloads(name, mime, w, "There is no unreadable file to save", null);
    }

    /**
     * emptyMessage is what a writer that returns -1 (nothing to write) says. readBack, when not null (a backup), is given the
     * saved file to look at once it is complete; the file is only a real file in Downloads once it passed: until then it is
     * hidden (Android 10 and newer: IS_PENDING) or named NAME.part (Android 8 and 9), so no other app, cloud upload or person
     * sees a half-finished or unproven file as a backup. When it fails, or anything else goes wrong (an Error too), the file
     * is deleted. A backup also never replaces a file of the same name on Android 8 and 9, and the place returned names the
     * file as Android really saved it (it may have added " (1)" to the name).
     */
    private String saveToDownloads(String name, String mime, Writer w, String emptyMessage, ReadBack readBack) throws IOException {
        if (Build.VERSION.SDK_INT >= 29) {
            android.content.ContentResolver cr = act.ctx().getContentResolver();
            ContentValues v = new ContentValues();
            v.put(MediaStore.Downloads.DISPLAY_NAME, name);
            v.put(MediaStore.Downloads.MIME_TYPE, mime);
            v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/ReelShelf");
            if (readBack != null) v.put(MediaStore.Downloads.IS_PENDING, 1);
            Uri uri = cr.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
            if (uri == null) throw new IOException("Android did not give a place to save");
            String saved = name;
            try {
                try (OutputStream out = cr.openOutputStream(uri)) {
                    if (out == null) throw new IOException("Could not write the file");
                    if (w.to(out) < 0) throw new IOException(emptyMessage);
                }
                if (readBack != null) {
                    try (InputStream in = cr.openInputStream(uri)) {
                        if (in == null) throw new IOException("Could not read the file back");
                        readBack.check(in);
                    }
                    ContentValues visible = new ContentValues();
                    visible.put(MediaStore.Downloads.IS_PENDING, 0);  // only now is it a file in Downloads
                    if (cr.update(uri, visible, null, null) < 1) throw new IOException("Could not finish the file");
                    saved = displayName(cr, uri, name);
                }
            } catch (Throwable t) {  // an Error too: nothing half-finished stays in Downloads
                cr.delete(uri, null, null);
                throw t;
            }
            return "Downloads/ReelShelf/" + saved;
        }
        File d = new File(act.ctx().getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "ReelShelf");
        if (readBack != null) return BackupNow.saveProven(d, name, w::to, emptyMessage, readBack::check).getPath();
        //noinspection ResultOfMethodCallIgnored
        d.mkdirs();
        File f = new File(d, name);
        boolean opened = false;  // only a file this call opened for writing is deleted when it fails
        try (OutputStream out = new FileOutputStream(f)) {
            opened = true;
            if (w.to(out) < 0) throw new IOException(emptyMessage);
        } catch (Throwable t) {  // an Error too, as on Android 10 and newer: no half-written file stays in Downloads
            //noinspection ResultOfMethodCallIgnored
            if (opened) f.delete();
            throw t;
        }
        return f.getPath();
    }

    /** The name Android gave a file it saved in Downloads (it renames a duplicate to "name (1).zip"); fallback when it cannot be asked. */
    private static String displayName(android.content.ContentResolver cr, Uri uri, String fallback) {
        try (android.database.Cursor c = cr.query(uri, new String[]{MediaStore.MediaColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                String n = c.getString(0);
                if (n != null && !n.isEmpty()) return n;
            }
        } catch (RuntimeException ignored) {
            // the name asked for is the best guess
        }
        return fallback;
    }

    /**
     * Back up now: ONE ZIP with the whole library (reels.json and shots.json byte for byte, and a manifest) in
     * Downloads/ReelShelf, then read back to prove it can be restored (LibraryBackup.check); a backup that fails the
     * read-back is deleted. countsJson is {reels, titles, screenshots} from the page, for the screen only. The library is
     * never parsed to make a backup and never changed. Done with JSON {name, where, bytes, counts, uninstall_warning,
     * shots_skipped} or, when it fails, with one plain sentence (no path, no exception text). Refused while the library is
     * locked (unreadable or newer). The file is readable by other apps: the page says so. Settings and API keys are not in it.
     */
    @JavascriptInterface
    public void backupLibrary(int id, String countsJson) {
        if (!ok()) return;
        work.execute(() -> {
            BackupNow.Outcome o;
            try {
                o = makeBackup(countsJson);  // everything is cleaned up before the page hears about it, so a click right after is not "busy"
            } catch (Throwable t) {  // an Error too (out of memory): the page must never stay on "Backing up..."
                o = BackupNow.fail(BackupNow.sentenceFor(t));
            }
            done(id, o.ok, o.text);
        });
    }

    private BackupNow.Outcome makeBackup(String countsJson) {
        if (!LIBRARY_JOB.compareAndSet(false, true)) return BackupNow.fail(BackupNow.BUSY);
        try {
            return backupHoldingTheFlag(countsJson);
        } finally {
            LIBRARY_JOB.set(false);  // whatever happens inside, the flag cannot stay set
        }
    }

    @SuppressWarnings("deprecation")
    private BackupNow.Outcome backupHoldingTheFlag(String countsJson) {
        File dir = act.ctx().getFilesDir();
        File snaps = new File(dir, "backup-work");  // hard links to the library files: only ever read or deleted, never opened for writing
        File staging = new File(dir, "backup-check");  // same volume as the library; the read-back unpacks here (not restore-staging: a restore waiting for its Restore button must survive the backup the page makes first)
        try {
            LibraryBackup.clear(snaps);  // what a cut-off backup left (our own links, not user data); snapshotTo refuses a name that exists
            LibraryFile reels = reelsFile(), shots = shotsFile();
            File reelsSnap = new File(snaps, LibraryBackup.REELS), shotsSnap = new File(snaps, LibraryBackup.SHOTS);
            boolean haveReels, haveShots = false, shotsSkipped = false;
            synchronized (reels) {  // both are taken together so they belong to each other: reels lock first, shots inside it (nothing takes them the other way round)
                try {
                    haveReels = reels.snapshotTo(reelsSnap);
                } catch (IOException e) {
                    if (reels.locked()) return BackupNow.fail(BackupNow.locked(reels.state() == LibraryFile.State.NEWER));  // unreadable or newer: never backed up
                    throw e;
                }
                if (haveReels) {
                    synchronized (shots) {
                        try {
                            haveShots = shots.snapshotTo(shotsSnap);
                        } catch (IOException e) {
                            if (!shots.locked()) throw e;
                            shotsSkipped = true;  // the screenshot list cannot be read (or is newer): it is not in the backup (it can be read again from the pictures), and the page says so
                        }
                    }
                }
            }
            if (!haveReels) return BackupNow.fail(BackupNow.NOTHING);
            long reelsBytes = reelsSnap.length(), shotsBytes = haveShots ? shotsSnap.length() : 0;
            long need = BackupNow.neededBytes(reelsBytes, shotsBytes, SharedItems.RESERVE_BYTES);
            long free = dir.getUsableSpace();
            File external = act.ctx().getExternalFilesDir(null);  // where Downloads is (the same disk on most phones)
            if (external != null) free = Math.min(free, external.getUsableSpace());
            if (free < need) return BackupNow.fail(BackupNow.notEnoughSpace(need, free));

            String versionName = "";
            int versionCode = 0;
            try {
                android.content.pm.PackageInfo pi = act.ctx().getPackageManager().getPackageInfo(act.ctx().getPackageName(), 0);
                if (pi.versionName != null) versionName = pi.versionName;
                versionCode = pi.versionCode;
            } catch (Exception ignored) {
                // the manifest then says "" and 0: a backup is still a backup
            }
            final String vName = versionName;
            final int vCode = versionCode;
            final boolean withShots = haveShots;
            final JSONObject counts = BackupNow.counts(countsJson, haveShots);  // display only; 0 screenshots here means "not counted", whether or not shots.json is in the ZIP
            long now = System.currentTimeMillis();
            long named = BackupNow.nameTime(now, lastBackupNameTime);
            lastBackupNameTime = named;
            String name = BackupNow.fileName(named, java.util.TimeZone.getDefault());
            long[] size = new long[1];
            final long raw = reelsBytes + shotsBytes;
            String place = saveToDownloads(name, "application/zip", out -> {
                BackupNow.Counter counter = new BackupNow.Counter(out);
                java.io.BufferedOutputStream buffered = new java.io.BufferedOutputStream(counter, 64 * 1024);
                LibraryBackup.write(buffered, reelsSnap, reels.supported(), withShots ? shotsSnap : null, shots.supported(), counts, vName, vCode, now);
                buffered.flush();
                size[0] = counter.count();
                return size[0];
            }, BackupNow.EMPTY, in -> {  // the proof that it can be restored
                LibraryBackup.Checked c;
                try {
                    c = LibraryBackup.check(new java.io.BufferedInputStream(in, 64 * 1024), staging, raw + LibraryBackup.MANIFEST_MAX_BYTES);
                } catch (OutOfMemoryError e) {
                    throw new BackupNow.Failure(BackupNow.OUT_OF_MEMORY);  // whole files are read to be checked
                }
                if (!c.ok()) throw new BackupNow.Failure(BackupNow.READ_BACK);
            });
            String saved = new File(place).getName();  // the name it really has: Android may have changed it ("name (1).zip") and a taken name is not reused
            boolean appFolder = Build.VERSION.SDK_INT < 29;  // Android 8 and 9: the app's own folder, deleted with the app
            return BackupNow.ok(saved, BackupNow.where(appFolder, act.ctx().getPackageName(), saved), size[0], counts, appFolder, shotsSkipped);
        } catch (IOException | RuntimeException e) {
            return BackupNow.fail(BackupNow.sentenceFor(e));
        } finally {
            LibraryBackup.clear(snaps);
            LibraryBackup.clear(staging);
        }
    }

    // ------------------------------------------------------------------ restore from a backup (two steps: choose and check, then restore)

    /** A job you started, a download, or the nightly run is going: nothing is chosen or restored then. */
    private boolean busyWithWork() {
        return act.isNight() || WorkService.isRunning() || WorkService.nightActive();
    }

    private File restoreStaging() {
        return new File(act.ctx().getFilesDir(), "restore-staging");  // same volume as the library: the install is a rename
    }

    /**
     * Restore, step 1: Android's file picker, then the chosen file is read once through LibraryBackup.check into
     * filesDir/restore-staging (nothing is installed, the library is not touched). Done with a preview JSON {token, created_at,
     * app_version, reels, titles, screenshots, has_shots, bytes} for the confirm screen, or with one plain sentence: no file chosen,
     * a job or the nightly run going, no room, not a backup (a bare reels.json or a notes export), damaged, made by a newer Reel
     * Shelf. A refusal leaves staging empty. The counts are the backup's own label (its manifest): the page knows the library's.
     */
    @JavascriptInterface
    public void chooseBackup(int id) {
        if (!ok()) return;
        if (busyWithWork()) {
            done(id, false, RestoreNow.WORK);
            return;
        }
        act.runOnUiThread(() -> act.pickModelFile(uri -> work.execute(() -> {
            BackupNow.Outcome o;
            try {
                o = stageBackup(uri);
            } catch (Throwable t) {  // an Error too (out of memory): the page must never stay on "Checking..."
                o = BackupNow.fail(RestoreNow.sentenceFor(t));
            }
            done(id, o.ok, o.text);
        })));
    }

    private BackupNow.Outcome stageBackup(Uri uri) {
        if (uri == null) return BackupNow.fail(RestoreNow.NO_FILE);
        if (!LIBRARY_JOB.compareAndSet(false, true)) return BackupNow.fail(RestoreNow.BUSY);
        try {
            return stageHoldingTheFlag(uri);
        } finally {
            LIBRARY_JOB.set(false);
        }
    }

    private BackupNow.Outcome stageHoldingTheFlag(Uri uri) {
        File dir = act.ctx().getFilesDir();
        File staging = restoreStaging();
        STAGE.clear();  // an earlier choice is gone before its files are: a valid token always means the files in staging
        LibraryBackup.clear(staging);
        if (busyWithWork()) return BackupNow.fail(RestoreNow.WORK);  // a nightly run can start while the picker is open: the app is not on screen then
        long current = reelsFile().main.length() + shotsFile().main.length();
        long free = dir.getUsableSpace();
        long max = RestoreNow.maxBytes(free, SharedItems.RESERVE_BYTES, current);
        if (max <= 0) return BackupNow.fail(RestoreNow.notEnoughSpace(free, SharedItems.RESERVE_BYTES, current));
        try (InputStream in = act.ctx().getContentResolver().openInputStream(uri)) {
            if (in == null) return BackupNow.fail(RestoreNow.CANNOT_OPEN);
            LibraryBackup.Checked c = LibraryBackup.check(new java.io.BufferedInputStream(in, 64 * 1024), staging, max);  // check empties staging when it refuses
            if (!c.ok()) return BackupNow.fail(c.message);
            long bytes = c.reels.length() + (c.hasShots() ? c.shots.length() : 0);
            return RestoreNow.preview(STAGE.put(c), c, bytes);
        } catch (IOException | RuntimeException e) {
            LibraryBackup.clear(staging);
            return BackupNow.fail(e instanceof java.io.FileNotFoundException || e instanceof SecurityException ? RestoreNow.CANNOT_OPEN : RestoreNow.sentenceFor(e));
        } catch (Throwable t) {  // out of memory while checking: nothing unverified stays
            LibraryBackup.clear(staging);
            throw t;
        }
    }

    /**
     * Restore, step 2: installs the backup that chooseBackup checked and gave this token for: the reels, then the screenshot list
     * (RestoreNow.install; LibraryFile.replaceWith). The library in place is kept as reels.json.before-restore-STAMP, never deleted.
     * Works while the library is unreadable (a way back). Refused (nothing changed) while a job or the nightly run is going, when the
     * token is not the one staged, and while the library (or the screenshot list) was saved by a newer Reel Shelf. Done with JSON
     * {set_aside, shots, shots_set_aside}, or one sentence. The token is used up by a call that gets past the token check, and staging is
     * emptied whatever the answer. The page reads the library fresh afterwards (the bridge does not adopt the new revision here).
     */
    @JavascriptInterface
    public void restoreBackup(int id, String token) {
        if (!ok()) return;
        work.execute(() -> {
            BackupNow.Outcome o;
            try {
                o = restoreStaged(token);
            } catch (Throwable t) {  // an Error too: the page must never stay on "Restoring..."
                o = BackupNow.fail(RestoreNow.sentenceFor(t));
            }
            done(id, o.ok, o.text);
        });
    }

    private BackupNow.Outcome restoreStaged(String token) {
        if (!LIBRARY_JOB.compareAndSet(false, true)) return BackupNow.fail(RestoreNow.BUSY);
        try {
            LibraryBackup.Checked c = STAGE.take(token);  // only for the file the page was shown, and only once
            if (c == null) return BackupNow.fail(RestoreNow.NOT_READY);
            try {
                if (busyWithWork()) return BackupNow.fail(RestoreNow.WORK);  // asked again here: a night or a job can start between the two steps
                return RestoreNow.install(reelsFile(), shotsFile(), c);
            } finally {
                LibraryBackup.clear(restoreStaging());
            }
        } finally {
            LIBRARY_JOB.set(false);
        }
    }

    /** The page leaves the restore screen (or the user cancels): the checked backup and its staged files are dropped. Skipped while a check or an install runs (it empties its own staging when it ends). */
    @JavascriptInterface
    public void cancelRestore() {
        if (!ok()) return;
        if (!LIBRARY_JOB.compareAndSet(false, true)) return;
        try {
            STAGE.clear();
            LibraryBackup.clear(restoreStaging());
        } finally {
            LIBRARY_JOB.set(false);
        }
    }

    // ------------------------------------------------------------------ files kept for safety (the logic is KeptFiles; this is the phone's part)

    private KeptFiles.Env keptEnv() {
        return new KeptFiles.Env(act.ctx().getFilesDir(), LIBRARY_JOB, this::busyWithWork, reelsFile(), shotsFile(), STAGE, KEPT_CONFIRM, java.util.TimeZone.getDefault());
    }

    /**
     * The files Reel Shelf set aside, newest first, as JSON {items: [{name, kind, library, size, at, files}], error}: library files that
     * could not be read (NAME.bad-STAMP), the library a restore replaced (NAME.before-restore-STAMP), and the leftover files of
     * restore-staging and backup-check as one row. Nothing else is listed (not the library, its backup, a temp file of a running write,
     * models, inboxes), no link is followed, and no path is given. Always allowed; changes nothing.
     */
    @JavascriptInterface
    public String keptFiles() {
        if (!ok()) return "";
        return KeptFiles.listJson(act.ctx().getFilesDir(), java.util.TimeZone.getDefault());
    }

    /**
     * Saves a copy of a kept file to Downloads/ReelShelf as LIBRARY-WHAT-STAMP.txt, like Back up now does: hidden until it has been read back
     * and found whole (IS_PENDING on Android 10 and newer, NAME.part on 8 and 9), deleted when anything fails, never replacing a file. The kept
     * file stays where it is. name must be one keptFiles gave (checked again). Always allowed (never blocked by work or a locked library).
     * Done with JSON {name, where, bytes, uninstall_warning}, or one plain sentence (no path, no exception text). The copy is private data
     * that other apps can read: the page says so.
     */
    @JavascriptInterface
    public void saveKept(int id, String name) {
        if (!ok()) return;
        work.execute(() -> {
            BackupNow.Outcome o;
            try {
                o = saveKeptNow(name);
            } catch (Throwable t) {  // an Error too: the page must never stay on "Saving..."
                o = BackupNow.fail(KeptFiles.sentenceFor(t));
            }
            done(id, o.ok, o.text);
        });
    }

    private BackupNow.Outcome saveKeptNow(String name) throws IOException {
        File dir = act.ctx().getFilesDir();
        KeptFiles.Kind kind = KeptFiles.kindOf(name);
        if (kind == null) return BackupNow.fail(KeptFiles.NOT_KEPT);
        if (kind == KeptFiles.Kind.TEMP) return BackupNow.fail(KeptFiles.TEMP_SAVE);
        KeptFiles.Item it = KeptFiles.find(dir, name, java.util.TimeZone.getDefault());
        if (it == null) return BackupNow.fail(KeptFiles.SAVE_GONE);
        long need = KeptFiles.neededBytes(it.size, SharedItems.RESERVE_BYTES);
        long free = dir.getUsableSpace();
        File external = act.ctx().getExternalFilesDir(null);  // where Downloads is (the same disk on most phones)
        if (external != null) free = Math.min(free, external.getUsableSpace());
        if (free < need) return BackupNow.fail(KeptFiles.notEnoughSpace(need, free));
        java.security.MessageDigest md = KeptFiles.sha256();
        byte[][] sha = new byte[1][];
        long[] size = new long[1];
        String place = saveToDownloads(KeptFiles.saveName(it), "text/plain", out -> {
            size[0] = KeptFiles.copy(dir, it, out, md);
            sha[0] = md.digest();
            return size[0];
        }, KeptFiles.EMPTY, in -> KeptFiles.verify(in, sha[0], size[0]));  // the proof that the copy is whole
        String saved = new File(place).getName();  // the name it really has: Android may have changed it ("name (1).txt")
        boolean appFolder = Build.VERSION.SDK_INT < 29;  // Android 8 and 9: the app's own folder, deleted with the app
        return KeptFiles.saved(saved, BackupNow.where(appFolder, act.ctx().getPackageName(), saved), size[0], appFolder);
    }

    /**
     * Delete, step 1: the page asks to delete a kept file (a name keptFiles gave). Answers JSON {ok:true, token, item} with the file as it is
     * now (the confirm screen shows it) or {ok:false, text} with one plain sentence; changes nothing. Refused while work or the nightly run is
     * going, while a backup or restore runs, while the library is locked, and for any name that is not a kept file's.
     */
    @JavascriptInterface
    public String askDeleteKept(String name) {
        if (!ok()) return "";
        try {
            return KeptFiles.ask(keptEnv(), name);
        } catch (Throwable t) {
            return KeptFiles.refuse(KeptFiles.NOT_DELETED);
        }
    }

    /**
     * Delete, step 2: deletes that one kept file, only with the one-use token askDeleteKept gave for it, and never while work or the nightly run
     * is going, a backup or restore runs, or the library is locked (all asked again here, under the same one-at-a-time flag the backup and
     * restore use). Nothing else is touched. Done with JSON {deleted, bytes} or one plain sentence (nothing was deleted).
     */
    @JavascriptInterface
    public void deleteKept(int id, String name, String token) {
        if (!ok()) return;
        work.execute(() -> {
            BackupNow.Outcome o;
            try {
                o = KeptFiles.delete(keptEnv(), name, token);
            } catch (Throwable t) {  // an Error too: the page must never stay on "Deleting..."
                o = BackupNow.fail(KeptFiles.NOT_DELETED);
            }
            done(id, o.ok, o.text);
        });
    }

    /**
     * What was shared while the app was closed: [{id, text, at}]. The items stay in the list until the page has saved
     * what it made of them and says so with ackShared, so nothing is lost when a save fails or the app dies in between.
     */
    @JavascriptInterface
    public String peekShared() {
        if (!ok()) return "[]";
        synchronized (SHARED_LOCK) {
            SharedQueue.Peeked p = SharedQueue.peek(prefs.getString(SHARED_KEY, "[]"), () -> java.util.UUID.randomUUID().toString());
            if (p.changed) prefs.edit().putString(SHARED_KEY, p.queue).commit();  // items from before ids existed get theirs
            return p.items;
        }
    }

    /** Removes the items with these ids (a JSON array of strings) from the list. Asking again, or from the other page, is harmless. */
    @JavascriptInterface
    public void ackShared(String idsJson) {
        if (!ok()) return;
        synchronized (SHARED_LOCK) {
            String cur = prefs.getString(SHARED_KEY, "[]");
            String next = SharedQueue.acknowledge(cur, idsJson);
            if (next.equals(cur)) return;
            if ("[]".equals(next)) prefs.edit().remove(SHARED_KEY).commit();
            else prefs.edit().putString(SHARED_KEY, next).commit();
        }
    }

    @JavascriptInterface
    public String getSettings() {
        if (!ok()) return "{}";
        return prefs.getString("local_settings", "{}");
    }

    @JavascriptInterface
    public void setSettings(String json) {
        if (!ok() || json == null) return;
        synchronized (SETTINGS_LOCK) {
            prefs.edit().putString("local_settings", json).apply();
        }
    }

    /**
     * Merges the keys a page changed (a JSON object) into the stored settings and returns the result. Keys the page did
     * not change are left as they are, so one page cannot revert what the other saved.
     */
    @JavascriptInterface
    public String patchSettings(String patchJson) {
        if (!ok() || patchJson == null) return "";
        synchronized (SETTINGS_LOCK) {
            String merged = SettingsPatch.merge(prefs.getString("local_settings", "{}"), patchJson);
            prefs.edit().putString("local_settings", merged).apply();
            return merged;
        }
    }

    // ------------------------------------------------------------------ talking to other apps

    @JavascriptInterface
    public void copy(String text) {
        if (!ok()) return;
        act.runOnUiThread(() -> {
            ClipboardManager cm = (ClipboardManager) act.ctx().getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("Reel Shelf", text == null ? "" : text));
        });
    }

    /** Opens the Android share menu with this text (pick Meta AI, WhatsApp, Instagram, Claude...). */
    @JavascriptInterface
    public void shareText(String text, String title) {
        if (!ok()) return;
        Intent send = new Intent(Intent.ACTION_SEND);
        send.setType("text/plain");
        send.putExtra(Intent.EXTRA_TEXT, text == null ? "" : text);
        act.runOnUiThread(() -> {
            try {
                act.startActivity(Intent.createChooser(send, title == null || title.isEmpty() ? "Send to" : title));
            } catch (Exception e) {
                act.toast("No app can receive this");
            }
        });
    }

    @JavascriptInterface
    public void openUrl(String url) {
        if (!ok() || url == null || !url.startsWith("https://")) return;
        act.runOnUiThread(() -> act.openExternal(Uri.parse(url)));
    }


    /** Saves a text file to Downloads/ReelShelf. Calls back with the place it was saved. */
    @JavascriptInterface
    public void saveFile(int id, String name, String mime, String text) {
        if (!ok()) return;
        String safe = new File(name == null || name.isEmpty() ? "reel-shelf.txt" : name).getName().replaceAll("[^A-Za-z0-9._-]", "_");
        byte[] data = (text == null ? "" : text).getBytes(StandardCharsets.UTF_8);
        runWork(() -> {
            try {
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.Downloads.DISPLAY_NAME, safe);
                    v.put(MediaStore.Downloads.MIME_TYPE, mime == null || mime.isEmpty() ? "text/plain" : mime);
                    v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/ReelShelf");
                    Uri uri = act.ctx().getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                    if (uri == null) throw new IOException("Android did not give a place to save");
                    try (OutputStream out = act.ctx().getContentResolver().openOutputStream(uri)) {
                        if (out == null) throw new IOException("Could not write the file");
                        out.write(data);
                    }
                    done(id, true, "Downloads/ReelShelf/" + safe);
                } else {
                    File d = new File(act.ctx().getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "ReelShelf");
                    //noinspection ResultOfMethodCallIgnored
                    d.mkdirs();
                    File f = new File(d, safe);
                    try (OutputStream out = new FileOutputStream(f)) {
                        out.write(data);
                    }
                    done(id, true, f.getPath());
                }
            } catch (Exception e) {
                done(id, false, "Could not save: " + e.getMessage());
            }
        });
    }

    // ------------------------------------------------------------------ reading a reel's public page

    private static boolean readable(String url) {
        return url != null && (url.startsWith("https://www.instagram.com/") || url.startsWith("https://www.youtube.com/")
                || url.startsWith("https://m.youtube.com/"));
    }

    /**
     * Fetches a public page: a reel's embed page (caption, creator) or a YouTube page / caption file (title,
     * description, what is said). Only Instagram and YouTube addresses; no login, no account cookies.
     */
    @JavascriptInterface
    public void fetchPage(int id, String url) {
        if (!ok()) return;
        if (!readable(url)) {
            done(id, false, "Only Instagram and YouTube pages can be read");
            return;
        }
        request(id, url, null);
    }

    /** The YouTube player request (title, description and the list of caption files of a video). */
    @JavascriptInterface
    public void postJson(int id, String url, String body) {
        if (!ok()) return;
        if (url == null || !url.startsWith("https://www.youtube.com/youtubei/v1/player")) {
            done(id, false, "Not allowed");
            return;
        }
        request(id, url, body == null ? "{}" : body);
    }

    /**
     * YouTube requests as one of YouTube's own apps ("ios", "android" or "web"): the player (title, description, caption
     * list) or the "Show transcript" panel. When YouTube blocks one app, the page tries the next. No account, no cookies.
     */
    @JavascriptInterface
    public void postYoutube(int id, String url, String body, String client) {
        if (!ok()) return;
        if (url == null || !(url.startsWith("https://www.youtube.com/youtubei/v1/player")
                || url.startsWith("https://www.youtube.com/youtubei/v1/get_transcript"))) {
            done(id, false, "Not allowed");
            return;
        }
        String[] h = YT_APPS.containsKey(client) ? YT_APPS.get(client) : YT_APPS.get("android");
        request(id, url, body == null ? "{}" : body, h[0], h[1], h[2]);
    }

    private static final String WEB_UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36";

    /** User agent, X-YouTube-Client-Name, X-YouTube-Client-Version for each YouTube app the page may ask as. */
    private static final java.util.Map<String, String[]> YT_APPS = new java.util.HashMap<>();
    static {
        YT_APPS.put("android", new String[]{"com.google.android.youtube/20.10.38 (Linux; U; Android 14) gzip", "3", "20.10.38"});
        YT_APPS.put("ios", new String[]{"com.google.ios.youtube/20.10.38 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)", "5", "20.10.38"});
        YT_APPS.put("web", new String[]{WEB_UA, "1", ""});
    }

    private void request(int id, String url, String body) {
        String[] a = YT_APPS.get("android");
        request(id, url, body, body != null ? a[0] : WEB_UA, body != null ? a[1] : null, body != null ? a[2] : null);
    }

    private void request(int id, String url, String body, String ua, String clientName, String clientVersion) {
        net.execute(() -> {
            HttpURLConnection c = null;
            try {
                c = (HttpURLConnection) new URL(url).openConnection();
                c.setConnectTimeout(15000);
                c.setReadTimeout(20000);
                c.setInstanceFollowRedirects(true);
                boolean yt = url.contains("youtube.com/");
                c.setRequestProperty("User-Agent", ua);
                c.setRequestProperty("Accept-Language", "en-US,en;q=0.8");
                if (yt) c.setRequestProperty("Cookie", "CONSENT=YES+cb");  // skips the cookie banner page, no account
                if (yt && clientName != null) c.setRequestProperty("X-YouTube-Client-Name", clientName);
                if (yt && clientVersion != null && !clientVersion.isEmpty()) c.setRequestProperty("X-YouTube-Client-Version", clientVersion);
                if (body != null) {
                    c.setRequestMethod("POST");
                    c.setDoOutput(true);
                    c.setRequestProperty("Content-Type", "application/json");
                    try (OutputStream out = c.getOutputStream()) {
                        out.write(body.getBytes(StandardCharsets.UTF_8));
                    }
                }
                int code = c.getResponseCode();
                if (code != 200) {
                    done(id, false, (yt ? "YouTube" : "Instagram") + " answered " + code);
                    return;
                }
                // only the site that was asked: a redirect to another site (a sign-in or consent page) is not read
                if (!c.getURL().getHost().equals(new URL(url).getHost())) {
                    done(id, false, (yt ? "YouTube" : "Instagram") + " sent a sign-in or consent page");
                    return;
                }
                try (InputStream in = c.getInputStream()) {
                    ByteArrayOutputStream b = new ByteArrayOutputStream();
                    byte[] buf = new byte[16384];
                    int n;
                    while ((n = in.read(buf)) > 0 && b.size() < 4_000_000) b.write(buf, 0, n);
                    done(id, true, b.toString("UTF-8"));
                }
            } catch (Exception e) {
                done(id, false, "No internet, or the site did not answer (" + e.getClass().getSimpleName() + ")");
            } finally {
                if (c != null) c.disconnect();
            }
        });
    }

    // ------------------------------------------------------------------ the on-phone AI model

    /** The answer for a model file without starting any work: "checking" while its check runs, else ModelCheck.known (yes, no, unknown or own). */
    private String verdict(ModelCatalog.Entry row, File f) {
        return model.checks.running(f) ? ModelCheck.CHECKING : ModelCheck.known(row, f);
    }

    /**
     * {"file", "ready", "bytes", "partial", "downloading", "backend", "free", "installed", "verified", "kept"}. "ready" only
     * means the file exists. "verified" is "yes", "no", "unknown", "checking" or "own" (see ModelCheck); "kept" is true once
     * you chose to keep using a file that is not the published one. Nothing is started here: checkModel does that.
     */
    @JavascriptInterface
    public String modelInfo(String name) {
        if (!ok()) return "{}";
        File f = model.file(name);
        File part = new File(f.getPath() + ".part");
        JSONObject o = new JSONObject();
        try {
            o.put("file", f.getName());
            o.put("ready", f.isFile());
            o.put("verified", verdict(ModelCatalog.lookup(name), f));
            o.put("kept", ModelCheck.kept(f));
            o.put("bytes", f.isFile() ? f.length() : 0);
            o.put("partial", part.isFile() ? part.length() : 0);
            o.put("downloading", downloading && !speechDownloading);  // the speech model's download is not the AI model's
            o.put("backend", model.backendInUse());
            o.put("free", model.dir().getUsableSpace());
            JSONArray all = new JSONArray();
            File[] files = model.dir().listFiles();
            if (files != null) for (File x : files) if (x.getName().endsWith(".litertlm")) all.put(x.getName());
            o.put("installed", all);
        } catch (JSONException ignored) {
            // not reachable
        }
        return o.toString();
    }

    /** Downloads one of the models in ModelCatalog by its file name. The address the page sends (url) is ignored: Java knows the pinned one. */
    @JavascriptInterface
    public void downloadModel(int id, String url, String name) {
        if (!ok()) return;
        ModelCatalog.Entry entry = ModelCatalog.lookup(name);
        if (entry == null) {
            done(id, false, ModelCatalog.UNKNOWN);
            return;
        }
        if (downloading) {
            done(id, false, speechDownloading ? "Speech to text is downloading. Wait until it is done, then download the model." : "Already downloading");
            return;
        }
        model.checks.cancel();  // a download you start wins over a model check (the check starts again later)
        downloading = true;
        net.execute(() -> {
            try {
                model.download(entry, (d, t) -> progress("download", d, t));
                done(id, true, "ready");
            } catch (InterruptedIOException e) {
                done(id, false, "paused");
            } catch (Exception e) {
                done(id, false, e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
            } finally {
                downloading = false;
            }
        });
    }

    @JavascriptInterface
    public void stopModel() {
        if (!ok()) return;
        model.stopAll();
    }

    /**
     * The check of the model file called name: "yes", "no", "unknown", "checking" or "own" (see ModelCheck). A file with
     * no result yet is read once in the background and this answers "checking"; the page is told when it ends (progress
     * "check"). Settings calls this; the nightly run never does and is refused here anyway. It does not start while the
     * app is off screen, a download or a job runs, or the battery is low (then the answer stays "unknown"). Only the
     * answer is kept next to the file: the model itself is never touched.
     */
    @JavascriptInterface
    public String checkModel(String name) {
        if (!ok()) return ModelCheck.UNKNOWN;
        ModelCatalog.Entry row = ModelCatalog.lookup(name);
        File f = model.file(name);
        String v = verdict(row, f);
        if (!ModelCheck.UNKNOWN.equals(v) || !f.isFile()) return v;
        int level = -1;
        boolean charging = false;
        try {
            JSONObject b = shots.battery();  // the level the app already reads; no new permission
            level = b.optInt("level", -1);
            charging = b.optBoolean("charging", false);
        } catch (JSONException ignored) {
            // unknown battery does not stop a check
        }
        if (ModelCheck.refuse(onScreen, act.isNight(), downloading, jobs.get() > 0, level, charging) != null) return v;
        boolean started = model.checks.start(work, row, f, () -> onScreen && jobs.get() == 0, r -> progress("check", 0, 0));  // asked again when the worker gets to it
        return started ? ModelCheck.CHECKING : v;
    }

    /** "Stop checking": the running check stops before its next read and records nothing. */
    @JavascriptInterface
    public void stopCheck() {
        if (!ok()) return;
        model.checks.cancel();
    }

    /** "Keep using it": remembers that you chose to keep a model file that is not the published one. The file is not touched. */
    @JavascriptInterface
    public boolean keepModel(String name) {
        if (!ok()) return false;
        return ModelCheck.keep(ModelCatalog.lookup(name), model.file(name));
    }

    @JavascriptInterface
    public boolean deleteModel(String name) {
        if (!ok()) return false;
        model.stopAll();
        File f = model.file(name);
        File part = new File(f.getPath() + ".part");
        boolean a = !f.exists() || f.delete();
        boolean b = !part.exists() || part.delete();
        if (a) ModelCheck.forget(f);  // its own bookkeeping goes with it
        synchronized (pickLock) {
            if (!picking) ModelCheck.clearPickTemp(model.dir());  // a pick that was cut off left a copy of up to several GB; not while a pick is copying
        }
        return a && b;
    }

    /**
     * Lets you pick your own .litertlm model file; it is copied into the app (progress as "import"). It is your own file
     * ("own": Reel Shelf does not claim it is the published one). It never takes the name of a model Reel Shelf downloads
     * and never replaces a file that is already there: a name in use gets " (own)" added (ModelCheck.keepPicked). The copy
     * is made under a temporary name of its own, so a download you paused is never touched either.
     */
    @JavascriptInterface
    public void pickModel(int id) {
        if (!ok()) return;
        act.runOnUiThread(() -> act.pickModelFile(uri -> net.execute(() -> {
            if (uri == null) {
                done(id, false, "cancelled");
                return;
            }
            String name = act.displayName(uri);
            if (name == null || !name.endsWith(".litertlm")) {
                done(id, false, "Choose a .litertlm model file");
                return;
            }
            model.checks.cancel();  // a copy you started wins over a model check
            synchronized (pickLock) {
                picking = true;  // deleteModel leaves the temporary copy alone from here to the end of this pick
                ModelCheck.clearPickTemp(model.dir());  // what an earlier pick that was cut off (the app was killed) left behind
            }
            try {
                savePicked(id, uri, name);
            } finally {
                picking = false;
            }
        })));
    }

    /** Copies the picked file to a temporary file of its own, then keeps it as an own model (ModelCheck.keepPicked). Always ends with done(). */
    private void savePicked(int id, Uri uri, String name) {
        File part = ModelCheck.pickTemp(model.dir());
        try (InputStream in = act.ctx().getContentResolver().openInputStream(uri); OutputStream out = new FileOutputStream(part)) {
            if (in == null) throw new IOException("Could not open the file");
            byte[] buf = new byte[1 << 16];
            long total = act.sizeOf(uri);
            long d = 0;
            long last = 0;
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
                d += n;
                if (d - last > 8L * 1024 * 1024) {
                    last = d;
                    progress("import", d, total);
                }
            }
        } catch (Exception e) {
            //noinspection ResultOfMethodCallIgnored
            part.delete();
            done(id, false, "Could not copy the model: " + e.getMessage());
            return;
        }
        File dest;
        try {
            dest = ModelCheck.keepPicked(part, model.dir(), name);
        } catch (IOException | RuntimeException e) {  // an odd name must never end the app or leave the page waiting
            //noinspection ResultOfMethodCallIgnored
            part.delete();  // our own temporary copy; the file you picked is untouched
            done(id, false, "Could not save the model file");
            return;
        }
        done(id, true, dest.getName());
    }

    /** Runs the model once. opts: {"file", "gpu", "system", "maxTokens", "temperature"}. Answers {"text", "backend", "tokens", "ms"}. */
    @JavascriptInterface
    public void generate(int id, String prompt, String opts) {
        if (!ok()) return;
        runWork(() -> {
            try {
                JSONObject o = new JSONObject(opts == null || opts.isEmpty() ? "{}" : opts);
                long t0 = System.currentTimeMillis();
                java.util.List<File> frames = new java.util.ArrayList<>();
                File sound = null;
                String out;
                boolean media = o.optBoolean("media", false);
                if (media) ReelVideo.BUSY.incrementAndGet();  // before the files are looked at: the temp sweep leaves the key frames and sound alone from here to the end of the call
                try {
                    if (media) {  // the current reel's key frames and sound, made by readLocalVideo
                        File dir = ReelVideo.mediaDir(act.ctx());
                        for (int i = 0; i < 4; i++) {
                            File f = new File(dir, "frame" + i + ".jpg");
                            if (f.isFile()) frames.add(f);
                        }
                        File w = new File(dir, "sound.wav");
                        if (w.isFile()) sound = w;
                    }
                    out = model.generate(model.file(o.optString("file", "")), o.optBoolean("gpu", true), o.optString("system", ""),
                            prompt == null ? "" : prompt, o.optInt("maxTokens", 800), o.optDouble("temperature", 0.3), frames, sound);
                } finally {
                    if (media) {
                        ReelVideo.clearMedia(act.ctx());
                        ReelVideo.BUSY.decrementAndGet();
                    }
                }
                JSONObject r = new JSONObject();
                r.put("text", out);
                r.put("backend", model.backendInUse());
                r.put("tokens", model.lastTokens());  // -1 when the engine did not say; the page does not store it
                r.put("ms", System.currentTimeMillis() - t0);
                done(id, true, r.toString());
            } catch (InterruptedIOException e) {
                done(id, false, "stopped");
            } catch (Throwable e) {
                String msg = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
                done(id, false, "The AI model failed: " + msg);
            }
        });
    }

    @JavascriptInterface
    public void allowWork() {
        if (!ok()) return;
        model.allow();
    }

    /** Where Instagram's own "Download your information" page is. Opened in Chrome, never inside Reel Shelf. */
    static final String IG_EXPORT_PAGE = "https://accountscenter.instagram.com/info_and_permissions/dyi/";
    static final String IG_WAITING_KEY = "ig_export_opened_at";

    /** Opens Instagram's export page in the browser (you sign in there; Reel Shelf never sees it) and starts the reminder. */
    @JavascriptInterface
    public void openInstagram() {
        if (!ok()) return;
        prefs.edit().putLong(IG_WAITING_KEY, System.currentTimeMillis()).apply();
        act.runOnUiThread(() -> act.openExternal(android.net.Uri.parse(IG_EXPORT_PAGE)));
    }

    /** When the Instagram export page was opened and no export was chosen since (ms), or 0. Shown as a reminder. */
    @JavascriptInterface
    public long instagramWaitingSince() {
        if (!ok()) return 0;
        return prefs.getLong(IG_WAITING_KEY, 0);
    }

    @JavascriptInterface
    public void dismissInstagramWaiting() {
        if (!ok()) return;
        prefs.edit().remove(IG_WAITING_KEY).apply();
    }

    // ------------------------------------------------------------------ screenshots (text read on the phone)

    /** The folders you picked for screenshots: [{uri, name}]. */
    @JavascriptInterface
    public String shotFolders() {
        if (!ok()) return "[]";
        return shots.folders().toString();
    }

    /** Opens Android's folder picker (starts at DCIM/Screenshots). Calls back with {uri, name}. */
    @JavascriptInterface
    public void addShotFolder(int id) {
        if (!ok()) return;
        act.runOnUiThread(() -> act.pickFolder(uri -> {
            if (uri == null) {
                done(id, false, "cancelled");
                return;
            }
            try {
                done(id, true, shots.addFolder(uri).toString());
            } catch (Exception e) {
                done(id, false, "Could not keep access to that folder: " + e.getMessage());
            }
        }));
    }

    // ------------------------------------------------------------------ what a reel shows and says (its video)

    /** True while the one running download (the shared "downloading" flag) is the speech model: only what the page shows for it. */
    private volatile boolean speechDownloading;

    /** {ready, downloading, size, partial} for the offline speech model (partial: bytes of an unfinished download). */
    @JavascriptInterface
    public String speechInfo() {
        if (!ok()) return "{}";
        JSONObject o = new JSONObject();
        try {
            File part = new File(speechZip().getPath() + ".part");
            o.put("ready", SpeechModel.dir(act.ctx()) != null);
            o.put("downloading", speechDownloading);
            o.put("size", SpeechModel.SIZE);
            o.put("partial", part.isFile() ? part.length() : 0);
        } catch (JSONException ignored) {
        }
        return o.toString();
    }

    /** The speech model's ZIP while it is downloaded (and for a moment while it is unpacked): in the app's own storage, next to the AI models. */
    private File speechZip() {
        return new File(model.dir(), ModelCatalog.SPEECH.file);
    }

    /**
     * Downloads (resuming) the offline speech model, checks its size, SHA-256 and MD5 against ModelCatalog.SPEECH, and only
     * then unpacks it (ModelZip). One download at a time, the same flag as the AI model. Progress as "speech".
     */
    @JavascriptInterface
    public void downloadSpeech(int id) {
        if (!ok()) return;
        if (downloading) {
            done(id, false, speechDownloading ? "Already downloading" : "The AI model is downloading. Wait until it is done, then download speech to text.");
            return;
        }
        model.checks.cancel();  // a download you start wins over a model check
        speechDownloading = true;
        downloading = true;
        net.execute(() -> {
            try {
                ModelZip.fetch(model.verifier(), ModelCatalog.SPEECH, speechZip(), SpeechModel.root(act.ctx()), ModelCatalog.SPEECH_ZIP,
                        (d, t) -> progress("speech", d, t));
                if (SpeechModel.dir(act.ctx()) == null) throw new IOException("The speech model did not unpack");
                done(id, true, "ready");
            } catch (InterruptedIOException e) {
                done(id, false, "paused");
            } catch (Exception e) {
                done(id, false, e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
            } finally {
                speechDownloading = false;  // first: once "downloading" is free, a new download may start and set its own label
                downloading = false;
            }
        });
    }

    @JavascriptInterface
    public void deleteSpeech() {
        if (!ok()) return;
        SpeechModel.delete(SpeechModel.root(act.ctx()));
    }

    // ------------------------------------------------------------------ reel videos on the phone (the whole reel)

    /** The folders you picked for reel videos: [{uri, name}]. */
    @JavascriptInterface
    public String videoFolders() {
        if (!ok()) return "[]";
        return shots.foldersOf(ScreenshotReader.VIDEO_FOLDERS).toString();
    }

    /** Android's folder picker, for where Instagram's Download or screen recordings put reels. Calls back with {uri, name}. */
    @JavascriptInterface
    public void addVideoFolder(int id) {
        if (!ok()) return;
        act.runOnUiThread(() -> act.pickFolder(uri -> {
            if (uri == null) {
                done(id, false, "cancelled");
                return;
            }
            try {
                done(id, true, shots.addFolderTo(ScreenshotReader.VIDEO_FOLDERS, uri).toString());
            } catch (Exception e) {
                done(id, false, "Could not keep access to that folder: " + e.getMessage());
            }
        }));
    }

    @JavascriptInterface
    public void removeVideoFolder(String uri) {
        if (!ok() || uri == null) return;
        shots.removeFolderFrom(ScreenshotReader.VIDEO_FOLDERS, uri);
    }

    /** Every video in the picked folders and the shared ones: [{k, n, f, m, s}]. */
    @JavascriptInterface
    public void listVideos(int id) {
        if (!ok()) return;
        shots.allow();
        ocr.execute(() -> {
            try {
                done(id, true, shots.listVideos().toString());
            } catch (Exception e) {
                done(id, false, "Could not list the folder: " + e.getMessage());
            }
        });
    }

    /** Reads one whole reel video from the phone: {screen, speech, seconds, speechModel, media}. Only picked or shared ones. */
    @JavascriptInterface
    public void readLocalVideo(int id, String key) {
        if (!ok()) return;
        if (!shots.videoAllowed(key)) {
            done(id, false, "Only videos in a folder you picked, or shared to Reel Shelf, can be read");
            return;
        }
        shots.allow();
        ocr.execute(() -> {
            try {
                done(id, true, ReelVideo.readLocal(act.ctx(), shots, SpeechModel.dir(act.ctx()), Uri.parse(key), shots::stopped).toString());
            } catch (Throwable e) {
                done(id, false, e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
            }
        });
    }

    /** Pick pictures (for example a reel's comments) and get their text back, read on the phone. Nothing is kept. */
    @JavascriptInterface
    public void readPictures(int id) {
        if (!ok()) return;
        act.runOnUiThread(() -> act.pickImages(uris -> {
            if (uris == null || uris.isEmpty()) {
                done(id, false, "cancelled");
                return;
            }
            shots.allow();
            ocr.execute(() -> {
                StringBuilder out = new StringBuilder();
                for (Uri u : uris) {
                    try (InputStream in = act.ctx().getContentResolver().openInputStream(u)) {
                        if (in == null) continue;
                        ByteArrayOutputStream b = new ByteArrayOutputStream();
                        byte[] buf = new byte[65536];
                        int n;
                        while ((n = in.read(buf)) > 0 && b.size() < 30_000_000) b.write(buf, 0, n);
                        out.append(shots.readBytes(b.toByteArray())).append('\n');
                    } catch (Exception ignored) {
                        // one picture that cannot be read
                    }
                }
                done(id, true, out.toString());
            });
        }));
    }

    /**
     * "Look it up online" (only when you switched it on in Settings): your question goes to Wikipedia and DuckDuckGo
     * Instant Answers (free, no key, no account, not AI). Returns [{title, url, text, source}] JSON. Nothing else is sent.
     */
    @JavascriptInterface
    public void webSearch(int id, String question) {
        if (!ok()) return;
        net.execute(() -> {
            try {
                done(id, true, new WebLookup(TitleVerifier.NET).search(question).toString());
            } catch (Exception e) {
                done(id, false, e.getMessage() == null ? "The search did not work" : e.getMessage());
            }
        });
    }

    /** A quote's first words to Wikiquote's search (part of Process, like the title check). {found, page, url, snippet}. */
    @JavascriptInterface
    public void quoteCheck(int id, String text) {
        if (!ok()) return;
        net.execute(() -> {
            try {
                done(id, true, new WebLookup(TitleVerifier.NET).quote(text).toString());
            } catch (Exception e) {
                done(id, false, e.getMessage() == null ? "The quote check did not work" : e.getMessage());
            }
        });
    }

    /** A product name (from a label, a store page or a reel's notes) to the open product databases. {results: [...]} */
    @JavascriptInterface
    public void productCheck(int id, String name) {
        if (!ok()) return;
        net.execute(() -> {
            try {
                done(id, true, new WebLookup(TitleVerifier.NET).product(name).toString());
            } catch (Exception e) {
                done(id, false, e.getMessage() == null ? "The product check did not work" : e.getMessage());
            }
        });
    }

    /** The search mic: what you said, as text. Android's own recognizer listens, not this app (no microphone permission). */
    @JavascriptInterface
    public void listen(int id) {
        if (!ok()) return;
        act.runOnUiThread(() -> act.listen(said -> {
            if (said == null) done(id, false, "cancelled");
            else if (said.isEmpty()) done(id, false, "This phone has no speech recognizer. Install Google's speech services from the Play Store.");
            else done(id, true, said);
        }));
    }

    /** Opens Android's picture picker (choose one or many screenshots). Calls back with how many were added. */
    @JavascriptInterface
    public void addShotPictures(int id) {
        if (!ok()) return;
        act.runOnUiThread(() -> act.pickImages(uris -> {
            if (uris == null || uris.isEmpty()) {
                done(id, false, "cancelled");
                return;
            }
            ocr.execute(() -> {
                MediaBatch.Report r = ScreenshotReader.addPictures(act.ctx(), uris);
                if (r.saved() == 0) done(id, false, "Could not keep those pictures" + (r.failed() > 0 ? ": " + r.firstWhy() : ""));
                else done(id, true, r.pickerAnswer());  // a picture kept before counts: it is in the app
            });
        }));
    }

    @JavascriptInterface
    public void removeShotFolder(String uri) {
        if (!ok() || uri == null) return;
        shots.removeFolder(uri);
    }

    /** Every picture in the picked folders: [{k, n, f, m, s}] (k is the picture's address, m when it was saved). */
    @JavascriptInterface
    public void listShots(int id) {
        if (!ok()) return;
        shots.allow();
        ocr.execute(() -> {
            try {
                done(id, true, shots.list().toString());
            } catch (Exception e) {
                done(id, false, "Could not list the folder: " + e.getMessage());
            }
        });
    }

    /** Reads the text of a few pictures, one after the other: [{k, ok, W, H, lines}]. Stops when you leave the app. */
    @JavascriptInterface
    public void readShots(int id, String keysJson) {
        if (!ok()) return;
        shots.allow();
        ocr.execute(() -> {
            JSONArray out = new JSONArray();
            try {
                JSONArray keys = new JSONArray(keysJson == null ? "[]" : keysJson);
                for (int i = 0; i < keys.length() && i < 50; i++) {
                    if (shots.stopped()) break;
                    out.put(shots.read(keys.getString(i)));
                }
                if (shots.stopped() && out.length() == 0) done(id, false, "stopped");
                else done(id, true, out.toString());
            } catch (Exception e) {
                done(id, false, "Could not read the pictures: " + e.getMessage());
            }
        });
    }

    @JavascriptInterface
    public void stopShots() {
        if (!ok()) return;
        shots.stop();
    }

    /** A small preview of one picture as a data: URL ("" when it cannot be opened). */
    @JavascriptInterface
    public String shotThumb(String key, int side) {
        if (!ok()) return "";
        return shots.thumb(key, side <= 0 ? 320 : Math.min(side, 800));
    }

    /** Opens one screenshot in Google Lens (or the share menu), to search the picture yourself. */
    @JavascriptInterface
    public void shotToLens(String key) {
        if (!ok() || !shots.allowed(key)) return;
        act.runOnUiThread(() -> act.sendToLens(Uri.parse(key)));
    }

    /** {level, charging} */
    @JavascriptInterface
    public String battery() {
        if (!ok()) return "{}";
        try {
            return shots.battery().toString();
        } catch (JSONException e) {
            return "{}";
        }
    }

    /** Keeps the screen on while a long run is going (only while the app is open). */
    @JavascriptInterface
    public void keepAwake(boolean on) {
        if (!ok()) return;
        act.keepScreenOn(on);
    }

    /**
     * What has been read from screenshots so far (its own file, so the library file stays small). A list that cannot be
     * read is set aside (renamed, kept) and read again from scratch: it only holds what can be rebuilt from the pictures.
     */
    @JavascriptInterface
    public String loadShots() {
        if (!ok()) return "";
        LibraryFile f = shotsFile();
        synchronized (f) {
            LibraryFile.Loaded l = f.load();
            if (l.state == LibraryFile.State.UNREADABLE) {
                try {
                    f.startNew();
                } catch (IOException e) {
                    // stays locked: nothing is written over it
                }
            }
            shotsRev = f.revision();
            return l.text;
        }
    }

    @JavascriptInterface
    public boolean storeShots(String json) {
        if (!ok() || json == null) return false;
        LibraryFile.Result r = shotsFile().write(json, shotsRev);
        if (r.ok) shotsRev = r.revision;
        return r.ok;
    }

    // ------------------------------------------------------------------ the watchlist's online check

    /**
     * Process: checks the watchlist titles that were never checked against the free databases (TMDB with your own
     * key, Wikidata, AniList, Jikan, MangaDex). Progress as "verify"; the answer is a summary. The results wait in
     * verify-results.json until the page takes them (takeVerified). Stops when you leave the app.
     */
    @JavascriptInterface
    public void verifyNow(int id) {
        if (!ok()) return;
        if (VerifyJob.running()) {
            done(id, false, "The check is already running");
            return;
        }
        verifyStop.set(false);
        verifyWork.execute(() -> {
            try {
                TitleVerifier v = new TitleVerifier(TitleVerifier.NET, TitleVerifier.REAL_CLOCK, NightlyCheck.tmdbKey(act.ctx()), verifyStop);
                v.omdbKey = NightlyCheck.omdbKey(act.ctx());
                JSONObject sum = new VerifyJob(act.ctx().getFilesDir(), v, verifyStop).run(0, 0, (d, t, title) -> progress("verify", d, t));
                done(id, true, sum.toString());
            } catch (Throwable e) {
                done(id, false, "The online check failed: " + (e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage()));
            }
        });
    }

    @JavascriptInterface
    public void stopVerify() {
        if (!ok()) return;
        verifyStop.set(true);
    }

    /** Answers not yet applied to the watchlist, {id: result}; each is handed out once. */
    @JavascriptInterface
    public String takeVerified() {
        if (!ok()) return "{}";
        return VerifyJob.take(act.ctx().getFilesDir());
    }

    /** The nightly check (phone not in use, battery at 40% or more, any internet). Off unless you switch it on. */
    @JavascriptInterface
    public void setNightly(boolean on) {
        if (!ok()) return;
        prefs.edit().putBoolean("nightly_check", on).apply();
        NightlyCheck.schedule(act.ctx(), on);
    }

    /** {"on", "scheduled", "last": {checked, verified, review, notFound, left, at}} */
    @JavascriptInterface
    public String nightlyInfo() {
        if (!ok()) return "{}";
        JSONObject o = new JSONObject();
        try {
            o.put("on", prefs.getBoolean("nightly_check", false));
            o.put("scheduled", NightlyCheck.scheduled(act.ctx()));
            o.put("running", VerifyJob.running());
            String last = prefs.getString("nightly_last", "");
            if (!last.isEmpty()) o.put("last", new JSONObject(last));
        } catch (JSONException ignored) {
            // not reachable
        }
        return o.toString();
    }

    // ------------------------------------------------------------------ jobs that keep going after you leave the app

    /** A job you started is running: show (or update) its notification, so it keeps going if you leave the app. */
    @JavascriptInterface
    public void workUpdate(String title, String text, int done, int total) {
        if (!ok()) return;
        act.setWorking(true);
        WorkService.show(act.ctx(), title, text, done, total);
    }

    /** No job is running any more: the notification goes and nothing keeps the phone busy. */
    @JavascriptInterface
    public void workEnd() {
        if (!ok()) return;
        act.setWorking(false);
        WorkService.end(act.ctx());
    }

    // ------------------------------------------------------------------ the nightly run

    /** True while a nightly run is still going and this is the app's page (not the nightly page): the app waits for it to finish. */
    @JavascriptInterface
    public boolean nightActive() {
        return ok() && !act.isNight() && WorkService.nightActive();
    }

    /** True when the page runs for the nightly run (no screen): it then does the overnight run and calls nightDone. */
    @JavascriptInterface
    public boolean isNight() {
        return ok() && act.isNight();
    }

    @JavascriptInterface
    public void nightDone() {
        if (!ok()) return;
        act.nightDone();
    }

    /** {on, hour, minBattery, exact}: the nightly run's settings. */
    @JavascriptInterface
    public String nightRunInfo() {
        if (!ok()) return "{}";
        try {
            Context c = act.ctx();
            android.app.AlarmManager am = (android.app.AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
            return new JSONObject().put("on", NightRun.on(c)).put("hour", NightRun.hour(c)).put("minBattery", NightRun.minBattery(c))
                    .put("exact", Build.VERSION.SDK_INT < 31 || (am != null && am.canScheduleExactAlarms())).toString();
        } catch (JSONException e) {
            return "{}";
        }
    }

    @JavascriptInterface
    public void setNightRun(boolean on, int hour, int minBattery) {
        if (!ok()) return;
        Context c = act.ctx();
        NightRun.prefs(c).edit().putBoolean(NightRun.ON, on).putInt(NightRun.HOUR, Math.max(0, Math.min(23, hour)))
                .putInt(NightRun.MIN_BATTERY, Math.max(0, Math.min(100, minBattery))).apply();
        NightRun.schedule(c);
    }
}
