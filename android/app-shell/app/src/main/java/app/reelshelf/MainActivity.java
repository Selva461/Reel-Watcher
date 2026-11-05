package app.reelshelf;

import android.app.Activity;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Build;
import android.provider.OpenableColumns;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;


/**
 * Reel Shelf for Android. By default everything runs inside this app (assets/local): shared reels are saved on the
 * phone, and only when you open the app and tap Start are they read and written up by the AI model on the phone.
 * A job you started keeps going after you leave the app only with a notification and a Stop button (WorkService).
 * Only the built-in page is ever shown: links to other sites open in their own app or the browser.
 */
public class MainActivity extends Activity implements Host {
    static final String LOCAL_PAGE = "file:///android_asset/local/index.html";
    private static final int MODEL_REQUEST = 3;
    private static final int FOLDER_REQUEST = 4;
    private static final int IMAGES_REQUEST = 5;
    private static final int FILE_REQUEST = 1;

    private WebView web;
    private volatile String currentUrl = "";
    private ValueCallback<Uri[]> fileCallback;
    private SharedPreferences prefs;
    private LocalBridge local;
    private java.util.function.Consumer<Uri> modelCallback;
    private java.util.function.Consumer<Uri> folderCallback;
    private java.util.function.Consumer<java.util.List<Uri>> imagesCallback;

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
        CookieManager.getInstance().setAcceptCookie(false);
        CookieManager.getInstance().removeAllCookies(null);  // older versions signed a page into Instagram: forget it

