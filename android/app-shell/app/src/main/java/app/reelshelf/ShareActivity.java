package app.reelshelf;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.io.Closeable;
import java.io.File;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Receives "Share" from Instagram (a reel link), from Meta AI (its answer), or pictures and reel videos from the gallery.
 * A link or a text is saved at once and the screen closes, so you stay in Instagram. Pictures and videos are copied into the
 * app on a worker thread, with a screen that shows how far it is and stays until every file is safely kept (or says which
 * could not be, with Try again). Nothing is processed now: open Reel Shelf and tap Start when you want.
 * Leaving the screen (Back, Home) stops the copy; what was already kept stays, and nothing half-written is ever left behind.
 */
public class ShareActivity extends Activity {
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile boolean destroyed;
    private volatile boolean stopRequested;
    private volatile Closeable openStream;  // the file being read: closing it ends a read that never returns (the other app stalls)
    private ExecutorService worker;  // one thread; MediaBatch also lets only one share copy at a time in the whole app

    private boolean video;
    private List<MediaBatch.Item> items;
    private int overLimit;
    private boolean copying;
    private int kept;
    private int already;
    private final Map<Integer, MediaBatch.Entry> failed = new LinkedHashMap<>();  // item position -> why it was not kept
    private long lastPaint;

    private LinearLayout buttons;
    private TextView title;
    private TextView detail;
    private ProgressBar bar;
    private Button stopButton;
    private Button retryButton;
    private Button closeButton;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent in = getIntent();
        String type = in == null ? null : in.getType();
        if (type != null && (type.startsWith("image/") || type.startsWith("video/"))) {  // screenshots, or a reel video (Instagram's Download, a screen recording)
            startMedia(streamsOf(in), type.startsWith("video/"));
            return;
        }
        String text = null;
        if (in != null && Intent.ACTION_SEND.equals(in.getAction())) {
            CharSequence t = in.getCharSequenceExtra(Intent.EXTRA_TEXT);
            String subject = in.getStringExtra(Intent.EXTRA_SUBJECT);
            text = t == null ? subject : (subject != null && !t.toString().contains(subject) ? subject + "\n" + t : t.toString());
        }
        if (text == null || text.trim().isEmpty()) {
            Toast.makeText(this, "Nothing to save: share a reel link or a text", Toast.LENGTH_SHORT).show();
        } else {
            LocalBridge.queueShared(this, text);
            boolean link = text.matches("(?s).*(instagram\\.com/(reels?|p|tv)/|youtube\\.com/(shorts/|watch)|youtu\\.be/).*");
            Toast.makeText(this, link ? "Saved to Reel Shelf. Open it and tap Start when you want the notes."
                    : "Saved to Reel Shelf. Open it to file this answer.", Toast.LENGTH_LONG).show();
        }
        finish();
    }

    private static List<Uri> streamsOf(Intent in) {
        List<Uri> uris = new ArrayList<>();
        if (Intent.ACTION_SEND_MULTIPLE.equals(in.getAction())) {
            ArrayList<Uri> many = in.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (many != null) for (Uri u : many) if (u != null) uris.add(u);
        } else {
            Uri one = in.getParcelableExtra(Intent.EXTRA_STREAM);
            if (one != null) uris.add(one);
        }
        return uris;
    }

    // ------------------------------------------------------------------ pictures and videos

    private void startMedia(List<Uri> uris, boolean isVideo) {
        video = isVideo;
        int max = isVideo ? SharedItems.MAX_VIDEOS : SharedItems.MAX_PICTURES;
        overLimit = Math.max(0, uris.size() - max);
        List<Uri> use = uris.subList(0, Math.min(uris.size(), max));
        items = isVideo ? SharedItems.videos(this, use) : SharedItems.pictures(this, use);
        if (items.isEmpty()) {
            Toast.makeText(this, "Nothing to save: share a picture or a video", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }
        buildScreen();
        worker = Executors.newSingleThreadExecutor();
        List<Integer> all = new ArrayList<>();
        for (int i = 0; i < items.size(); i++) all.add(i);
        attempt(all);
    }

    /** Copies these items (positions in the list), on the worker thread. The screen only gets told what happened. */
    private void attempt(List<Integer> which) {
        copying = true;
        stopRequested = false;
        showCopying();
        List<MediaBatch.Item> run = new ArrayList<>();
        for (int i : which) run.add(items.get(i));
        final File staging = SharedItems.staging(getApplicationContext());
        worker.execute(() -> {
            MediaBatch.Report report;
            try {
                report = MediaBatch.run(run, staging, new MediaBatch.Listener() {
                    @Override
                    public boolean cancelled() {
                        return stopRequested || destroyed;
                    }

                    @Override
                    public void opened(Closeable stream) {
                        openStream = stream;
                    }

                    @Override
                    public void waiting() {
                        post(() -> show("Waiting for another share to finish...", "", -1));
                    }

                    @Override
                    public void started(int index, int total, String label) {
                        String of = which.get(index) + 1 + " of " + (items.size());
                        post(() -> show((video ? "Saving video " : "Saving picture ") + of, label, 0));
                    }

                    @Override
                    public void bytes(int index, long copied, long size) {
                        long now = System.currentTimeMillis();
                        if (now - lastPaint < 100 && copied != size) return;  // not more than ten times a second
                        lastPaint = now;
                        post(() -> show(null, size > 0 ? MediaCopy.mb(copied) + " of " + MediaCopy.mb(size) : MediaCopy.mb(copied), size > 0 ? (int) (copied * 1000 / size) : -1));
                    }
                });
            } catch (Throwable t) {  // whatever it was, the screen must not stay on "Saving..."
                report = null;
            }
            final MediaBatch.Report done = report;
            post(() -> {
                if (done == null) wentWrong();
                else attemptDone(done, which);
            });
        });
    }

    private void wentWrong() {
        copying = false;
        Toast.makeText(this, "Something went wrong while saving. What was already saved stays; share the rest again.", Toast.LENGTH_LONG).show();
        finish();
    }

    /** Ends a read that is waiting for the other app. Closing a file is quick, but not on the screen's thread. */
    private void closeOpenStream() {
        final Closeable s = openStream;
        if (s == null) return;
        new Thread(() -> {
            try {
                s.close();
            } catch (Exception e) {
                // already closed, or the other app is gone: the copy ends either way
            }
        }, "share-close").start();
    }

    private void attemptDone(MediaBatch.Report report, List<Integer> which) {
        copying = false;
        for (MediaBatch.Entry e : report.entries) {
            int at = which.get(e.index);
            if (e.status == MediaBatch.Status.KEPT) {
                kept++;
                failed.remove(at);
            } else if (e.status == MediaBatch.Status.ALREADY) {
                already++;
                failed.remove(at);
            } else if (e.status == MediaBatch.Status.FAILED) {
                failed.put(at, e);
            }
        }
        if (report.cancelled) {
            Toast.makeText(this, "Stopped. " + count(kept + already) + " saved; share the rest again.", Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        if (failed.isEmpty() && overLimit == 0) {
            int n = kept + already;
            String what = count(n);
            String msg = kept == 0 ? what + " already in Reel Shelf (shared before)."
                    : what + " saved" + (already > 0 ? " (" + already + " of them already saved before)" : "") + ". "
                    + (video ? "Reel Shelf reads the whole reel on Start (or at night)." : "Open Reel Shelf, Start, Read my screenshots (or wait for the nightly run).");
            Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        showProblems();
    }

    private String count(int n) {
        String one = video ? "video" : "picture";
        return n + " " + (n == 1 ? one : one + "s");
    }

    // ------------------------------------------------------------------ the screen

    private void showCopying() {
        title.setText(video ? "Saving your videos" : "Saving your pictures");
        detail.setText("");
        bar.setVisibility(View.VISIBLE);
        bar.setIndeterminate(true);
        stopButton.setEnabled(true);
        stopButton.setText("Stop");
        stopButton.setVisibility(View.VISIBLE);
        retryButton.setVisibility(View.GONE);
        closeButton.setVisibility(View.GONE);
    }

    /** title/line null: unchanged. permille < 0: no known size. */
    private void show(String heading, String line, int permille) {
        if (heading != null) title.setText(heading);
        if (line != null) detail.setText(line);
        if (permille < 0) {
            bar.setIndeterminate(true);
        } else {
            bar.setIndeterminate(false);
            bar.setProgress(permille);
        }
    }

    private void showProblems() {
        int total = items.size() + overLimit;
        title.setText(kept + already + " of " + total + " saved");
        StringBuilder s = new StringBuilder();
        int shown = 0;
        boolean again = false;
        for (Map.Entry<Integer, MediaBatch.Entry> f : failed.entrySet()) {
            MediaBatch.Entry e = f.getValue();
            String name = e.label == null || e.label.isEmpty() ? "item " + (f.getKey() + 1) : e.label;  // its place in the whole share
            if (shown++ < 6) s.append("• ").append(name).append(": ").append(e.why).append('\n');
            if (e.kind != null && e.kind.retryable()) again = true;
        }
        if (failed.size() > 6) s.append("• and ").append(failed.size() - 6).append(" more\n");
        if (overLimit > 0) s.append("• ").append(overLimit).append(" more than the limit of ").append(video ? SharedItems.MAX_VIDEOS : SharedItems.MAX_PICTURES).append(" at once\n");
        s.append(again ? "What was saved stays. Try again for the rest, or close." : "What was saved stays.");
        detail.setText(s.toString().trim());
        bar.setVisibility(View.GONE);
        stopButton.setVisibility(View.GONE);
        retryButton.setVisibility(again ? View.VISIBLE : View.GONE);
        closeButton.setVisibility(View.VISIBLE);
    }

    private void buildScreen() {
        LinearLayout root = new LinearLayout(this);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(0x99000000);
        root.setPadding(dp(24), dp(24), dp(24), dp(24));
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(20), dp(20), dp(12));
        GradientDrawable back = new GradientDrawable();
        back.setColor(Color.WHITE);
        back.setCornerRadius(dp(16));
        box.setBackground(back);
        title = new TextView(this);
        title.setTextSize(18);
        title.setTypeface(null, Typeface.BOLD);
        title.setTextColor(0xFF111111);
        detail = new TextView(this);
        detail.setTextSize(14);
        detail.setTextColor(0xFF444444);
        detail.setPadding(0, dp(8), 0, dp(8));
        bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(1000);
        buttons = new LinearLayout(this);
        buttons.setGravity(Gravity.END);
        stopButton = button("Stop", () -> {
            stopRequested = true;
            closeOpenStream();
            stopButton.setEnabled(false);
            stopButton.setText("Stopping...");
        });
        retryButton = button("Try again", () -> {
            List<Integer> again = new ArrayList<>();
            for (Map.Entry<Integer, MediaBatch.Entry> e : failed.entrySet()) if (e.getValue().kind != null && e.getValue().kind.retryable()) again.add(e.getKey());
            if (!again.isEmpty()) attempt(again);
        });
        closeButton = button("Close", this::finish);
        buttons.addView(stopButton);
        buttons.addView(retryButton);
        buttons.addView(closeButton);
        box.addView(title);
        box.addView(detail);
        box.addView(bar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        box.addView(buttons, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(box, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        setContentView(root);
    }

    private Button button(String label, Runnable click) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setOnClickListener(v -> click.run());
        return b;
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }

    /** Runs on the screen's thread, and not at all once the screen is gone. */
    private void post(Runnable r) {
        if (destroyed) return;
        ui.post(() -> {
            if (!destroyed) r.run();
        });
    }

    @Override
    public void onBackPressed() {
        finish();  // while copying this stops the copy (onDestroy)
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        stopRequested = true;
        closeOpenStream();
        if (worker != null) worker.shutdownNow();  // the copy sees it at the next buffer, removes its half file and ends
        ui.removeCallbacksAndMessages(null);
        if (copying) {
            Toast.makeText(getApplicationContext(), "Stopped before it finished. What was already saved stays; share the rest again.", Toast.LENGTH_LONG).show();
        }
        super.onDestroy();
    }
}
