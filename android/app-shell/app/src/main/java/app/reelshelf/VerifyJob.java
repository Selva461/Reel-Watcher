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
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

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
    /** Titles checked at the same time (Avles: about 10; data use does not matter). */
    static final int WORKERS = 10;
    /** No service answered for this many titles in a row: offline, stop. */
    static final int OFFLINE_AFTER = 10;

    interface Progress {
        void at(int done, int total, String title);
    }

    static boolean running() {
        return RUNNING.get();
    }

    private final File dir;
    private final TitleVerifier verifier;
    private final AtomicBoolean stop;
    int workers = WORKERS;

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

    /** Answers from before 1.3.5 (one source was enough) are asked again, not reused. */
    static final int CACHE_VERSION = 4;

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
        if (!RUNNING.compareAndSet(false, true)) {
            sum.put("busy", true);
            return sum;
        }
        try {
            long t0 = System.currentTimeMillis();
            File f = new File(dir, RESULTS);
            JSONObject db;
            synchronized (LibraryFile.reels(dir)) {  // not while a save is swapping the file
                db = readJson(new File(dir, "reels.json"));
            }
            JSONObject all;
            synchronized (LOCK) {
                all = readJson(f);
            }
            JSONObject rs0 = all.optJSONObject("results");
            if (rs0 == null) all.put("results", rs0 = new JSONObject());
            JSONObject cache0 = all.optJSONObject("cache");
            if (cache0 == null) all.put("cache", cache0 = new JSONObject());
            final JSONObject rs = rs0;
            final JSONObject cache = cache0;
            List<TitleVerifier.Candidate> todo = pending(db, all, System.currentTimeMillis());
            int total = limit > 0 ? Math.min(limit, todo.size()) : todo.size();
            // the same title seen in several screenshots is looked up once, by one worker, and shared with the rest
            Map<String, List<TitleVerifier.Candidate>> byKey = new java.util.LinkedHashMap<>();
            for (TitleVerifier.Candidate c : todo.subList(0, total)) {
                List<TitleVerifier.Candidate> l = byKey.get(cacheKey(c));
                if (l == null) byKey.put(cacheKey(c), l = new ArrayList<>());
                l.add(c);
            }
            List<List<TitleVerifier.Candidate>> groups = new ArrayList<>(byKey.values());
            int offlineAfter = Math.max(1, Math.min(OFFLINE_AFTER, groups.size()));
            AtomicInteger checked = new AtomicInteger();
            AtomicInteger verified = new AtomicInteger();
            AtomicInteger review = new AtomicInteger();
            AtomicInteger notFound = new AtomicInteger();
            AtomicInteger offlineInARow = new AtomicInteger();
            AtomicInteger unsaved = new AtomicInteger();
            AtomicBoolean stopped = new AtomicBoolean();
            AtomicBoolean offline = new AtomicBoolean();
            AtomicInteger done = new AtomicInteger();
            parallel(groups.size(), () -> stopped.get() || offline.get() || timeUp(t0, budgetMs, stopped), i -> {
                List<TitleVerifier.Candidate> group = groups.get(i);
                TitleVerifier.Candidate c = group.get(0);
                String key = cacheKey(c);
                JSONObject res = null;
                JSONObject hit;
                synchronized (all) {
                    hit = cache.optJSONObject(key);
                    if (hit != null) hit = new JSONObject(hit.toString());
                }
                if (hit != null && hit.optInt("v") == CACHE_VERSION && !("not_found".equals(hit.optString("verdict"))
                        && System.currentTimeMillis() - hit.optLong("checked_at") > RETRY_NOT_FOUND_MS)) {
                    res = hit;
                    res.put("id", c.id);
                    res.put("updated_at", c.updatedAt);
                    res.put("cached", true);
                }
                if (res == null) {
                    try {
                        res = verifier.verify(c);
                    } catch (TitleVerifier.Stopped e) {
                        stopped.set(true);
                        return;
                    } catch (Exception e) {
                        res = null;
                    }
                    if (res != null) {
                        JSONObject keep = new JSONObject(res.toString());
                        keep.remove("id");
                        keep.remove("updated_at");
                        if (!"not_found".equals(keep.optString("verdict"))) keep.remove("choices");  // the close ones: for the phone AI
                        keep.put("v", CACHE_VERSION);
                        synchronized (all) {
                            cache.put(key, keep);
                        }
                    }
                }
                if (res == null) {  // no service answered: probably offline; stop after a run of them
                    if (offlineInARow.incrementAndGet() >= offlineAfter) offline.set(true);
                    return;
                }
                offlineInARow.set(0);
                for (int g = 0; g < group.size(); g++) {
                    TitleVerifier.Candidate one = group.get(g);
                    JSONObject mine = res;
                    if (g > 0) {  // a twin: the same answer, marked as coming from the cache
                        mine = new JSONObject(res.toString());
                        mine.put("id", one.id);
                        mine.put("updated_at", one.updatedAt);
                        mine.put("cached", true);
                    }
                    synchronized (all) {
                        rs.put(one.id, mine);
                    }
                    checked.incrementAndGet();
                    String v = mine.optString("verdict");
                    if (v.equals("verified")) verified.incrementAndGet();
                    else if (v.equals("conflict")) review.incrementAndGet();
                    else notFound.incrementAndGet();
                }
                if (progress != null) progress.at(done.addAndGet(group.size()), total, c.title);
                if (unsaved.incrementAndGet() % 10 == 0) save(f, all);
            });
            if (stop.get()) stopped.set(true);
            // titles checked before 1.3.4 have no seasons or rating yet (some no length): looked up once
            AtomicInteger lengths = new AtomicInteger();
            if (!stopped.get() && !offline.get()) {
                List<String[]> need = needDetails(db, rs);
                int room = limit > 0 ? Math.max(0, limit - checked.get()) : need.size();
                AtomicInteger failedInARow = new AtomicInteger();
                AtomicBoolean gaveUp = new AtomicBoolean();
                parallel(Math.min(room, need.size()), () -> stopped.get() || gaveUp.get() || timeUp(t0, budgetMs, stopped), i -> {
                    String id = need.get(i)[0];
                    JSONObject m = media(db, id);
                    if (m == null) return;
                    Map<String, String> ext = new HashMap<>();
                    JSONObject e = m.optJSONObject("ext");
                    if (e != null) for (Iterator<String> it = e.keys(); it.hasNext(); ) {
                        String k = it.next();
                        ext.put(k, e.optString(k));
                    }
                    TitleVerifier.Details d;
                    try {
                        d = verifier.details(ext, m.optString("type"));
                        failedInARow.set(0);
                    } catch (TitleVerifier.Stopped x) {
                        stopped.set(true);
                        return;
                    } catch (Exception x) {
                        if (failedInARow.incrementAndGet() >= OFFLINE_AFTER) gaveUp.set(true);
                        return;
                    }
                    JSONObject r = new JSONObject();
                    r.put("verdict", "details");
                    r.put("runtime", d.runtime);
                    r.put("episodes", d.episodes);
                    if (d.rating > 0) r.put("rating", new JSONObject().put("score", d.rating).put("by", d.ratingBy).put("votes", d.votes));
                    if (d.seasons.length() > 0) r.put("seasons", d.seasons);
                    if (d.seasons.length() > 0 && !d.seasonsBy.isEmpty()) r.put("seasons_by", d.seasonsBy);
                    if (!d.imdb.isEmpty()) r.put("imdb", d.imdb);
                    r.put("checked_at", System.currentTimeMillis());
                    synchronized (all) {
                        rs.put(id, r);
                    }
                    lengths.incrementAndGet();
                    if (unsaved.incrementAndGet() % 10 == 0) save(f, all);
                });
            }
            if (stop.get()) stopped.set(true);
            sum.put("lengths", lengths.get());
            save(f, all);
            if (progress != null) progress.at(checked.get(), total, "");
            sum.put("checked", checked.get());
            sum.put("verified", verified.get());
            sum.put("review", review.get());
            sum.put("notFound", notFound.get());
            sum.put("left", Math.max(0, todo.size() - checked.get()));
            sum.put("offline", offline.get());
            sum.put("stopped", stopped.get());
            return sum;
        } finally {
            RUNNING.set(false);
        }
    }

    interface Task {
        void run(int i) throws JSONException;
    }

    interface Halt {
        boolean now();
    }

    /** Runs task(0..n-1) on {@link #workers} threads at once (each service keeps its own speed limit in TitleVerifier). */
    private void parallel(int n, Halt halt, Task task) {
        AtomicInteger next = new AtomicInteger();
        Runnable worker = () -> {
            for (int i; !stop.get() && !halt.now() && (i = next.getAndIncrement()) < n; ) {
                try {
                    task.run(i);
                } catch (Exception ignored) {
                    // one title's broken answer does not stop the others
                }
            }
        };
        int k = Math.max(1, Math.min(workers, n));
        List<Thread> threads = new ArrayList<>();
        for (int t = 0; t < k; t++) {
            Thread th = new Thread(worker, "title-check-" + t);
            threads.add(th);
            th.start();
        }
        for (Thread th : threads) {
            try {
                th.join();
            } catch (InterruptedException e) {
                stop.set(true);
                Thread.currentThread().interrupt();
            }
        }
    }

    private boolean timeUp(long t0, long budgetMs, AtomicBoolean stopped) {
        if (stop.get() || (budgetMs > 0 && System.currentTimeMillis() - t0 > budgetMs)) {
            stopped.set(true);
            return true;
        }
        return false;
    }

    /** Checked titles to watch that have an id but were never given seasons and a rating (details_at): [[id]]. */
    static List<String[]> needDetails(JSONObject db, JSONObject results) {
        List<String[]> out = new ArrayList<>();
        JSONArray media = db.optJSONArray("media");
        if (media == null) return out;
        for (int i = 0; i < media.length(); i++) {
            JSONObject m = media.optJSONObject(i);
            if (m == null || !"verified".equals(m.optString("verified"))) continue;
            if (m.has("details_at")) continue;
            if (!TitleVerifier.groupOf(m.optString("type")).equals("watch")) continue;
            JSONObject e = m.optJSONObject("ext");
            if (e == null || !(e.has("tmdb") || e.has("anilist") || e.has("mal"))) continue;
            if (results != null && results.has(m.optString("id"))) continue;
            out.add(new String[]{m.optString("id")});
        }
        return out;
    }

    private static JSONObject media(JSONObject db, String id) {
        JSONArray media = db.optJSONArray("media");
        if (media == null) return null;
        for (int i = 0; i < media.length(); i++) {
            JSONObject m = media.optJSONObject(i);
            if (m != null && id.equals(m.optString("id"))) return m;
        }
        return null;
    }

    private static void save(File f, JSONObject all) {
        synchronized (all) {  // the titles being checked add to it meanwhile
            trim(all.optJSONObject("cache"), 5000);
            synchronized (LOCK) {
                try {
                    writeJson(f, all);
                } catch (IOException ignored) {
                    // the next run looks these titles up again
                }
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
