package app.reelshelf;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import java.util.Set;
import java.util.concurrent.CopyOnWriteArraySet;

/**
 * Keeps a job you started (Start, screenshots, online check, Instagram export download) running after you leave the
 * app. It only exists while such a job runs: it shows a notification with the progress and a Stop button, and it
 * ends itself the moment the job finishes or you tap Stop. Nothing ever starts it on its own.
 */
public class WorkService extends Service {
    private static final String CHANNEL = "work";
    private static final int ID = 7;
    private static final String ACTION_STOP = "app.reelshelf.STOP_WORK";
    private static final long MAX_HOLD_MS = 3L * 60 * 60 * 1000;  // the CPU is never kept awake longer than this

    /** Called when Stop is tapped in the notification (the page and the export screen register one). */
    static final Set<Runnable> STOP_HOOKS = new CopyOnWriteArraySet<>();
    private static volatile boolean running;

    private static final String ACTION_NIGHT = "app.reelshelf.NIGHT";
    private PowerManager.WakeLock lock;
    private NightRun.Headless night;

    /** The nightly run (from NightRun's alarm): the page runs without a screen inside this service. */
    static void startNight(Context ctx) {
        if (running) return;  // something you started is already running
        Intent i = new Intent(ctx, WorkService.class).setAction(ACTION_NIGHT)
                .putExtra("title", "Nightly run").putExtra("text", "Shared reels, new screenshots, titles");
        try {
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i);
            else ctx.startService(i);
        } catch (Exception ignored) {
            // Android refused tonight; the alarm is set again for tomorrow
        }
    }

    /** Starts the service, or updates its notification. */
    static void show(Context ctx, String title, String text, int done, int total) {
        Intent i = new Intent(ctx, WorkService.class)
                .putExtra("title", title == null ? "Reel Shelf is working" : title)
                .putExtra("text", text == null ? "" : text)
                .putExtra("done", done)
                .putExtra("total", total);
        try {
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i);
            else ctx.startService(i);
        } catch (Exception ignored) {
            // Android refused (for example the app was already in the background): the job keeps the old behavior
        }
    }

    static void end(Context ctx) {
        ctx.stopService(new Intent(ctx, WorkService.class));
    }

    static boolean isRunning() {
        return running;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            if (night != null) night.callPage("window.stopAllWork && stopAllWork()");
            for (Runnable r : STOP_HOOKS) {
                try {
                    r.run();
                } catch (Exception ignored) {
                }
            }
            stopSelf();
            return START_NOT_STICKY;
        }
        Notification n = build(intent);
        if (!running) {
            if (Build.VERSION.SDK_INT >= 29) startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            else startForeground(ID, n);
            running = true;
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            lock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ReelShelf:work");
            lock.setReferenceCounted(false);
            lock.acquire(MAX_HOLD_MS);
        } else {
            ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).notify(ID, n);
        }
        if (intent != null && ACTION_NIGHT.equals(intent.getAction()) && night == null) {
            night = new NightRun.Headless(this, this::stopSelf);
            night.start();
        }
        return START_NOT_STICKY;  // if Android kills it, it does not come back by itself
    }

    private Notification build(Intent in) {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Work in progress", NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("Shown only while a job you started keeps running after you leave the app");
            nm.createNotificationChannel(ch);
        }
        String title = in == null ? "Reel Shelf is working" : in.getStringExtra("title");
        String text = in == null ? "" : in.getStringExtra("text");
        int done = in == null ? 0 : in.getIntExtra("done", 0);
        int total = in == null ? 0 : in.getIntExtra("total", 0);
        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, WorkService.class).setAction(ACTION_STOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        b.setSmallIcon(android.R.drawable.stat_sys_download)
                .setContentTitle(title)
                .setContentText(text)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setContentIntent(open)
                .addAction(new Notification.Action.Builder(null, "Stop", stop).build());
        if (total > 0) b.setProgress(total, Math.min(done, total), false);
        else b.setProgress(0, 0, true);
        return b.build();
    }

    @Override
    public void onDestroy() {
        running = false;
        if (night != null) night.stop();
        night = null;
        if (lock != null && lock.isHeld()) lock.release();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
