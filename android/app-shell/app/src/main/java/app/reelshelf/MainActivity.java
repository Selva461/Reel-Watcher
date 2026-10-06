package app.reelshelf;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
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

    private WebView web;
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

    /** Methods the start page (and the app) can call: window.ReelShelf.* */
    private class Bridge {
        @JavascriptInterface
        public String server() {
            return serverUrl();
        }

        @JavascriptInterface
        public boolean hasTermux() {
            return termuxInstalled();
        }

        @JavascriptInterface
        public void open() {
            runOnUiThread(() -> web.loadUrl(serverUrl()));
        }

        @JavascriptInterface
        public void setServer(String url) {
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
            prefs.edit().putString("url", DEFAULT_URL).apply();
        }

        @JavascriptInterface
        public void copy(String text) {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(ClipData.newPlainText("Reel Shelf", text));
            toast("Copied. Paste it in Termux.");
        }

        @JavascriptInterface
        public void openTermux() {
            Intent i = getPackageManager().getLaunchIntentForPackage(TERMUX);
            if (i != null) startActivity(i);
            else openExternal(Uri.parse("https://f-droid.org/packages/com.termux/"));
        }

        @JavascriptInterface
        public void installTermux() {
            openExternal(Uri.parse("https://f-droid.org/packages/com.termux/"));
        }

        /** Starts `reel-shelf --no-open` in Termux's background (needs allow-external-apps, set by the setup script). */
        @JavascriptInterface
        public String startEngine() {
            if (!termuxInstalled()) return "no-termux";
            if (checkSelfPermission("com.termux.permission.RUN_COMMAND") != PackageManager.PERMISSION_GRANTED) {
                runOnUiThread(() -> requestPermissions(new String[]{"com.termux.permission.RUN_COMMAND"}, PERMISSION_REQUEST));
                return "permission";
            }
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
                return "error: " + e.getMessage();
            }
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        if (requestCode == PERMISSION_REQUEST) {
            boolean ok = results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED;
            toast(ok ? "Allowed. Tap Start again." : "Without this permission, start Reel Shelf from Termux with: reel-shelf");
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_REQUEST && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
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
    }

    @Override
    protected void onPause() {
        web.onPause();
        super.onPause();
    }
}
