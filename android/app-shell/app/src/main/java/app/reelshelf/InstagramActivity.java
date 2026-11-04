package app.reelshelf;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Instagram's own "Download your information" page, opened inside Reel Shelf so the saved-reels export comes straight
 * back into the app. It is a plain web page, like Instagram in a phone browser, so you sign in and tap the buttons
 * yourself: Reel Shelf never types, clicks or scrolls for you (that is what gets accounts flagged), never reads your
 * password or cookies, and gives this page no access to the app. When you tap Download on the finished export, the
 * ZIP is fetched while this screen is open, only the saved-posts files are kept, and the rest is thrown away.
 * Leaving the screen stops the download.
 */
public class InstagramActivity extends Activity {
    static final String START = "https://accountscenter.instagram.com/info_and_permissions/dyi/";
    static final String RESULT_FILE = "ig-saved.json";
    private static final long MAX_ZIP = 4L * 1024 * 1024 * 1024;
    private static final int MAX_ENTRY = 40 * 1024 * 1024;

    private WebView web;
    private TextView bar;
    private volatile Thread download;
    private volatile boolean stop;
    private final Handler ui = new Handler(Looper.getMainLooper());

    /** Pages that may open here: Instagram, Facebook and Meta's sign-in, Accounts Center and export file hosts. */
    static boolean metaHost(String host) {
        if (host == null) return false;
        host = host.toLowerCase(java.util.Locale.ROOT);
        for (String d : new String[]{"instagram.com", "facebook.com", "fbcdn.net", "meta.com", "fb.com", "fbsbx.com"}) {
            if (host.equals(d) || host.endsWith("." + d)) return true;
        }
        return false;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xFF15161A);

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.setPadding(24, 16, 16, 16);
        bar = new TextView(this);
        bar.setTextColor(Color.WHITE);
        bar.setTextSize(13);
        bar.setText("Sign in, then: Some of your information > tick Saved > Download to device > format JSON > Create files. "
                + "Meta emails you when it is ready (minutes to hours). Then open this screen again and tap Download.");
        top.addView(bar, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        Button done = new Button(this);
        done.setText("Back");
        done.setOnClickListener(v -> finish());
        top.addView(done);
        root.addView(top);

        web = new WebView(this);
        root.addView(web, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);  // Instagram's page needs it; no app bridge is added to this WebView
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setSupportMultipleWindows(false);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if ("https".equals(u.getScheme()) && metaHost(u.getHost())) return false;
                try {  // anything else (help pages, other sites) opens outside the app
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (Exception ignored) {
                }
                return true;
            }
        });
        web.setDownloadListener((url, userAgent, disposition, mime, length) -> startDownload(url, userAgent));
        web.loadUrl(START);
    }

    private void say(String text) {
        ui.post(() -> bar.setText(text));
    }

    private void startDownload(String url, String userAgent) {
        Uri u = Uri.parse(url);
        if (!"https".equals(u.getScheme()) || !metaHost(u.getHost())) {
            Toast.makeText(this, "That download is not from Instagram. Save it to the phone and choose it in Add.",
                    Toast.LENGTH_LONG).show();
            return;
        }
        if (download != null) return;
        stop = false;
        String cookies = CookieManager.getInstance().getCookie(url);  // used only for this one request to Meta
        Thread t = new Thread(() -> {
            try {
                String result = fetchSaved(url, userAgent, cookies);
                if (stop) return;
                File out = new File(getFilesDir(), RESULT_FILE);
                File tmp = new File(getFilesDir(), RESULT_FILE + ".tmp");
                try (OutputStream o = new FileOutputStream(tmp)) {
                    o.write(result.getBytes(StandardCharsets.UTF_8));
                }
                if (!tmp.renameTo(out)) throw new Exception("could not save");
                ui.post(() -> {
                    Toast.makeText(this, "Saved reels received. Back in Reel Shelf they are added to your shelf.",
                            Toast.LENGTH_LONG).show();
                    finish();
                });
            } catch (Exception e) {
                if (!stop) say("The download did not finish (" + e.getMessage() + "). Tap Download again.");
            } finally {
                download = null;
            }
        }, "ig-export");
        download = t;
        say("Downloading your export. Keep this screen open...");
        t.start();
    }

    /** Streams the export ZIP and keeps only the saved-posts files. Returns [{name, text}] as JSON. */
    private String fetchSaved(String url, String userAgent, String cookies) throws Exception {
        HttpURLConnection c = null;
        for (int hop = 0; hop < 6; hop++) {
            URL target = new URL(url);
            if (!"https".equals(target.getProtocol()) || !metaHost(target.getHost())) throw new Exception("left Instagram");
            c = (HttpURLConnection) target.openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(20000);
            c.setReadTimeout(60000);
            if (userAgent != null) c.setRequestProperty("User-Agent", userAgent);
            String ck = CookieManager.getInstance().getCookie(url);
            if (ck == null) ck = cookies;
            if (ck != null) c.setRequestProperty("Cookie", ck);
            int code = c.getResponseCode();
            if (code >= 300 && code < 400) {
                String next = c.getHeaderField("Location");
                c.disconnect();
                if (next == null) throw new Exception("bad redirect");
                url = new URL(target, next).toString();
                continue;
            }
            if (code != 200) throw new Exception("HTTP " + code);
            break;
        }
        if (c == null) throw new Exception("too many redirects");
        long len = c.getContentLengthLong();
        if (len > MAX_ZIP) throw new Exception("export too big; pick only Saved");
        JSONArray parts = new JSONArray();
        long seen = 0;
        try (InputStream in = c.getInputStream(); ZipInputStream zip = new ZipInputStream(in)) {
            ZipEntry e;
            byte[] buf = new byte[65536];
            while ((e = zip.getNextEntry()) != null) {
                if (stop) throw new Exception("stopped");
                String name = e.getName();
                String base = name.substring(name.lastIndexOf('/') + 1).toLowerCase(java.util.Locale.ROOT);
                boolean keep = !e.isDirectory() && base.startsWith("saved") && (base.endsWith(".json") || base.endsWith(".html"));
                ByteArrayOutputStream text = keep ? new ByteArrayOutputStream() : null;
                int n;
                while ((n = zip.read(buf)) > 0) {
                    if (stop) throw new Exception("stopped");
                    seen += n;
                    if (seen > MAX_ZIP) throw new Exception("export too big; pick only Saved");
                    if (text != null) {
                        if (text.size() + n > MAX_ENTRY) throw new Exception(base + " is too big");
                        text.write(buf, 0, n);
                    }
                }
                if (text != null) parts.put(new JSONObject().put("name", base).put("text", text.toString("UTF-8")));
                if (len > 0) say("Downloading your export... " + Math.min(100, seen * 100 / Math.max(1, len)) + "%");
            }
        } finally {
            c.disconnect();
        }
        if (parts.length() == 0) throw new Exception("no saved posts in this file; tick Saved when you request it");
        return parts.toString();
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    /** Leaving this screen stops the download: nothing runs in the background. */
    @Override
    protected void onStop() {
        stop = true;
        Thread t = download;
        if (t != null) t.interrupt();
        CookieManager.getInstance().flush();
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }

    /** Takes the saved-reels files the last export brought in (once), or null. */
    static String takeResult(Activity a) {
        File f = new File(a.getFilesDir(), RESULT_FILE);
        if (!f.exists()) return null;
        try (InputStream in = new java.io.FileInputStream(f)) {
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
            return b.toString("UTF-8");
        } catch (Exception e) {
            return null;
        } finally {
            //noinspection ResultOfMethodCallIgnored
            f.delete();
        }
    }

    /** Signs Reel Shelf out of Instagram by clearing its own web cookies (Instagram's app is not touched). */
    static void signOut() {
        CookieManager.getInstance().removeAllCookies(null);
        CookieManager.getInstance().flush();
    }
}
