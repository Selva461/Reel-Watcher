package app.reelshelf;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * One run of the online check, used by the Process button (app open) and by the optional nightly check.
 * Reads the watchlist from reels.json but never writes it: answers go to verify-results.json, which the page
 * applies (Catalog.verify) the next time it is open. So the page and this job can never overwrite each other.
 * The same title seen in many screenshots is looked up once (a cache in the same file).
 * Pure Java (files and org.json only), tested on a computer.
 */
final class VerifyJob {
    static final String RESULTS = "verify-results.json";
    /** Titles that were not found are tried again after this long (new entries in the databases). */
    static final long RETRY_NOT_FOUND_MS = 30L * 86400_000L;
    static final Object LOCK = new Object();
    private static final AtomicBoolean RUNNING = new AtomicBoolean(false);

    interface Progress {
        void at(int done, int total, String title);
    }

    static boolean running() {
        return RUNNING.get();
    }

    private final File dir;
    private final TitleVerifier verifier;
    private final AtomicBoolean stop;

    VerifyJob(File dir, TitleVerifier verifier, AtomicBoolean stop) {
        this.dir = dir;
        this.verifier = verifier;
        this.stop = stop;
    }

    static JSONObject readJson(File f) {
        try {
            if (f.isFile()) return new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
        } catch (IOException | JSONException ignored) {
            // a broken file is replaced
        }
        return new JSONObject();
    }

    static void writeJson(File f, JSONObject o) throws IOException {
        File tmp = new File(f.getPath() + ".tmp");
        try (OutputStream out = new FileOutputStream(tmp)) {
            out.write(o.toString().getBytes(StandardCharsets.UTF_8));
        }
        if (!tmp.renameTo(f)) throw new IOException("Could not save " + f.getName());
    }

    static String cacheKey(TitleVerifier.Candidate c) {
        return TitleMatch.clean(c.title) + "|" + c.type + "|" + (c.year > 0 ? c.year : "") + "|" + c.lang;
    }

    /** Watchlist entries the check has not answered yet, newest first (the same rule as Catalog.toVerify). */
    static List<TitleVerifier.Candidate> pending(JSONObject db, JSONObject results, long now) {
        List<TitleVerifier.Candidate> out = new ArrayList<>();
        JSONArray media = db.optJSONArray("media");
        if (media == null) return out;
        JSONObject done = results.optJSONObject("results");
        for (int i = 0; i < media.length(); i++) {
            JSONObject m = media.optJSONObject(i);
            if (m == null) continue;
            String v = m.optString("verified", "unverified");
            if (!v.isEmpty() && !v.equals("unverified")) continue;
            long checked = m.optLong("checked_at", 0);
            long updated = m.optLong("updated_at", 0);
            if (checked > 0 && updated <= checked && now - checked < RETRY_NOT_FOUND_MS) continue;  // looked up, nothing found
            if (done != null && done.has(m.optString("id"))) continue;  // answered, waiting for the page to apply it
            out.add(TitleVerifier.Candidate.from(m));
        }
        out.sort((a, b) -> Long.compare(b.updatedAt, a.updatedAt));
        return out;
    }

    /** Results the page has not applied yet, and empties that list (the cache stays). */
    static String take(File dir) {
        if (!RUNNING.compareAndSet(false, true)) return "{}";  // a run is writing; the page takes them when it ends
        try {
            synchronized (LOCK) {
                File f = new File(dir, RESULTS);
                JSONObject all = readJson(f);
                JSONObject r = all.optJSONObject("results");
                if (r == null || r.length() == 0) return "{}";
                all.remove("results");
                try {
                    writeJson(f, all);
                } catch (IOException e) {
                    return "{}";
                }
                return r.toString();
            }
        } finally {
            RUNNING.set(false);
        }
    }

