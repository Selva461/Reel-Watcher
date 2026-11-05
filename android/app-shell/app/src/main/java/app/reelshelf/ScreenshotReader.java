package app.reelshelf;

import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Rect;
import android.net.Uri;
import android.os.BatteryManager;
import android.provider.DocumentsContract;
import android.util.Base64;

import com.google.android.gms.tasks.Tasks;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.text.Text;
import com.google.mlkit.vision.text.TextRecognition;
import com.google.mlkit.vision.text.TextRecognizer;
import com.google.mlkit.vision.text.latin.TextRecognizerOptions;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayDeque;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Reads the text in your screenshots on the phone, with Google ML Kit's text recognizer (the model is inside the
 * app: no download, no internet, nothing leaves the phone). Only folders you pick yourself are read (Android's folder
 * picker, so the app never asks for access to all your photos). One picture at a time, only while the app is open.
 */
final class ScreenshotReader {
    private static final String FOLDERS = "shot_folders";
    private static final int MAX_SIDE = 2400;
    private static final int MAX_FILES = 200_000;

    private final Context ctx;
    private final SharedPreferences prefs;
    private TextRecognizer recognizer;
    private volatile boolean stop;

    ScreenshotReader(Context ctx, SharedPreferences prefs) {
        this.ctx = ctx;
        this.prefs = prefs;
    }

    void stop() {
        stop = true;
        synchronized (this) {
            if (recognizer != null) {
                recognizer.close();  // frees the model's memory while the app is away
                recognizer = null;
            }
        }
    }

    void allow() {
        stop = false;
    }

    boolean stopped() {
        return stop;
    }

    // ------------------------------------------------------------------ folders you picked

    JSONArray folders() {
        try {
            return new JSONArray(prefs.getString(FOLDERS, "[]"));
        } catch (JSONException e) {
            return new JSONArray();
        }
    }

