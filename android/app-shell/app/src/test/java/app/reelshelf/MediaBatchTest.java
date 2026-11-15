package app.reelshelf;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Random;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * The items of one share, one after the other. An item is reported finished only when its file is complete in the inbox;
 * failed items stay retryable and a retry keeps nothing twice; a stop leaves no half file; two shares never copy at once.
 */
public class MediaBatchTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private File inbox;
    private File staging;

    @Before
    public void folders() throws Exception {
        inbox = tmp.newFolder("video-inbox");
        staging = new File(tmp.getRoot(), "share-staging");
    }

    private static byte[] data(int n, int seed) {
        byte[] b = new byte[n];
        new Random(seed).nextBytes(b);
        return b;
    }

    /** A shared item with these bytes; failAt: the other app fails after that many bytes (-1: never). */
    private class Shared implements MediaBatch.Item {
        final String name;
        final byte[] bytes;
        volatile int failAt;
        volatile boolean unsupported;
        volatile boolean revoked;

        Shared(String name, byte[] bytes) {
            this.name = name;
            this.bytes = bytes;
            this.failAt = -1;
        }

        @Override
        public String label() {
            return name;
        }

        @Override
        public MediaCopy.Rules rules() throws MediaCopy.CopyException {
            if (unsupported) throw new MediaCopy.CopyException(MediaCopy.Kind.UNSUPPORTED, "not a video");
            return new MediaCopy.Rules(inbox, staging, "video_", ".mp4", 1024 * 1024, 0);
        }

        @Override
        public MediaCopy.Source source() {
            return new MediaCopy.Source() {
                @Override
                public InputStream open() {
                    if (revoked) throw new SecurityException("Permission Denial");
                    return new ByteArrayInputStream(bytes) {
                        @Override
                        public synchronized int read(byte[] b, int off, int len) {
                            if (failAt >= 0 && pos >= failAt) throw new RuntimeException(new IOException("lost"));
                            return super.read(b, off, len);
                        }
                    };
                }

                @Override
                public long size() {
                    return bytes.length;
                }
            };
        }
    }

    /** Records what the caller is told, and what the inbox holds at the moment it is told. */
    private class Log implements MediaBatch.Listener {
        final List<String> events = new ArrayList<>();
        final List<Boolean> fileThereWhenTold = new ArrayList<>();
        volatile boolean stop;
        int waited;

        @Override
        public boolean cancelled() {
            return stop;
        }

        @Override
        public void waiting() {
            waited++;
        }

        @Override
        public void started(int index, int total, String label) {
            events.add("start " + index + "/" + total + " " + label);
        }

        @Override
        public void finished(MediaBatch.Entry e) {
            events.add("done " + e.index + " " + e.status);
            fileThereWhenTold.add(e.file != null && e.file.isFile());
        }
    }

    private int inboxCount() {
        return inbox.listFiles().length;
    }

    private int stagingCount() {
        File[] f = staging.listFiles();
        return f == null ? 0 : f.length;
    }

    private static List<MediaBatch.Item> list(MediaBatch.Item... items) {
        return new ArrayList<>(Arrays.asList(items));
    }

    // ------------------------------------------------------------------ acknowledged only after it is kept

    @Test
    public void everyItemIsKeptAndToldOnlyAfterItsFileIsCompleteInTheInbox() {
        Log log = new Log();
        MediaBatch.Report r = MediaBatch.run(list(new Shared("a.mp4", data(100_000, 1)), new Shared("b.mp4", data(100_000, 2)), new Shared("c.mp4", data(5000, 3))), staging, log);
        assertEquals(3, r.kept());
        assertEquals(0, r.failed());
        assertFalse(r.cancelled);
        assertEquals(Arrays.asList(true, true, true), log.fileThereWhenTold);
        assertEquals(Arrays.asList("start 0/3 a.mp4", "done 0 KEPT", "start 1/3 b.mp4", "done 1 KEPT", "start 2/3 c.mp4", "done 2 KEPT"), log.events);
        assertEquals(3, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void aFailedItemLeavesNothingAndTheOthersAreStillKept() {
        Shared bad = new Shared("bad.mp4", data(100_000, 4));
        bad.failAt = 30_000;
        Log log = new Log();
        MediaBatch.Report r = MediaBatch.run(list(new Shared("a.mp4", data(10_000, 5)), bad, new Shared("c.mp4", data(10_000, 6))), staging, log);
        assertEquals(2, r.kept());
        assertEquals(1, r.failed());
        assertEquals(MediaCopy.Kind.FAILED, r.entries.get(1).kind);
        assertEquals("bad.mp4", r.entries.get(1).label);
        assertFalse(r.entries.get(1).why.isEmpty());
        assertEquals(Arrays.asList(true, false, true), log.fileThereWhenTold);  // the failed one: no file to be told about
        assertEquals(2, inboxCount());
        assertEquals(0, stagingCount());
    }

    // ------------------------------------------------------------------ failed items can be tried again

    @Test
    public void failedItemsThatMayWorkAgainAreOfferedForARetryAndARetryKeepsEachFileOnce() {
        Shared flaky = new Shared("flaky.mp4", data(100_000, 7));
        flaky.failAt = 20_000;
        Shared revoked = new Shared("revoked.mp4", data(1000, 8));
        revoked.revoked = true;
        Shared notAVideo = new Shared("photo.jpg", data(1000, 9));
        notAVideo.unsupported = true;
        Shared empty = new Shared("empty.mp4", new byte[0]);
        List<MediaBatch.Item> items = list(new Shared("ok.mp4", data(10_000, 10)), flaky, revoked, notAVideo, empty);

        MediaBatch.Report first = MediaBatch.run(items, staging, new Log());
        assertEquals(1, first.kept());
        assertEquals(4, first.failed());
        assertEquals("flaky and revoked may work again; a photo and an empty file never will", Arrays.asList(1, 2), first.retryable());
        assertEquals(1, inboxCount());

        flaky.failAt = -1;  // the other app is back
        revoked.revoked = false;
        List<MediaBatch.Item> again = new ArrayList<>();
        for (int i : first.retryable()) again.add(items.get(i));
        MediaBatch.Report second = MediaBatch.run(again, staging, new Log());
        assertEquals(2, second.kept());
        assertEquals(3, inboxCount());
        assertEquals(0, stagingCount());

        // running everything once more keeps nothing twice
        MediaBatch.Report third = MediaBatch.run(list(items.get(0), flaky, revoked), staging, new Log());
        assertEquals(0, third.kept());
        assertEquals(3, third.already());
        assertEquals(3, inboxCount());
    }

    @Test
    public void theSameFileSharedTwiceInOneShareIsKeptOnce() {
        byte[] same = data(50_000, 11);
        MediaBatch.Report r = MediaBatch.run(list(new Shared("one.mp4", same), new Shared("copy of one.mp4", same)), staging, new Log());
        assertEquals(1, r.kept());
        assertEquals(1, r.already());
        assertEquals(1, inboxCount());
    }

    // ------------------------------------------------------------------ stopping

    @Test
    public void stoppingBetweenItemsKeepsTheFinishedOnesAndStartsNoMore() {
        Log log = new Log() {
            @Override
            public void finished(MediaBatch.Entry e) {
                super.finished(e);
                if (e.index == 0) stop = true;  // the user presses Stop after the first
            }
        };
        MediaBatch.Report r = MediaBatch.run(list(new Shared("a.mp4", data(10_000, 12)), new Shared("b.mp4", data(10_000, 13)), new Shared("c.mp4", data(10_000, 14))), staging, log);
        assertTrue(r.cancelled);
        assertEquals(1, r.kept());
        assertEquals(2, r.count(MediaBatch.Status.NOT_STARTED));
        assertEquals(1, inboxCount());  // the finished one is a complete file: kept, not deleted
        assertEquals(0, stagingCount());
    }

    @Test
    public void stoppingInTheMiddleOfAnItemLeavesNoHalfFile() {
        Log log = new Log();
        Shared big = new Shared("big.mp4", data(600_000, 15)) {
            @Override
            public MediaCopy.Source source() {
                MediaCopy.Source real = super.source();
                return new MediaCopy.Source() {
                    @Override
                    public InputStream open() throws IOException {
                        InputStream in = real.open();
                        return new InputStream() {
                            @Override
                            public int read() throws IOException {
                                return in.read();
                            }

                            @Override
                            public int read(byte[] b, int off, int len) throws IOException {
                                log.stop = true;  // Stop pressed as the first buffer is read
                                return in.read(b, off, len);
                            }
                        };
                    }

                    @Override
                    public long size() {
                        return real.size();
                    }
                };
            }
        };
        MediaBatch.Report r = MediaBatch.run(list(big, new Shared("next.mp4", data(1000, 16))), staging, log);
        assertTrue(r.cancelled);
        assertEquals(0, r.kept());
        assertEquals(2, r.count(MediaBatch.Status.NOT_STARTED));
        assertEquals(0, inboxCount());
        assertEquals(0, stagingCount());
    }

    // ------------------------------------------------------------------ leftovers and one at a time

    @Test
    public void filesLeftInStagingByACopyThatWasKilledAreRemovedBeforeTheNextShare() throws Exception {
        assertTrue(staging.mkdirs());
        File leftover = new File(staging, "copy-123.part");
        Files.write(leftover.toPath(), new byte[5000]);
        File other = new File(staging, "keep-me.txt");  // not ours: untouched
        Files.write(other.toPath(), new byte[3]);
        MediaBatch.run(list(new Shared("a.mp4", data(1000, 17))), staging, new Log());
        assertFalse(leftover.exists());
        assertTrue(other.exists());
        assertEquals("the killed copy was never listed as media", 1, inboxCount());
    }

    @Test
    public void aProviderThatThrowsSomethingUnexpectedFailsOnlyThatItem() {
        Shared odd = new Shared("odd.mp4", data(1000, 18)) {
            @Override
            public MediaCopy.Source source() {
                throw new IllegalArgumentException("odd uri");
            }
        };
        MediaBatch.Report r = MediaBatch.run(list(odd, new Shared("fine.mp4", data(1000, 19))), staging, new Log());
        assertEquals(1, r.failed());
        assertEquals(1, r.kept());
        assertEquals(MediaCopy.Kind.FAILED, r.entries.get(0).kind);
    }

    @Test(timeout = 20_000)
    public void twoSharesNeverCopyAtTheSameTime() throws Exception {
        CountDownLatch insideFirst = new CountDownLatch(1);
        CountDownLatch letFirstGo = new CountDownLatch(1);
        AtomicInteger active = new AtomicInteger();
        AtomicInteger peak = new AtomicInteger();
        // both shares count how many items are being copied between "started" and "finished"
        class Counting extends Log {
            @Override
            public void started(int index, int total, String label) {
                super.started(index, total, label);
                peak.accumulateAndGet(active.incrementAndGet(), Math::max);
            }

            @Override
            public void finished(MediaBatch.Entry e) {
                super.finished(e);
                active.decrementAndGet();
            }
        }
        Shared slow = new Shared("slow.mp4", data(200_000, 20)) {
            @Override
            public MediaCopy.Source source() {
                MediaCopy.Source real = super.source();
                return new MediaCopy.Source() {
                    @Override
                    public InputStream open() throws IOException {
                        insideFirst.countDown();  // the first share is in the middle of its copy ...
                        try {
                            letFirstGo.await(10, TimeUnit.SECONDS);  // ... and stays there
                        } catch (InterruptedException e) {
                            throw new IOException(e);
                        }
                        return real.open();
                    }

                    @Override
                    public long size() {
                        return real.size();
                    }
                };
            }
        };
        Counting firstLog = new Counting();
        Counting secondLog = new Counting();
        Thread first = new Thread(() -> MediaBatch.run(list(slow), staging, firstLog));
        first.start();
        assertTrue(insideFirst.await(10, TimeUnit.SECONDS));
        Thread second = new Thread(() -> MediaBatch.run(list(new Shared("quick.mp4", data(1000, 21))), staging, secondLog));
        second.start();
        long until = System.currentTimeMillis() + 5000;
        while (secondLog.waited == 0 && System.currentTimeMillis() < until) Thread.sleep(10);
        assertEquals("the second share is told it waits", 1, secondLog.waited);
        assertTrue("and has not started", secondLog.events.isEmpty());
        letFirstGo.countDown();
        first.join();
        second.join();
        assertEquals("never two copies at once", 1, peak.get());
        assertEquals(2, inboxCount());
        assertEquals(0, stagingCount());
    }
}
