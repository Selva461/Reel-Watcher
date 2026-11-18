package app.reelshelf;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.concurrent.Executor;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import java.util.regex.Pattern;

/**
 * Is a model file that is already on the phone the published one? ModelVerifier proves a new download; this covers the
 * files that were there before (downloaded by an older version, or picked by hand). The answer is one word, "verified"
 * in the page: "yes" (it is the catalog's file), "no" (it is not: the page says so, offers a new download and lets you
 * keep using it), "unknown" (not checked yet), "checking" (a check is running) and "own" (a file you picked yourself: the
 * app does not claim it is the published one). "ready" still only means the file exists, so nothing that works stops
 * working. A model is never deleted or replaced because of this answer.
 *
 * The first time Settings shows a model with no result, the file is read once through SHA-256 in the background (a
 * Runner, on the app's worker thread), and the result is kept in a small sidecar file next to it, "&lt;file&gt;.check",
 * reused while the size and the modified time of the model are the same. The sidecar can never make a model unusable
 * and is never trusted when it is unreadable or does not belong to the file (it is then ignored and written again).
 * Pure Java (files only), tested on a computer.
 */
final class ModelCheck {
    private ModelCheck() {
    }

    static final String YES = "yes", NO = "no", UNKNOWN = "unknown", CHECKING = "checking", OWN = "own";

    /** Below this battery level (and not charging) a check does not start: it reads several GB, once. */
    static final int LOW_BATTERY = 15;

    private static final String EXT = ".litertlm";
    private static final Pattern HEX64 = Pattern.compile("^[0-9a-f]{64}$");
    private static final int READ = 1 << 20;

    // ------------------------------------------------------------------ the answer

    /**
     * What a model file is, from the catalog row for its name (null: the catalog has no such name), its size, the SHA-256
     * of its content (null: not hashed) and whether the user picked it. A picked file and a file the catalog does not know
     * are always "own": never "yes", whatever their hash. Only the catalog's own fingerprint, or an older good one in
     * "accepted", gives "yes". Without a hash a wrong size is already "no" (unless older good files exist, which may have
     * another size) and the right size is "unknown": only the hash can tell.
     */
    static String decide(ModelCatalog.Entry row, long bytes, String sha256, boolean picked) {
        if (picked || row == null) return OWN;
        if (sha256 == null) return bytes != row.bytes && row.accepted.isEmpty() ? NO : UNKNOWN;
        if (row.accepted.contains(sha256)) return YES;
        return bytes == row.bytes && sha256.equals(row.sha256) ? YES : NO;
    }

    /** The answer that needs no work: from the sidecar when it belongs to this file, else from the size alone. "unknown" when only a check can tell. */
    static String known(ModelCatalog.Entry row, File f) {
        try {
            if (!f.isFile()) return UNKNOWN;
            if (row == null) return OWN;
            Record r = read(f);
            if (r != null) {
                if (OWN.equals(r.result)) return OWN;
                String v = decide(row, r.bytes, r.sha256.isEmpty() ? null : r.sha256, false);
                if (!UNKNOWN.equals(v)) return v;
            }
            return decide(row, f.length(), null, false);
        } catch (RuntimeException x) {
            return UNKNOWN;
        }
    }

    // ------------------------------------------------------------------ the sidecar

    /** What a check leaves next to a model: {"sha256","bytes","mtime","result"} and "kept" once you chose to keep a file that failed. */
    static final class Record {
        final String sha256;
        final long bytes;
        final long mtime;
        final String result;
        final boolean kept;

        Record(String sha256, long bytes, long mtime, String result, boolean kept) {
            this.sha256 = sha256;
            this.bytes = bytes;
            this.mtime = mtime;
            this.result = result;
            this.kept = kept;
        }
    }

    static File sidecar(File model) {
        return new File(model.getPath() + ".check");
    }

