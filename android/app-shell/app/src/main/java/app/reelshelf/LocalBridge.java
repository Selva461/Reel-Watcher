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

    private final MainActivity act;
    private final SharedPreferences prefs;
    private final LocalModel model;
    private final ScreenshotReader shots;
    private final ExecutorService ocr = Executors.newSingleThreadExecutor();
    private final ExecutorService work = Executors.newSingleThreadExecutor();
    private final ExecutorService net = Executors.newSingleThreadExecutor();
    private volatile boolean downloading;

    LocalBridge(MainActivity act, SharedPreferences prefs) {
        this.act = act;
        this.prefs = prefs;
        this.model = new LocalModel(act);
        this.shots = new ScreenshotReader(act, prefs);
    }

    /** Called when the app leaves the screen: stop downloads and answers, free the model's memory. */
    void pause() {
        model.stopAll();
        shots.stop();
        act.keepScreenOn(false);
    }

    /** Adds shared text to the queue the page reads when it opens (used by ShareActivity, which has no page). */
    static void queueShared(Context ctx, String text) {
        if (text == null || text.trim().isEmpty()) return;
        synchronized (SHARED_LOCK) {
            SharedPreferences p = ctx.getSharedPreferences("reelshelf", Context.MODE_PRIVATE);
            JSONArray a;
            try {
                a = new JSONArray(p.getString(SHARED_KEY, "[]"));
            } catch (JSONException e) {
                a = new JSONArray();
            }
            JSONObject o = new JSONObject();
            try {
                o.put("text", text.length() > 20000 ? text.substring(0, 20000) : text);
                o.put("at", System.currentTimeMillis());
            } catch (JSONException ignored) {
                return;
            }
            a.put(o);
            p.edit().putString(SHARED_KEY, a.toString()).commit();
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

    private File dbFile() {
        return new File(act.getFilesDir(), "reels.json");
    }

    @JavascriptInterface
    public String load() {
        if (!ok()) return "";
        try {
            File f = dbFile();
            return f.isFile() ? new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8) : "";
        } catch (IOException e) {
            return "";
        }
    }

    @JavascriptInterface
    public boolean store(String json) {
        if (!ok() || json == null) return false;
        synchronized (this) {
            File tmp = new File(act.getFilesDir(), "reels.json.tmp");
            try (OutputStream out = new FileOutputStream(tmp)) {
                out.write(json.getBytes(StandardCharsets.UTF_8));
                out.flush();
            } catch (IOException e) {
                return false;
            }
            return tmp.renameTo(dbFile());
        }
    }

    @JavascriptInterface
    public String takeShared() {
        if (!ok()) return "[]";
        synchronized (SHARED_LOCK) {
            String s = prefs.getString(SHARED_KEY, "[]");
            prefs.edit().remove(SHARED_KEY).commit();
            return s;
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
        prefs.edit().putString("local_settings", json).apply();
    }

    // ------------------------------------------------------------------ talking to other apps

    @JavascriptInterface
    public void copy(String text) {
        if (!ok()) return;
        act.runOnUiThread(() -> {
            ClipboardManager cm = (ClipboardManager) act.getSystemService(Context.CLIPBOARD_SERVICE);
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

    @JavascriptInterface
    public void openServerMode() {
        if (!ok()) return;
        act.runOnUiThread(act::openServerMode);
    }

    /** Saves a text file to Downloads/ReelShelf. Calls back with the place it was saved. */
    @JavascriptInterface
    public void saveFile(int id, String name, String mime, String text) {
        if (!ok()) return;
        String safe = new File(name == null || name.isEmpty() ? "reel-shelf.txt" : name).getName().replaceAll("[^A-Za-z0-9._-]", "_");
        byte[] data = (text == null ? "" : text).getBytes(StandardCharsets.UTF_8);
        work.execute(() -> {
            try {
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.Downloads.DISPLAY_NAME, safe);
                    v.put(MediaStore.Downloads.MIME_TYPE, mime == null || mime.isEmpty() ? "text/plain" : mime);
                    v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/ReelShelf");
                    Uri uri = act.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                    if (uri == null) throw new IOException("Android did not give a place to save");
                    try (OutputStream out = act.getContentResolver().openOutputStream(uri)) {
                        if (out == null) throw new IOException("Could not write the file");
                        out.write(data);
                    }
                    done(id, true, "Downloads/ReelShelf/" + safe);
                } else {
                    File d = new File(act.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "ReelShelf");
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

    /** {"file", "ready", "bytes", "partial", "downloading", "backend", "free"} */
    @JavascriptInterface
    public String modelInfo(String name) {
        if (!ok()) return "{}";
        File f = model.file(name);
        File part = new File(f.getPath() + ".part");
        JSONObject o = new JSONObject();
        try {
            o.put("file", f.getName());
            o.put("ready", f.isFile());
            o.put("bytes", f.isFile() ? f.length() : 0);
            o.put("partial", part.isFile() ? part.length() : 0);
            o.put("downloading", downloading);
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

    @JavascriptInterface
    public void downloadModel(int id, String url, String name) {
        if (!ok()) return;
        String u = url == null || url.isEmpty() ? LocalModel.DEFAULT_URL : url;
        if (!u.startsWith("https://huggingface.co/")) {
            done(id, false, "Models can only be downloaded from huggingface.co");
            return;
        }
        if (downloading) {
            done(id, false, "Already downloading");
            return;
        }
        downloading = true;
        net.execute(() -> {
            try {
                model.download(u, model.file(name), (d, t) -> progress("download", d, t));
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

    @JavascriptInterface
    public boolean deleteModel(String name) {
        if (!ok()) return false;
        model.stopAll();
        File f = model.file(name);
        File part = new File(f.getPath() + ".part");
        boolean a = !f.exists() || f.delete();
        boolean b = !part.exists() || part.delete();
        return a && b;
    }

    /** Lets you pick your own .litertlm model file; it is copied into the app (progress as "import"). */
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
            File dest = model.file(name);
            File part = new File(dest.getPath() + ".part");
            try (InputStream in = act.getContentResolver().openInputStream(uri); OutputStream out = new FileOutputStream(part)) {
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
            if (dest.exists()) //noinspection ResultOfMethodCallIgnored
                dest.delete();
            if (!part.renameTo(dest)) {
                done(id, false, "Could not save the model file");
                return;
            }
            done(id, true, dest.getName());
        })));
    }

    /** Runs the model once. opts: {"file", "gpu", "system", "maxTokens", "temperature"}. */
    @JavascriptInterface
    public void generate(int id, String prompt, String opts) {
        if (!ok()) return;
        work.execute(() -> {
            try {
                JSONObject o = new JSONObject(opts == null || opts.isEmpty() ? "{}" : opts);
                long t0 = System.currentTimeMillis();
                String out = model.generate(model.file(o.optString("file", "")), o.optBoolean("gpu", true), o.optString("system", ""),
                        prompt == null ? "" : prompt, o.optInt("maxTokens", 800), o.optDouble("temperature", 0.3));
                JSONObject r = new JSONObject();
                r.put("text", out);
                r.put("backend", model.backendInUse());
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

    /** Opens Instagram's own "Download your information" page inside Reel Shelf (you sign in and tap yourself). */
    @JavascriptInterface
    public void openInstagram() {
        if (!ok()) return;
        act.runOnUiThread(() -> act.startActivity(new android.content.Intent(act, InstagramActivity.class)));
    }

    /** The saved-posts files brought back by the last in-app export download, as [{name, text}] JSON, or "". */
    @JavascriptInterface
    public String takeInstagramExport() {
        if (!ok()) return "";
        String r = InstagramActivity.takeResult(act);
        return r == null ? "" : r;
    }

    /** Signs Reel Shelf's own web pages out of Instagram (clears the app's web cookies). */
    @JavascriptInterface
    public void signOutInstagram() {
        if (!ok()) return;
        act.runOnUiThread(InstagramActivity::signOut);
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

    /** What has been read from screenshots so far (its own file, so the library file stays small). */
    @JavascriptInterface
    public String loadShots() {
        if (!ok()) return "";
        try {
            File f = new File(act.getFilesDir(), "shots.json");
            return f.isFile() ? new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8) : "";
        } catch (IOException e) {
            return "";
        }
    }

    @JavascriptInterface
    public boolean storeShots(String json) {
        if (!ok() || json == null) return false;
        synchronized (this) {
            File tmp = new File(act.getFilesDir(), "shots.json.tmp");
            try (OutputStream out = new FileOutputStream(tmp)) {
                out.write(json.getBytes(StandardCharsets.UTF_8));
                out.flush();
            } catch (IOException e) {
                return false;
            }
            return tmp.renameTo(new File(act.getFilesDir(), "shots.json"));
        }
    }
}
