package app.reelshelf;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.provider.Settings;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Reel Shelf for Android: a full-screen window onto the Reel Shelf app.
 * The engine runs on this phone inside Termux (http://localhost:8765) or on your PC (its address with the access code).
 * When it is not reachable, a start page offers to start it in Termux, connect to a PC, or set it up.
 */
public class MainActivity extends Activity {
    private static final String DEFAULT_URL = "http://localhost:8765/";
    private static final String START_PAGE = "file:///android_asset/start.html";
    private static final int FILE_REQUEST = 1;
    private static final int PERMISSION_REQUEST = 2;
    private static final String TERMUX = "com.termux";
    private static final String RUN_COMMAND = "com.termux.permission.RUN_COMMAND";

    private WebView web;
    private volatile String currentUrl = "";
    private ValueCallback<Uri[]> fileCallback;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("reelshelf", MODE_PRIVATE);
        web = new WebView(this);
        web.setBackgroundColor(0xFF15161A);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        CookieManager.getInstance().setAcceptCookie(true);

        web.addJavascriptInterface(new Bridge(), "ReelShelf");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                currentUrl = url == null ? "" : url;
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                String scheme = u.getScheme() == null ? "" : u.getScheme();
                if (scheme.equals("file")) return false;
                Uri server = Uri.parse(serverUrl());
                boolean sameServer = scheme.startsWith("http") && u.getHost() != null && u.getHost().equals(server.getHost())
                        && u.getPort() == server.getPort();
                if (sameServer) return false;
                openExternal(u);  // Instagram links, help pages: open in their own app or the browser
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && !START_PAGE.equals(request.getUrl().toString())) {
                    view.loadUrl(START_PAGE);
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), FILE_REQUEST);
                } catch (Exception e) {
                    fileCallback = null;
                    toast("No file picker available");
                    return false;
                }
                return true;
            }
        });
        web.setDownloadListener((url, userAgent, contentDisposition, mimeType, length) -> {
            try {
                String name = URLUtil.guessFileName(url, contentDisposition, mimeType);
                DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
                r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "ReelShelf/" + name);
                String cookie = CookieManager.getInstance().getCookie(url);
                if (cookie != null) r.addRequestHeader("Cookie", cookie);
                ((DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE)).enqueue(r);
                toast("Saving " + name + " to Downloads/ReelShelf");
            } catch (Exception e) {
                toast("Could not save: " + e.getMessage());
            }
        });
        web.loadUrl(serverUrl());
    }

    private String serverUrl() {
        return prefs.getString("url", DEFAULT_URL);
    }

    private void toast(String msg) {
        runOnUiThread(() -> Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
    }

    private void openExternal(Uri u) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, u));
        } catch (Exception e) {
            toast("No app can open this link");
        }
    }

    private boolean termuxInstalled() {
        try {
            getPackageManager().getPackageInfo(TERMUX, 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    /** Only the built-in start page and the Reel Shelf server may use the bridge, never another site shown in the app. */
    private boolean trustedPage() {
        String u = currentUrl;
        if (u.startsWith(START_PAGE)) return true;
        Uri page = Uri.parse(u);
        Uri server = Uri.parse(serverUrl());
        return page.getScheme() != null && page.getScheme().startsWith("http") && page.getHost() != null
                && page.getHost().equals(server.getHost()) && page.getPort() == server.getPort();
    }

    /** Methods the start page (and the app) can call: window.ReelShelf.* */
    private class Bridge {
        @JavascriptInterface
        public String server() {
            if (!trustedPage()) return "untrusted";
            return serverUrl();
        }

        @JavascriptInterface
        public boolean hasTermux() {
            if (!trustedPage()) return false;
            return termuxInstalled();
        }

        @JavascriptInterface
        public void open() {
            if (!trustedPage()) return;
            runOnUiThread(() -> web.loadUrl(serverUrl()));
        }

        @JavascriptInterface
        public void setServer(String url) {
            if (!trustedPage()) return;
            String u = url == null ? "" : url.trim();
            if (u.isEmpty()) u = DEFAULT_URL;
            if (!u.startsWith("http://") && !u.startsWith("https://")) u = "http://" + u;
            prefs.edit().putString("url", u).apply();
            final String target = u;
            runOnUiThread(() -> web.loadUrl(target));
        }

        /** Remember "this phone" as the server without reloading the page (the start page keeps polling). */
        @JavascriptInterface
        public void rememberPhone() {
            if (!trustedPage()) return;
            prefs.edit().putString("url", DEFAULT_URL).apply();
        }

        @JavascriptInterface
        public void copy(String text) {
            if (!trustedPage()) return;
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("Reel Shelf", text));
            toast("Copied. Paste it in Termux.");
        }

        @JavascriptInterface
        public void openTermux() {
            if (!trustedPage()) return;
            Intent i = getPackageManager().getLaunchIntentForPackage(TERMUX);
            if (i != null) startActivity(i);
            else openExternal(Uri.parse("https://f-droid.org/packages/com.termux/"));
        }

        @JavascriptInterface
        public void installTermux() {
            if (!trustedPage()) return;
            openExternal(Uri.parse("https://f-droid.org/packages/com.termux/"));
        }

        /**
         * Hands a screenshot to Google Lens (inside the Google app), or to the share menu when that app is missing.
         * The picture is saved to Pictures/ReelShelf first, because other apps can only open shared storage.
         */
        @JavascriptInterface
        public String shareImage(String path) {
            if (!trustedPage()) return "untrusted";
            if (path == null || !path.matches("/api/items/\\d+/image")) return "Could not open Google Lens";
            if (Build.VERSION.SDK_INT < 29) return "Needs Android 10 or newer: save the picture and open it in Google Lens";
            Uri server = Uri.parse(serverUrl());
            final String base = server.getScheme() + "://" + server.getEncodedAuthority();
            new Thread(() -> {
                try {
                    HttpURLConnection c = (HttpURLConnection) new URL(base + path).openConnection();
                    String cookie = CookieManager.getInstance().getCookie(base);
                    if (cookie != null) c.setRequestProperty("Cookie", cookie);
                    c.setConnectTimeout(10000);
                    c.setReadTimeout(30000);
                    if (c.getResponseCode() != 200) {
                        toast("Could not load the picture (" + c.getResponseCode() + ")");
                        return;
                    }
                    String mime = c.getContentType() == null ? "image/jpeg" : c.getContentType();
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.Images.Media.DISPLAY_NAME, "reelshelf_lens_" + System.currentTimeMillis());
                    v.put(MediaStore.Images.Media.MIME_TYPE, mime);
                    v.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/ReelShelf");
                    Uri uri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
                    if (uri == null) {
                        toast("Could not save the picture for Google Lens");
                        return;
                    }
                    try (InputStream in = c.getInputStream(); OutputStream out = getContentResolver().openOutputStream(uri)) {
                        byte[] buf = new byte[65536];
                        int n;
                        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                    }
                    Intent send = new Intent(Intent.ACTION_SEND);
                    send.setType(mime);
                    send.putExtra(Intent.EXTRA_STREAM, uri);
                    send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    Intent lens = new Intent(send).setPackage("com.google.android.googlequicksearchbox");
                    runOnUiThread(() -> {
                        try {
                            startActivity(lens);
                        } catch (Exception e) {
                            startActivity(Intent.createChooser(send, "Search with Google Lens"));
                        }
                    });
                } catch (Exception e) {
                    toast("Could not open Google Lens: " + e.getMessage());
                }
            }).start();
            return "ok";
        }

        /** "play" when Termux came from the Play Store (a different build that cannot be started by other apps), else "ok" or "none". */
        @JavascriptInterface
        public String termuxSource() {
            if (!trustedPage()) return "untrusted";
            if (!termuxInstalled()) return "none";
            try {
                String installer = Build.VERSION.SDK_INT >= 30
                        ? getPackageManager().getInstallSourceInfo(TERMUX).getInstallingPackageName()
                        : getPackageManager().getInstallerPackageName(TERMUX);
                return "com.android.vending".equals(installer) ? "play" : "ok";
            } catch (Exception e) {
                return "ok";
            }
        }

        @JavascriptInterface
        public boolean getFlag(String name) {
            if (!trustedPage()) return false;
            return prefs.getBoolean("flag_" + name, false);
        }

        @JavascriptInterface
        public void setFlag(String name, boolean value) {
            if (!trustedPage()) return;
            prefs.edit().putBoolean("flag_" + name, value).apply();
        }

        /** Copies the setup command and opens Termux, so the user only has to paste. */
        @JavascriptInterface
        public void copyAndOpenTermux(String text) {
            if (!trustedPage()) return;
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("Reel Shelf", text));
            runOnUiThread(this::openTermux);
        }

        @JavascriptInterface
        public void openAppSettings() {
            if (!trustedPage()) return;
            Intent i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName()));
            runOnUiThread(() -> startActivity(i));
        }

        /**
         * Starts `reel-shelf --no-open` in Termux's background (needs allow-external-apps, set by the setup script).
         * Returns started, permission (Android is asking), denied (Android refused), or no-termux.
         * When it is not "started", the start page opens Termux instead, which starts Reel Shelf by itself.
         */
        @JavascriptInterface
        public String startEngine() {
            if (!trustedPage()) return "untrusted";
            if (!termuxInstalled()) return "no-termux";
            if (checkSelfPermission(RUN_COMMAND) != PackageManager.PERMISSION_GRANTED) {
                if (prefs.getBoolean("asked", false) && !shouldShowRequestPermissionRationale(RUN_COMMAND)) return "denied";
                prefs.edit().putBoolean("asked", true).apply();
                runOnUiThread(() -> requestPermissions(new String[]{RUN_COMMAND}, PERMISSION_REQUEST));
                return "permission";
            }
            return runInTermux();
        }
    }

    private String runInTermux() {
        try {
            Intent intent = new Intent();
            intent.setClassName(TERMUX, "com.termux.app.RunCommandService");
            intent.setAction("com.termux.RUN_COMMAND");
            intent.putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/reel-shelf");
            intent.putExtra("com.termux.RUN_COMMAND_ARGUMENTS", new String[]{"--no-open"});
            intent.putExtra("com.termux.RUN_COMMAND_BACKGROUND", true);
            startService(intent);
            return "started";
        } catch (Exception e) {
            return "denied";
        }
    }

    private void callPage(String js) {
        runOnUiThread(() -> web.evaluateJavascript(js, null));
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        if (requestCode == PERMISSION_REQUEST) {
            boolean ok = results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED;
            String r = ok ? runInTermux() : "denied";
            callPage("window.onEngineStart && onEngineStart('" + r + "')");
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_REQUEST && fileCallback != null) {
            Uri[] picked = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
            ClipData clip = data == null ? null : data.getClipData();
            if (resultCode == RESULT_OK && clip != null && clip.getItemCount() > 0) {  // several files chosen at once
                picked = new Uri[clip.getItemCount()];
                for (int i = 0; i < clip.getItemCount(); i++) picked[i] = clip.getItemAt(i).getUri();
            }
            fileCallback.onReceiveValue(picked);
            fileCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
        callPage("window.onAppResume && onAppResume()");
    }

    @Override
    protected void onPause() {
        web.onPause();
        super.onPause();
    }
}