    /**
     * The recorded result for this exact file, or null: no sidecar, one that cannot be read or is not well formed, or one
     * written for another size or modified time (the file changed since). Never throws.
     */
    static Record read(File model) {
        try {
            File s = sidecar(model);
            if (!s.isFile() || s.length() > 2048) return null;
            JSONObject o = new JSONObject(new String(Files.readAllBytes(s.toPath()), StandardCharsets.UTF_8));
            String result = o.getString("result");
            if (!YES.equals(result) && !NO.equals(result) && !OWN.equals(result)) return null;
            String sha = o.optString("sha256", "");
            if (!sha.isEmpty() && !HEX64.matcher(sha).matches()) return null;
            long bytes = o.getLong("bytes"), mtime = o.getLong("mtime");
            if (bytes < 0 || bytes != model.length() || mtime != model.lastModified()) return null;
            return new Record(sha, bytes, mtime, result, o.optBoolean("kept", false));
        } catch (Exception x) {  // org.json's JSONException is checked on Android and not in the test jar: Exception fits both
            return null;
        }
    }

    /** Writes the sidecar in one step (a temporary file, then a rename). False when it could not be written: the model is not affected. Never throws. */
    static boolean write(File model, Record r) {
        File s = sidecar(model);
        File tmp = new File(s.getPath() + ".tmp");
        try {
            JSONObject o = new JSONObject();
            o.put("sha256", r.sha256);
            o.put("bytes", r.bytes);
            o.put("mtime", r.mtime);
            o.put("result", r.result);
            if (r.kept) o.put("kept", true);
            Files.write(tmp.toPath(), o.toString().getBytes(StandardCharsets.UTF_8));
            try {
                Files.move(tmp.toPath(), s.toPath(), StandardCopyOption.ATOMIC_MOVE);
            } catch (AtomicMoveNotSupportedException x) {
                Files.move(tmp.toPath(), s.toPath(), StandardCopyOption.REPLACE_EXISTING);
            }
            return true;
        } catch (Exception x) {
            //noinspection ResultOfMethodCallIgnored
            tmp.delete();
            return false;
        }
    }

    /** Removes the sidecar of a model that is being deleted (its own bookkeeping, never the model). */
    static void forget(File model) {
        //noinspection ResultOfMethodCallIgnored
        sidecar(model).delete();
        //noinspection ResultOfMethodCallIgnored
        new File(sidecar(model).getPath() + ".tmp").delete();
    }

    /** True when you chose "Keep using it" for this file (and it has not changed since). */
    static boolean kept(File model) {
        Record r = read(model);
        return r != null && r.kept;
    }

    /** "Keep using it": remembers, for this exact file, that you chose to keep a file that is not the published one. False for any other answer. */
    static boolean keep(ModelCatalog.Entry row, File f) {
        if (!NO.equals(known(row, f))) return false;
        Record r = read(f);
        return write(f, new Record(r == null ? "" : r.sha256, f.length(), f.lastModified(), NO, true));
    }

    /** A download that just passed ModelVerifier is exactly the catalog's file: recorded as "yes" so it is never read again for nothing. */
    static void recordDownloaded(ModelCatalog.Entry e, File f) {
        write(f, new Record(e.sha256, f.length(), f.lastModified(), YES, false));
    }

    // ------------------------------------------------------------------ the check

    /**
     * Reads the file once through SHA-256 and records the answer. Returns the answer, or null when nothing was decided:
     * stopped (cancelled), the file changed while it was read, or it could not be read. Nothing is recorded then, and the
     * file is never touched. A file that needs no hashing ("own", or the wrong size) is answered without reading it and
     * needs no sidecar. Never throws.
     */
    static String check(ModelCatalog.Entry row, File f, BooleanSupplier cancelled) {
        try {
            if (!f.isFile()) return null;
            long bytes = f.length(), mtime = f.lastModified();
            String quick = decide(row, bytes, null, false);
            if (!UNKNOWN.equals(quick)) return quick;
            String sha = sha256(f, cancelled);
            if (sha == null) return null;
            if (f.length() != bytes || f.lastModified() != mtime) return null;  // replaced or written while it was read
            String v = decide(row, bytes, sha, false);
            write(f, new Record(sha, bytes, mtime, v, false));
            return v;
        } catch (IOException | RuntimeException x) {
            return null;
        }
    }