    /** Summary: {checked, verified, review, notFound, left, offline, stopped}. limit 0 = all; budgetMs 0 = no time limit. */
    JSONObject run(int limit, long budgetMs, Progress progress) throws JSONException {
        JSONObject sum = new JSONObject();
        int checked = 0;
        int verified = 0;
        int review = 0;
        int notFound = 0;
        boolean stopped = false;
        boolean offline = false;
        if (!RUNNING.compareAndSet(false, true)) {
            sum.put("busy", true);
            return sum;
        }
        try {
            long t0 = System.currentTimeMillis();
            File f = new File(dir, RESULTS);
            JSONObject db = readJson(new File(dir, "reels.json"));
            JSONObject all;
            synchronized (LOCK) {
                all = readJson(f);
            }
            JSONObject rs = all.optJSONObject("results");
            if (rs == null) all.put("results", rs = new JSONObject());
            JSONObject cache = all.optJSONObject("cache");
            if (cache == null) all.put("cache", cache = new JSONObject());
            List<TitleVerifier.Candidate> todo = pending(db, all, System.currentTimeMillis());
            int total = limit > 0 ? Math.min(limit, todo.size()) : todo.size();
            int offlineInARow = 0;
            int unsaved = 0;
            for (int i = 0; i < total; i++) {
                if (stop.get() || (budgetMs > 0 && System.currentTimeMillis() - t0 > budgetMs)) {
                    stopped = true;
                    break;
                }
                TitleVerifier.Candidate c = todo.get(i);
                if (progress != null) progress.at(i, total, c.title);
                String key = cacheKey(c);
                JSONObject res = null;
                JSONObject hit = cache.optJSONObject(key);
                if (hit != null && !("not_found".equals(hit.optString("verdict"))
                        && System.currentTimeMillis() - hit.optLong("checked_at") > RETRY_NOT_FOUND_MS)) {
                    res = new JSONObject(hit.toString());
                    res.put("id", c.id);
                    res.put("updated_at", c.updatedAt);
                    res.put("cached", true);
                }
                if (res == null) {
                    try {
                        res = verifier.verify(c);
                    } catch (TitleVerifier.Stopped e) {
                        stopped = true;
                        break;
                    } catch (Exception e) {
                        res = null;
                    }
                    if (res != null) {
                        JSONObject keep = new JSONObject(res.toString());
                        keep.remove("id");
                        keep.remove("updated_at");
                        if (!"conflict".equals(keep.optString("verdict"))) keep.remove("choices");
                        cache.put(key, keep);
                    }
                }
                if (res == null) {  // no service answered: probably offline; stop after a few in a row
                    if (++offlineInARow >= 3) {
                        offline = true;
                        break;
                    }
                    continue;
                }
                offlineInARow = 0;
                rs.put(c.id, res);
                checked++;
                String v = res.optString("verdict");
                if (v.equals("verified")) verified++;
                else if (v.equals("conflict")) review++;
                else notFound++;
                if (++unsaved >= 10) {
                    save(f, all);
                    unsaved = 0;
                }
            }
            save(f, all);
            if (progress != null) progress.at(checked, total, "");
            sum.put("checked", checked);
            sum.put("verified", verified);
            sum.put("review", review);
            sum.put("notFound", notFound);
            sum.put("left", Math.max(0, todo.size() - checked));
            sum.put("offline", offline);
            sum.put("stopped", stopped);
            return sum;
        } finally {
            RUNNING.set(false);
        }
    }

    private static void save(File f, JSONObject all) {
        trim(all.optJSONObject("cache"), 5000);
        synchronized (LOCK) {
            try {
                writeJson(f, all);
            } catch (IOException ignored) {
                // the next run looks these titles up again
            }
        }
    }

    /** Keeps the cache file small: drops the oldest answers past n. */
    private static void trim(JSONObject cache, int n) {
        if (cache == null || cache.length() <= n) return;
        List<String> keys = new ArrayList<>();
        for (Iterator<String> it = cache.keys(); it.hasNext(); ) keys.add(it.next());
        keys.sort((a, b) -> Long.compare(cache.optJSONObject(a).optLong("checked_at"), cache.optJSONObject(b).optLong("checked_at")));
        for (int i = 0; i < keys.size() - n; i++) cache.remove(keys.get(i));
    }
}