    /** Keeps read access to a picked folder (also after a restart) and remembers it. Returns {uri, name}. */
    JSONObject addFolder(Uri tree) throws JSONException {
        ctx.getContentResolver().takePersistableUriPermission(tree, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        JSONArray all = folders();
        String u = tree.toString();
        for (int i = 0; i < all.length(); i++) if (u.equals(all.getJSONObject(i).optString("uri"))) return all.getJSONObject(i);
        JSONObject o = new JSONObject();
        o.put("uri", u);
        o.put("name", niceName(DocumentsContract.getTreeDocumentId(tree)));
        all.put(o);
        prefs.edit().putString(FOLDERS, all.toString()).apply();
        return o;
    }

    void removeFolder(String uri) {
        JSONArray all = folders();
        JSONArray keep = new JSONArray();
        for (int i = 0; i < all.length(); i++) {
            JSONObject o = all.optJSONObject(i);
            if (o == null) continue;
            if (o.optString("uri").equals(uri)) {
                try {
                    ctx.getContentResolver().releasePersistableUriPermission(Uri.parse(uri), Intent.FLAG_GRANT_READ_URI_PERMISSION);
                } catch (Exception ignored) {
                    // already gone
                }
            } else keep.put(o);
        }
        prefs.edit().putString(FOLDERS, keep.toString()).apply();
    }

    /** "primary:DCIM/Screenshots" -> "DCIM/Screenshots" */
    private static String niceName(String docId) {
        if (docId == null) return "";
        int c = docId.indexOf(':');
        return c >= 0 ? docId.substring(c + 1) : docId;
    }

    // ------------------------------------------------------------------ pictures you chose or shared one by one

    /** Pictures you chose in Reel Shelf or shared to it are copied here (the app's own storage, nobody else's). */
    static File inbox(Context c) {
        File d = new File(c.getFilesDir(), "shot-inbox");
        if (!d.isDirectory()) d.mkdirs();
        return d;
    }

    private static final long MAX_PICTURE = 30L * 1024 * 1024;

    /** Copies pictures (from the picker or Share) into the inbox. Returns how many were copied. */
    static int addPictures(Context c, List<Uri> uris) {
        if (uris == null) return 0;
        File dir = inbox(c);
        int n = 0;
        long now = System.currentTimeMillis();
        for (Uri u : uris) {
            if (u == null || n >= 2000) continue;
            String type = c.getContentResolver().getType(u);
            if (type != null && !type.startsWith("image/")) continue;
            String ext = type != null && type.endsWith("png") ? ".png" : type != null && type.endsWith("webp") ? ".webp" : ".jpg";
            File out = new File(dir, "shot_" + now + "_" + n + ext);
            try (InputStream in = c.getContentResolver().openInputStream(u); OutputStream o = new FileOutputStream(out)) {
                if (in == null) continue;
                byte[] buf = new byte[65536];
                long total = 0;
                int r;
                while ((r = in.read(buf)) > 0) {
                    total += r;
                    if (total > MAX_PICTURE) throw new Exception("too big");
                    o.write(buf, 0, r);
                }
                n++;
            } catch (Exception e) {
                out.delete();
            }
        }
        return n;
    }

    private boolean inInbox(String key) {
        try {
            String p = Uri.parse(key).getPath();
            if (p == null) return false;
            File f = new File(p).getCanonicalFile();
            return f.getParentFile() != null && f.getParentFile().equals(inbox(ctx).getCanonicalFile());
        } catch (Exception e) {
            return false;
        }
    }

    /** A picture may be read only when it is inside a folder you picked, or one you chose or shared yourself. */
    boolean allowed(String key) {
        if (key != null && key.startsWith("file://")) return inInbox(key);
        if (key == null || !key.startsWith("content://")) return false;
        JSONArray all = folders();
        for (int i = 0; i < all.length(); i++) {
            String t = all.optJSONObject(i) == null ? "" : all.optJSONObject(i).optString("uri");
            if (!t.isEmpty() && key.startsWith(t + "/document/")) return true;
        }
        return false;
    }

    // ------------------------------------------------------------------ listing

    /** Every picture in the picked folders (and their sub-folders): [{k, n, f, m, s}], newest first is not guaranteed. */
    JSONArray list() throws JSONException {
        JSONArray out = new JSONArray();
        File[] mine = inbox(ctx).listFiles();
        if (mine != null) {
            for (File f : mine) {
                if (!f.isFile()) continue;
                JSONObject o = new JSONObject();
                o.put("k", Uri.fromFile(f).toString());
                o.put("n", f.getName());
                o.put("f", "Chosen pictures");
                o.put("m", f.lastModified());
                o.put("s", f.length());
                out.put(o);
            }
        }
        ContentResolver cr = ctx.getContentResolver();
        JSONArray all = folders();
        for (int i = 0; i < all.length() && !stop; i++) {
            Uri tree = Uri.parse(all.getJSONObject(i).getString("uri"));
            ArrayDeque<String[]> todo = new ArrayDeque<>();  // {documentId, folder path}
            try {
                String root = DocumentsContract.getTreeDocumentId(tree);
                todo.add(new String[]{root, niceName(root)});
            } catch (Exception e) {
                continue;
            }
            int depth = 0;
            while (!todo.isEmpty() && out.length() < MAX_FILES && !stop) {
                String[] d = todo.poll();
                Uri kids = DocumentsContract.buildChildDocumentsUriUsingTree(tree, d[0]);
                try (Cursor c = cr.query(kids, new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                        DocumentsContract.Document.COLUMN_MIME_TYPE, DocumentsContract.Document.COLUMN_LAST_MODIFIED, DocumentsContract.Document.COLUMN_SIZE},
                        null, null, null)) {
                    if (c == null) continue;
                    while (c.moveToNext()) {
                        String id = c.getString(0);
                        String name = c.getString(1);
                        String mime = c.getString(2);
                        if (DocumentsContract.Document.MIME_TYPE_DIR.equals(mime)) {
                            if (depth++ < 400 && name != null && !name.startsWith(".")) todo.add(new String[]{id, d[1] + "/" + name});
                            continue;
                        }
                        if (mime == null || !mime.startsWith("image/") || mime.equals("image/gif")) continue;
                        JSONObject o = new JSONObject();
                        o.put("k", DocumentsContract.buildDocumentUriUsingTree(tree, id).toString());
                        o.put("n", name == null ? "" : name);
                        o.put("f", d[1]);
                        o.put("m", c.isNull(3) ? 0 : c.getLong(3));
                        o.put("s", c.isNull(4) ? 0 : c.getLong(4));
                        out.put(o);
                    }
                } catch (SecurityException e) {
                    // access was taken back in Android's settings: skip this folder
                    break;
                }
            }
        }
        return out;
    }

    // ------------------------------------------------------------------ reading the text