    /** The SHA-256 of the file in lowercase hex, or null when cancelled (asked before every read). */
    private static String sha256(File f, BooleanSupplier cancelled) throws IOException {
        MessageDigest md;
        try {
            md = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException x) {
            throw new IllegalStateException(x);  // every Java and Android has SHA-256
        }
        try (InputStream in = new FileInputStream(f)) {
            byte[] buf = new byte[READ];
            while (true) {
                if (cancelled.getAsBoolean()) return null;
                int n = in.read(buf);
                if (n < 0) break;
                md.update(buf, 0, n);
            }
        }
        return ModelVerifier.hex(md.digest());
    }

    /**
     * Why a check must not start now, in plain words, or null when it may. A check reads several GB once, so it runs only
     * while the app is on screen, never in the nightly run, never beside a download or a job (it gives way to them), and
     * not on a low battery. Unknown battery (-1) does not stop it.
     */
    static String refuse(boolean onScreen, boolean night, boolean downloading, boolean jobRunning, int batteryPercent, boolean charging) {
        if (night) return "the nightly run does not check models";
        if (!onScreen) return "the app is not on screen";
        if (downloading) return "a download is running";
        if (jobRunning) return "a job is running";
        if (batteryPercent >= 0 && batteryPercent < LOW_BATTERY && !charging) return "the battery is low";
        return null;
    }

    // ------------------------------------------------------------------ one check at a time

    /** Runs at most one check at a time on the executor it is given, and stops it when asked (stopAll, a download, a job, leaving the app). */
    static final class Runner {
        private static final class Run {
            final File file;
            volatile boolean cancelled;

            Run(File file) {
                this.file = file;
            }
        }

        private Run current;

        /**
         * Starts the check of f unless one is running. mayRun is asked again when the worker gets to it (a job may have been
         * queued meanwhile); onEnd gets the answer, or null when the check was stopped, refused or could not decide.
         */
        synchronized boolean start(Executor ex, ModelCatalog.Entry row, File f, BooleanSupplier mayRun, Consumer<String> onEnd) {
            if (current != null) return false;
            Run r = new Run(f);
            current = r;
            try {
                ex.execute(() -> {
                    String v = null;
                    try {
                        if (!r.cancelled && mayRun.getAsBoolean()) v = check(row, f, () -> r.cancelled);
                    } finally {
                        synchronized (Runner.this) {
                            if (current == r) current = null;
                        }
                    }
                    onEnd.accept(v);
                });
            } catch (RuntimeException x) {  // the executor is gone
                current = null;
                return false;
            }
            return true;
        }

        /** True while the check of this file is queued or running. */
        synchronized boolean running(File f) {
            return current != null && current.file.equals(f);
        }

        /** Stops the running check, if any, before its next read; nothing is recorded. */
        synchronized void cancel() {
            if (current != null) current.cancelled = true;
        }
    }

    // ------------------------------------------------------------------ a file you picked

    /**
     * Moves the copy of a file the user picked (tmp) into the models folder and returns where it went. It never takes a
     * name the catalog uses (so it cannot pass as the published model) and never replaces a file that is already there:
     * it keeps its own name when that is free, else "name (own).litertlm", "name (own 2).litertlm" and so on. Marked
     * "own" with its size. The user's file stays exactly as it is wherever they picked it from.
     */
    static File keepPicked(File tmp, File dir, String name) throws IOException {
        String file = new File(name).getName();
        String base = file.endsWith(EXT) ? file.substring(0, file.length() - EXT.length()) : file;
        for (int i = 0; i < 100; i++) {
            String candidate = i == 0 ? file : base + (i == 1 ? " (own)" : " (own " + i + ")") + EXT;
            if (ModelCatalog.lookup(candidate) != null && !candidate.isEmpty()) continue;
            File dest = new File(dir, candidate);
            try {
                Files.move(tmp.toPath(), dest.toPath());  // no REPLACE_EXISTING: an existing file is never overwritten
            } catch (FileAlreadyExistsException x) {
                continue;
            }
            write(dest, new Record("", dest.length(), dest.lastModified(), OWN, false));
            return dest;
        }
        throw new IOException("Too many model files with this name");
    }
}