        local = new LocalBridge(this, prefs);
        web.addJavascriptInterface(local, "RN");
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
                openExternal(u);  // Instagram links, help pages: open in their own app or the browser
                return true;
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
        prefs.edit().remove("mode").remove("url").apply();  // the old Termux/PC mode is gone
        web.loadUrl(LOCAL_PAGE);
        WorkService.STOP_HOOKS.add(stopHook);
        NightRun.schedule(this);  // the nightly run (on unless switched off in Settings)
    }

    /** The built-in page (not a web site) is showing: only it may use window.RN. */
    public boolean localPageTrusted() {
        return currentUrl.startsWith("file:///android_asset/local/");
    }

    public void pickModelFile(java.util.function.Consumer<Uri> cb) {
        modelCallback = cb;
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("*/*");
        try {
            startActivityForResult(i, MODEL_REQUEST);
        } catch (Exception e) {
            modelCallback = null;
            cb.accept(null);
        }
    }

    /** Android's folder picker, opening at DCIM/Screenshots. Only the folder you choose can be read. */
    /** Android's picker for pictures (several at once). Only the pictures you choose can be read. */
    public void pickImages(java.util.function.Consumer<java.util.List<Uri>> cb) {
        imagesCallback = cb;
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("image/*");
        i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        try {
            startActivityForResult(i, IMAGES_REQUEST);
        } catch (Exception e) {
            imagesCallback = null;
            cb.accept(null);
        }
    }

    public void pickFolder(java.util.function.Consumer<Uri> cb) {
        folderCallback = cb;
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        if (Build.VERSION.SDK_INT >= 26) {
            i.putExtra(android.provider.DocumentsContract.EXTRA_INITIAL_URI,
                    Uri.parse("content://com.android.externalstorage.documents/document/primary%3ADCIM%2FScreenshots"));
        }
        try {
            startActivityForResult(i, FOLDER_REQUEST);
        } catch (Exception e) {
            folderCallback = null;
            cb.accept(null);
        }
    }

    /** Hands one picture to Google Lens (inside the Google app), or to the share menu when that app is missing. */
    public void sendToLens(Uri uri) {
        Intent send = new Intent(Intent.ACTION_SEND);
        send.setType("image/*");
        send.putExtra(Intent.EXTRA_STREAM, uri);
        send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        Intent lens = new Intent(send).setPackage("com.google.android.googlequicksearchbox");
        try {
            startActivity(lens);
        } catch (Exception e) {
            try {
                startActivity(Intent.createChooser(send, "Search with Google Lens"));
            } catch (Exception e2) {
                toast("No app can search this picture");
            }
        }
    }

    public void keepScreenOn(boolean on) {
        runOnUiThread(() -> {
            if (on) getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            else getWindow().clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        });
    }

    public String displayName(Uri uri) {
        try (Cursor c = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst()) return c.getString(0);
        } catch (Exception ignored) {
            // fall through
        }
        return uri.getLastPathSegment();
    }

    public long sizeOf(Uri uri) {
        try (Cursor c = getContentResolver().query(uri, new String[]{OpenableColumns.SIZE}, null, null, null)) {
            if (c != null && c.moveToFirst() && !c.isNull(0)) return c.getLong(0);
        } catch (Exception ignored) {
            // unknown
        }
        return -1;
    }

    public void toast(String msg) {
        runOnUiThread(() -> Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
    }

    public void openExternal(Uri u) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, u));
        } catch (Exception e) {
            toast("No app can open this link");
        }
    }

    public void callPage(String js) {
        runOnUiThread(() -> web.evaluateJavascript(js, null));
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == MODEL_REQUEST && modelCallback != null) {
            java.util.function.Consumer<Uri> cb = modelCallback;
            modelCallback = null;
            cb.accept(resultCode == RESULT_OK && data != null ? data.getData() : null);
            return;
        }
        if (requestCode == IMAGES_REQUEST && imagesCallback != null) {
            java.util.function.Consumer<java.util.List<Uri>> cb = imagesCallback;
            imagesCallback = null;
            java.util.List<Uri> got = new java.util.ArrayList<>();
            if (resultCode == RESULT_OK && data != null) {
                ClipData clip = data.getClipData();
                if (clip != null) for (int k = 0; k < clip.getItemCount(); k++) got.add(clip.getItemAt(k).getUri());
                else if (data.getData() != null) got.add(data.getData());
            }
            cb.accept(got);
            return;
        }
        if (requestCode == FOLDER_REQUEST && folderCallback != null) {
            java.util.function.Consumer<Uri> cb = folderCallback;
            folderCallback = null;
            cb.accept(resultCode == RESULT_OK && data != null ? data.getData() : null);
            return;
        }
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
        if (!working) web.onPause();  // a running job keeps its page alive
        super.onPause();
    }

    /**
     * Leaving the app (home button, another app, screen off). A job you started keeps running with its notification
     * (Stop is there); with no job running, everything stops so nothing drains the battery.
     */
    @Override
    protected void onStop() {
        if (!working) {
            callPage("window.onAppPause && onAppPause()");
            if (local != null) local.pause();
        }
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        WorkService.STOP_HOOKS.remove(stopHook);
        if (local != null) local.pause();
        WorkService.end(this);
        working = false;
        super.onDestroy();
    }

    private volatile boolean working;
    /** Stop in the notification: the page stops every job, then everything is paused as when leaving the app. */
    private final Runnable stopHook = () -> runOnUiThread(() -> {
        working = false;
        web.evaluateJavascript("window.stopAllWork && stopAllWork()", null);
        if (local != null) local.pause();
    });

    @Override
    public Context ctx() {
        return this;
    }

    @Override
    public boolean isNight() {
        return false;
    }

    @Override
    public void nightDone() {
    }

    public void setWorking(boolean on) {
        working = on;
        if (on) askNotificationPermission();
    }

    /** Android 13+: the progress notification needs permission (asked once, when the first job starts). */
    private void askNotificationPermission() {
        if (Build.VERSION.SDK_INT < 33 || prefs.getBoolean("asked_notify", false)) return;
        if (checkSelfPermission("android.permission.POST_NOTIFICATIONS") == PackageManager.PERMISSION_GRANTED) return;
        prefs.edit().putBoolean("asked_notify", true).apply();
        runOnUiThread(() -> requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 4));
    }
}