    private synchronized TextRecognizer recognizer() {
        if (recognizer == null) recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS);
        return recognizer;
    }

    private Bitmap decode(Uri uri, int maxSide) throws Exception {
        ContentResolver cr = ctx.getContentResolver();
        BitmapFactory.Options b = new BitmapFactory.Options();
        b.inJustDecodeBounds = true;
        try (InputStream in = cr.openInputStream(uri)) {
            BitmapFactory.decodeStream(in, null, b);
        }
        if (b.outWidth <= 0 || b.outHeight <= 0) throw new Exception("not a picture");
        int sample = 1;
        while (Math.max(b.outWidth, b.outHeight) / (sample * 2) >= maxSide) sample *= 2;
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inSampleSize = sample;
        o.inPreferredConfig = Bitmap.Config.ARGB_8888;
        try (InputStream in = cr.openInputStream(uri)) {
            Bitmap bm = BitmapFactory.decodeStream(in, null, o);
            if (bm == null) throw new Exception("could not open the picture");
            return bm;
        }
    }

    /** The text of one picture: {k, ok, W, H, lines: [{t, x, y, w, h}]} (sizes in the picture's pixels). */
    JSONObject read(String key) throws JSONException {
        JSONObject r = new JSONObject();
        r.put("k", key);
        if (!allowed(key)) {
            r.put("ok", false);
            r.put("error", "not in a picked folder");
            return r;
        }
        Bitmap bm = null;
        try {
            bm = decode(Uri.parse(key), MAX_SIDE);
            Text text = Tasks.await(recognizer().process(InputImage.fromBitmap(bm, 0)), 30, TimeUnit.SECONDS);
            JSONArray lines = new JSONArray();
            for (Text.TextBlock block : text.getTextBlocks()) {
                for (Text.Line line : block.getLines()) {
                    String t = line.getText();
                    if (t == null || t.trim().isEmpty()) continue;
                    JSONObject l = new JSONObject();
                    l.put("t", t);
                    Rect box = line.getBoundingBox();
                    if (box != null) {
                        l.put("x", box.left);
                        l.put("y", box.top);
                        l.put("w", box.width());
                        l.put("h", box.height());
                    }
                    lines.put(l);
                }
            }
            r.put("ok", true);
            r.put("W", bm.getWidth());
            r.put("H", bm.getHeight());
            r.put("lines", lines);
        } catch (Exception e) {
            r.put("ok", false);
            r.put("error", e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage());
        } finally {
            if (bm != null) bm.recycle();
        }
        return r;
    }

    /** The text in a picture given as bytes (a reel's cover picture), lines joined with newlines; "" when none. */
    String readBytes(byte[] data) throws Exception {
        BitmapFactory.Options b = new BitmapFactory.Options();
        b.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(data, 0, data.length, b);
        if (b.outWidth <= 0 || b.outHeight <= 0) throw new Exception("not a picture");
        int sample = 1;
        while (Math.max(b.outWidth, b.outHeight) / (sample * 2) >= MAX_SIDE) sample *= 2;
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inSampleSize = sample;
        o.inPreferredConfig = Bitmap.Config.ARGB_8888;
        Bitmap bm = BitmapFactory.decodeByteArray(data, 0, data.length, o);
        if (bm == null) throw new Exception("could not open the picture");
        try {
            return textOf(bm);
        } finally {
            bm.recycle();
        }
    }

    /** The text in a bitmap (a video frame or a picture), lines joined with newlines; "" when none. */
    String textOf(Bitmap bm) throws Exception {
        Text text = Tasks.await(recognizer().process(InputImage.fromBitmap(bm, 0)), 30, TimeUnit.SECONDS);
        StringBuilder out = new StringBuilder();
        for (Text.TextBlock block : text.getTextBlocks()) {
            for (Text.Line line : block.getLines()) {
                String t = line.getText();
                if (t != null && !t.trim().isEmpty()) out.append(t.trim()).append('\n');
            }
        }
        return out.toString().trim();
    }

    /** A small preview (data: URL), so you can see which screenshot a name came from. */
    String thumb(String key, int side) {
        if (!allowed(key)) return "";
        Bitmap bm = null;
        Bitmap small = null;
        try {
            bm = decode(Uri.parse(key), Math.max(side, 64) * 2);
            float s = Math.min(1f, (float) side / Math.max(bm.getWidth(), bm.getHeight()));
            small = Bitmap.createScaledBitmap(bm, Math.max(1, Math.round(bm.getWidth() * s)), Math.max(1, Math.round(bm.getHeight() * s)), true);
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            small.compress(Bitmap.CompressFormat.JPEG, 70, out);
            return "data:image/jpeg;base64," + Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP);
        } catch (Exception e) {
            return "";
        } finally {
            if (small != null && small != bm) small.recycle();
            if (bm != null) bm.recycle();
        }
    }

    /** {level 0..100, charging} so a long run can pause before the battery runs low. */
    JSONObject battery() throws JSONException {
        Intent b = ctx.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        JSONObject o = new JSONObject();
        int level = b == null ? -1 : b.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
        int scale = b == null ? 100 : b.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
        int plugged = b == null ? 0 : b.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0);
        o.put("level", level < 0 || scale <= 0 ? -1 : Math.round(level * 100f / scale));
        o.put("charging", plugged != 0);
        return o;
    }
}
