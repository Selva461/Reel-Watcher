package app.reelshelf;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Copies the pictures or videos of one share, one after the other (never two at once, in this app: a lock for the whole
 * process), with {@link MediaCopy}. Reports each item when it is finished, and only then: an item that was kept is
 * complete in the inbox by that time, an item that was not kept leaves nothing behind. The items that failed stay in the
 * report so the caller can run them again; copying them again keeps nothing twice. Runs on the thread that calls it (never
 * the main thread: the caller decides). Pure Java, tested on a computer.
 */
final class MediaBatch {
    /** One thing that was shared. label() and rules() may read from the other app: they are called on the copying thread. */
    interface Item {
        String label();

        /** Where and how big this one may be, or the reason it cannot be kept at all (not a picture). */
        MediaCopy.Rules rules() throws MediaCopy.CopyException;

        MediaCopy.Source source();
    }

    interface Listener {
        boolean cancelled();

        /** Another share is being copied: this one starts when it is done. */
        default void waiting() {
        }

        default void started(int index, int total, String label) {
        }

        default void bytes(int index, long copied, long size) {
        }

        /** Item index is finished. For a kept one the file is complete in the inbox already (this is the acknowledgement). */
        default void finished(Entry entry) {
        }

        default long freeSpace(File dir) {
            return dir.getUsableSpace();
        }

        /** The stream being read, or null when none is (see MediaCopy.Control.opened): closing it ends a stalled read. */
        default void opened(java.io.Closeable stream) {
        }
    }

    enum Status { KEPT, ALREADY, FAILED, NOT_STARTED }

    static final class Entry {
        final int index;
        final String label;
        final Status status;
        final MediaCopy.Kind kind;  // why not, for FAILED
        final String why;           // the same in words
        final File file;            // for KEPT and ALREADY

        Entry(int index, String label, Status status, MediaCopy.Kind kind, String why, File file) {
            this.index = index;
            this.label = label;
            this.status = status;
            this.kind = kind;
            this.why = why;
            this.file = file;
        }
    }

    static final class Report {
        final List<Entry> entries = new ArrayList<>();
        /** Stopped before all items were done (the rest are NOT_STARTED). */
        boolean cancelled;

        int count(Status s) {
            int n = 0;
            for (Entry e : entries) if (e.status == s) n++;
            return n;
        }

        int kept() {
            return count(Status.KEPT);
        }

        int already() {
            return count(Status.ALREADY);
        }

        int failed() {
            return count(Status.FAILED);
        }

        /** The failed ones that may work when tried again, as positions in the list that was run. */
        List<Integer> retryable() {
            List<Integer> out = new ArrayList<>();
            for (Entry e : entries) if (e.status == Status.FAILED && e.kind.retryable()) out.add(e.index);
            return out;
        }

        /** The reason of the first failure, or "". */
        String firstWhy() {
            for (Entry e : entries) if (e.status == Status.FAILED) return e.why;
            return "";
        }

        /** In the app now: kept just now, or kept before (the same content). */
        int saved() {
            return kept() + already();
        }

        /** What the page is told when at least one was saved: "3", or {"kept":3,"failed":2,"why":"..."} when some were not. */
        String pickerAnswer() {
            int failed = failed();
            if (failed == 0) return String.valueOf(saved());
            try {
                return new JSONObject().put("kept", saved()).put("failed", failed).put("why", firstWhy()).toString();
            } catch (JSONException e) {
                return String.valueOf(saved());
            }
        }
    }

    /** Only one share is copied at a time in the whole app (one buffer, one disk writer, however many are shared). */
    private static final ReentrantLock ONE_AT_A_TIME = new ReentrantLock();
    /**
     * How long a share waits for the one before it (ms). A copy that never ends (the other app stalls) must not hold everyone
     * up for ever: after this the waiting items are reported as not saved, and Try again can start them.
     */
    static volatile long maxWaitMillis = 2 * 60 * 1000;

    private MediaBatch() {
    }

    /**
     * Copies the items. staging is the folder the half-written files live in (never the inbox). Files left there by a
     * copy that was cut short (the phone killed the app) are removed first: nothing else can be using it, the lock is ours.
     */
    static Report run(List<Item> items, File staging, Listener l) {
        Report report = new Report();
        try {
            if (!ONE_AT_A_TIME.tryLock()) {
                l.waiting();
                long until = System.currentTimeMillis() + maxWaitMillis;
                while (!ONE_AT_A_TIME.tryLock(200, TimeUnit.MILLISECONDS)) {
                    if (l.cancelled()) return notStarted(report, items);  // Stop works while waiting too
                    if (System.currentTimeMillis() >= until) {
                        for (int i = 0; i < items.size(); i++) {
                            report.entries.add(new Entry(i, "", Status.FAILED, MediaCopy.Kind.FAILED, "another share is still being copied", null));
                        }
                        return report;
                    }
                }
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return notStarted(report, items);
        }
        try {
            removeLeftovers(staging);
            for (int i = 0; i < items.size(); i++) {
                Item item = items.get(i);
                if (l.cancelled()) {
                    report.cancelled = true;
                    for (int j = i; j < items.size(); j++) report.entries.add(new Entry(j, "", Status.NOT_STARTED, null, "", null));
                    return report;
                }
                final int at = i;
                String label = labelOf(item, i);
                l.started(i, items.size(), label);
                Entry entry;
                try {
                    MediaCopy.Rules rules = item.rules();
                    MediaCopy.Source source = item.source();
                    final long size = source.size();  // asked once: the other app may answer slowly
                    MediaCopy.Result r = MediaCopy.copy(source, rules, new MediaCopy.Control() {
                        @Override
                        public boolean cancelled() {
                            return l.cancelled();
                        }

                        @Override
                        public void progress(long copied) {
                            l.bytes(at, copied, size);
                        }

                        @Override
                        public long freeSpace(File dir) {
                            return l.freeSpace(dir);
                        }

                        @Override
                        public void opened(java.io.Closeable stream) {
                            l.opened(stream);
                        }
                    });
                    entry = new Entry(i, label, r.alreadyThere ? Status.ALREADY : Status.KEPT, null, "", r.file);
                } catch (MediaCopy.CopyException e) {
                    if (e.kind == MediaCopy.Kind.CANCELLED) {
                        report.cancelled = true;
                        for (int j = i; j < items.size(); j++) report.entries.add(new Entry(j, "", Status.NOT_STARTED, null, "", null));
                        return report;
                    }
                    entry = new Entry(i, label, Status.FAILED, e.kind, e.getMessage(), null);
                } catch (RuntimeException e) {  // the other app's provider threw something unexpected: this one failed, the others go on
                    entry = new Entry(i, label, Status.FAILED, MediaCopy.Kind.FAILED, "it could not be read", null);
                }
                report.entries.add(entry);
                l.finished(entry);
            }
            return report;
        } finally {
            ONE_AT_A_TIME.unlock();
        }
    }

    private static Report notStarted(Report report, List<Item> items) {
        for (int i = 0; i < items.size(); i++) report.entries.add(new Entry(i, "", Status.NOT_STARTED, null, "", null));
        report.cancelled = true;
        return report;
    }

    private static String labelOf(Item item, int i) {
        try {
            String s = item.label();
            return s == null || s.isEmpty() ? "item " + (i + 1) : s;
        } catch (RuntimeException e) {
            return "item " + (i + 1);
        }
    }

    private static void removeLeftovers(File staging) {
        File[] old = staging.listFiles();
        if (old == null) return;
        for (File f : old) if (f.isFile() && f.getName().endsWith(".part")) f.delete();
    }
}
