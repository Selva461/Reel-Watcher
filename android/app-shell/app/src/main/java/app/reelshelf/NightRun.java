package app.reelshelf;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.util.Calendar;
import java.util.function.Consumer;

/**
 * The nightly run (on by default, Settings can switch it off or change the time and battery level): once a night at
 * the chosen hour (midnight unless changed), if the battery is above the chosen level, Reel Shelf does what the
 * Overnight run button does, without its screen: files what you shared during the day and any export you imported,
 * writes notes for reels still waiting (reels already on the shelf or done are skipped), reads only new screenshots
 * and checks titles online. It shows the usual notification with Stop and ends by itself.
 */
public class NightRun extends BroadcastReceiver {
    static final String ON = "night_on", HOUR = "night_hour", MIN_BATTERY = "night_min_battery";
    private static final String ACTION = "app.reelshelf.NIGHT_RUN";

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("reelshelf", Context.MODE_PRIVATE);
    }

    static boolean on(Context c) {
        return prefs(c).getBoolean(ON, true);
    }

    static int hour(Context c) {
        return prefs(c).getInt(HOUR, 0);
    }

    static int minBattery(Context c) {
        return prefs(c).getInt(MIN_BATTERY, 40);
    }

    private static PendingIntent pending(Context c) {
        return PendingIntent.getBroadcast(c, 9, new Intent(c, NightRun.class).setAction(ACTION),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    /** Sets (or clears) the alarm for the next run at the chosen hour. Called at app start, after a run and at boot. */
    static void schedule(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        am.cancel(pending(c));
        if (!on(c)) return;
        Calendar at = Calendar.getInstance();
        at.set(Calendar.HOUR_OF_DAY, hour(c));
        at.set(Calendar.MINUTE, 0);
        at.set(Calendar.SECOND, 0);
        at.set(Calendar.MILLISECOND, 0);
        if (at.getTimeInMillis() <= System.currentTimeMillis() + 60_000) at.add(Calendar.DAY_OF_MONTH, 1);
        boolean exact = Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms();
        if (exact) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at.getTimeInMillis(), pending(c));
        else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at.getTimeInMillis(), pending(c));
    }

    /** Battery level (0-100, or -1) and whether it is charging. */
    static int[] battery(Context c) {
        Intent b = c.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (b == null) return new int[]{-1, 0};
        int level = b.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
        int scale = b.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
        int status = b.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
        boolean charging = status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL;
        return new int[]{level < 0 || scale <= 0 ? -1 : level * 100 / scale, charging ? 1 : 0};
    }

    @Override
    public void onReceive(Context c, Intent intent) {
        String a = intent == null ? null : intent.getAction();
        if (Intent.ACTION_BOOT_COMPLETED.equals(a) || Intent.ACTION_MY_PACKAGE_REPLACED.equals(a)) {
            schedule(c);
            return;
        }
        if (!ACTION.equals(a)) return;
        schedule(c);  // the next night, whatever happens tonight
        if (!on(c)) return;
        int[] b = battery(c);
        if (b[0] >= 0 && b[0] < minBattery(c) && b[1] == 0) return;  // too low tonight: skipped
        WorkService.startNight(c);
    }

    // ------------------------------------------------------------------ the page, run without a screen

    /** Shows the built-in page in a WebView that is never on screen, with the same window.RN as the app. */
    static final class Headless implements Host {
        private final Context ctx;
        private final Runnable onDone;
        private final Handler ui = new Handler(Looper.getMainLooper());
        private WebView web;
        private LocalBridge bridge;
        private volatile String url = "";
        private boolean done;

        Headless(Context ctx, Runnable onDone) {
            this.ctx = ctx;
            this.onDone = onDone;
        }

        void start() {
            web = new WebView(ctx);
            WebSettings s = web.getSettings();
            s.setJavaScriptEnabled(true);
            s.setDomStorageEnabled(true);
            s.setAllowFileAccess(false);
            s.setAllowContentAccess(false);
            bridge = new LocalBridge(this, prefs(ctx));
            web.addJavascriptInterface(bridge, "RN");
            web.setWebViewClient(new WebViewClient() {
                @Override
                public void onPageStarted(WebView v, String u, android.graphics.Bitmap f) {
                    url = u == null ? "" : u;
                }

                @Override
                public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                    return !"file".equals(r.getUrl().getScheme());  // nothing else is opened at night
                }
            });
            web.loadUrl(MainActivity.LOCAL_PAGE + "#/night");
            ui.postDelayed(this::watchBattery, 60_000);
        }

        /** Stops the run when the battery falls well below the chosen level and the phone is not charging. */
        private void watchBattery() {
            if (done) return;
            int[] b = battery(ctx);
            int floor = Math.max(15, minBattery(ctx) - 20);
            if (b[0] >= 0 && b[0] < floor && b[1] == 0) {
                callPage("window.stopAllWork && stopAllWork()");
                ui.postDelayed(this::nightDone, 5000);
                return;
            }
            ui.postDelayed(this::watchBattery, 60_000);
        }

        void stop() {
            if (done) return;
            done = true;
            if (bridge != null) bridge.pause();
            if (web != null) {
                web.destroy();
                web = null;
            }
        }

        @Override public Context ctx() { return ctx; }
        @Override public boolean localPageTrusted() { return url.startsWith("file:///android_asset/local/"); }
        @Override public void callPage(String js) { ui.post(() -> { if (web != null) web.evaluateJavascript(js, null); }); }
        @Override public void runOnUiThread(Runnable r) { ui.post(r); }
        @Override public void toast(String msg) { }
        @Override public void startActivity(Intent i) { }
        @Override public void openExternal(Uri u) { }
        @Override public void openServerMode() { }
        @Override public void pickModelFile(Consumer<Uri> cb) { cb.accept(null); }
        @Override public void pickFolder(Consumer<Uri> cb) { cb.accept(null); }
        @Override public void sendToLens(Uri uri) { }
        @Override public void keepScreenOn(boolean on) { }
        @Override public String displayName(Uri uri) { return uri.getLastPathSegment(); }
        @Override public long sizeOf(Uri uri) { return -1; }
        @Override public void setWorking(boolean on) { }
        @Override public boolean isNight() { return true; }

        @Override
        public void nightDone() {
            ui.post(() -> {
                stop();
                onDone.run();
            });
        }
    }

    static void toastIfOpen(Context c, String msg) {
        Toast.makeText(c, msg, Toast.LENGTH_SHORT).show();
    }
}
