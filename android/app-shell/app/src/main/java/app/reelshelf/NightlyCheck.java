package app.reelshelf;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * The optional nightly online check (off until you switch it on in Settings), like WhatsApp's night backup.
 * Android runs it about once a day, when the phone is not being used and the battery is at 40% or more (any internet).
 * It only looks at titles that were never checked, stops when Android asks, and never runs AI.
 * This is the one thing Reel Shelf does while closed, and only because you turned it on.
 */
public class NightlyCheck extends JobService {
    static final int JOB_ID = 4201;
    /** Android gives a job about 10 minutes; stop well before. */
    private static final long BUDGET_MS = 8 * 60_000L;

    private final AtomicBoolean stop = new AtomicBoolean(false);
    private Thread thread;

    static void schedule(Context ctx, boolean on) {
        JobScheduler js = (JobScheduler) ctx.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        if (!on) {
            js.cancel(JOB_ID);
            return;
        }
        JobInfo job = new JobInfo.Builder(JOB_ID, new ComponentName(ctx, NightlyCheck.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)       // Wi-Fi or mobile data; no charger needed
                .setRequiresDeviceIdle(true)                            // screen off, not in use: at night
                .setPeriodic(24L * 3600_000L)
                .setPersisted(true)                                     // still on after a restart
                .build();
        js.schedule(job);
    }

    static boolean scheduled(Context ctx) {
        JobScheduler js = (JobScheduler) ctx.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        return js != null && js.getPendingJob(JOB_ID) != null;
    }

    static String tmdbKey(Context ctx) {
        return setting(ctx, "tmdbKey");
    }

    static String omdbKey(Context ctx) {
        return setting(ctx, "omdbKey");
    }

    private static String setting(Context ctx, String name) {
        SharedPreferences p = ctx.getSharedPreferences("reelshelf", Context.MODE_PRIVATE);
        try {
            return new JSONObject(p.getString("local_settings", "{}")).optString(name, "");
        } catch (Exception e) {
            return "";
        }
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        SharedPreferences p = getSharedPreferences("reelshelf", MODE_PRIVATE);
        if (!p.getBoolean("nightly_check", false) || VerifyJob.running()) return false;
        int level = NightRun.battery(this)[0];
        if (level >= 0 && level < NightRun.minBattery(this)) return false;  // battery is the only rule: below 40%, not tonight
        stop.set(false);
        thread = new Thread(() -> {
            try {
                TitleVerifier v = new TitleVerifier(TitleVerifier.NET, TitleVerifier.REAL_CLOCK, tmdbKey(this), stop);
                v.omdbKey = omdbKey(this);
                JSONObject sum = new VerifyJob(getFilesDir(), v, stop).run(0, BUDGET_MS, null);
                sum.put("at", System.currentTimeMillis());
                p.edit().putString("nightly_last", sum.toString()).apply();
            } catch (Exception ignored) {
                // tried again next night
            }
            jobFinished(params, false);
        }, "nightly-check");
        thread.setPriority(Thread.MIN_PRIORITY);
        thread.start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        stop.set(true);  // Android wants the phone back (screen on, no internet)
        return true;     // try again later
    }
}
