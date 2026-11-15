package app.reelshelf;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Random;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * One shared file copied into an inbox: complete or not at all. Nothing half-written is ever in the inbox, the staging
 * folder is empty after every outcome, the same content is never kept twice, and the limits hold.
 */
public class MediaCopyTest {
    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private File inbox;
    private File staging;
    private static final long MB = 1024 * 1024;

    @Before
    public void folders() throws Exception {
        inbox = tmp.newFolder("shot-inbox");
        staging = new File(tmp.getRoot(), "share-staging");  // not made: the copy makes it
    }

    private MediaCopy.Rules rules(long max) {
        return new MediaCopy.Rules(inbox, staging, "shot_", ".jpg", max, 0);
    }

    private static byte[] data(int n, int seed) {
        byte[] b = new byte[n];
        new Random(seed).nextBytes(b);
        return b;
    }

    /** A source of these bytes; size() says what it is told to. */
    private static MediaCopy.Source of(byte[] bytes, long declared) {
        return new MediaCopy.Source() {
            @Override
            public InputStream open() {
                return new ByteArrayInputStream(bytes);
            }

            @Override
            public long size() {
                return declared;
            }
        };
    }

    private static MediaCopy.Control go() {
        return () -> false;
    }

    private int inboxCount() {
        return inbox.listFiles().length;
    }

    private int stagingCount() {
        File[] f = staging.listFiles();
        return f == null ? 0 : f.length;
    }

    private MediaCopy.CopyException copyFails(MediaCopy.Source src, MediaCopy.Rules rules, MediaCopy.Control ctl) {
        try {
            MediaCopy.copy(src, rules, ctl);
        } catch (MediaCopy.CopyException e) {
            return e;
        }
        fail("expected the copy to fail");
        return null;
    }

    // ------------------------------------------------------------------ success

    @Test
    public void aCopyIsCompleteInTheInboxAndNothingIsLeftInStaging() throws Exception {
        byte[] bytes = data(300_000, 1);  // several buffers
        MediaCopy.Result r = MediaCopy.copy(of(bytes, bytes.length), rules(30 * MB), go());
        assertFalse(r.alreadyThere);
        assertEquals(300_000, r.bytes);
        assertEquals(inbox, r.file.getParentFile());
        assertTrue(r.file.getName().matches("shot_[0-9a-f]{24}\\.jpg"));
        assertArrayEquals(bytes, Files.readAllBytes(r.file.toPath()));
        assertEquals(1, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void theNameComesFromTheContentSoDifferentFilesHaveDifferentNames() throws Exception {
        MediaCopy.Result a = MediaCopy.copy(of(data(5000, 1), -1), rules(MB), go());
        MediaCopy.Result b = MediaCopy.copy(of(data(5000, 2), -1), rules(MB), go());
        assertFalse(a.file.equals(b.file));
        assertEquals(2, inboxCount());
    }

    @Test
    public void progressIsReportedAsBytesAreCopied() throws Exception {
        AtomicInteger calls = new AtomicInteger();
        long[] last = new long[1];
        MediaCopy.Control ctl = new MediaCopy.Control() {
            @Override
            public boolean cancelled() {
                return false;
            }

            @Override
            public void progress(long copied) {
                calls.incrementAndGet();
                assertTrue(copied > last[0]);
                last[0] = copied;
            }
        };
        MediaCopy.copy(of(data(200_000, 3), -1), rules(MB), ctl);
        assertTrue(calls.get() >= 3);
        assertEquals(200_000, last[0]);
    }

    // ------------------------------------------------------------------ interrupted and failed copies

    /** Gives some bytes, then fails (the other app dies, the cable is pulled). */
    private static MediaCopy.Source breaksAfter(int good, IOException error) {
        return new MediaCopy.Source() {
            @Override
            public InputStream open() {
                return new InputStream() {
                    int sent;

                    @Override
                    public int read() throws IOException {
                        if (sent >= good) throw error;
                        sent++;
                        return 7;
                    }

                    @Override
                    public int read(byte[] b, int off, int len) throws IOException {
                        if (sent >= good) throw error;
                        int n = Math.min(len, good - sent);
                        Arrays.fill(b, off, off + n, (byte) 7);
                        sent += n;
                        return n;
                    }
                };
            }

            @Override
            public long size() {
                return -1;
            }
        };
    }

    @Test
    public void anInterruptedCopyLeavesNothingInTheInboxOrStaging() {
        MediaCopy.CopyException e = copyFails(breaksAfter(100_000, new IOException("connection lost")), rules(MB), go());
        assertEquals(MediaCopy.Kind.FAILED, e.kind);
        assertTrue(e.kind.retryable());
        assertEquals(0, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void whileACopyRunsTheInboxHoldsNoPartOfIt() throws Exception {
        int[] seen = {-1, -1};
        byte[] bytes = data(400_000, 4);
        MediaCopy.Source src = new MediaCopy.Source() {
            @Override
            public InputStream open() {
                return new ByteArrayInputStream(bytes) {
                    @Override
                    public synchronized int read(byte[] b, int off, int len) {
                        if (pos >= 200_000 && seen[0] < 0) {  // half way: look
                            seen[0] = inbox.listFiles().length;
                            seen[1] = staging.listFiles().length;
                        }
                        return super.read(b, off, len);
                    }
                };
            }

            @Override
            public long size() {
                return bytes.length;
            }
        };
        MediaCopy.copy(src, rules(MB), go());
        assertEquals("nothing in the inbox while it is half copied", 0, seen[0]);
        assertEquals("the half copy is in staging", 1, seen[1]);
        assertEquals(1, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void aSourceThatCannotBeOpenedFailsCleanly() {
        MediaCopy.Source nothing = new MediaCopy.Source() {
            @Override
            public InputStream open() {
                return null;
            }

            @Override
            public long size() {
                return -1;
            }
        };
        MediaCopy.CopyException e = copyFails(nothing, rules(MB), go());
        assertEquals(MediaCopy.Kind.UNREADABLE, e.kind);
        assertEquals(0, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void aRevokedPermissionIsReportedAsNotAllowedToRead() {
        MediaCopy.Source revoked = new MediaCopy.Source() {
            @Override
            public InputStream open() {
                throw new SecurityException("Permission Denial");
            }

            @Override
            public long size() {
                return -1;
            }
        };
        MediaCopy.CopyException e = copyFails(revoked, rules(MB), go());
        assertEquals(MediaCopy.Kind.UNREADABLE, e.kind);
        assertTrue(e.getMessage().contains("not allowed to read"));
        assertEquals(0, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void aMissingFileIsReportedAsCouldNotBeOpened() {
        MediaCopy.Source gone = new MediaCopy.Source() {
            @Override
            public InputStream open() throws IOException {
                throw new java.io.FileNotFoundException("no such file");
            }

            @Override
            public long size() {
                return -1;
            }
        };
        assertEquals(MediaCopy.Kind.UNREADABLE, copyFails(gone, rules(MB), go()).kind);
        assertEquals(0, stagingCount());
    }

    // ------------------------------------------------------------------ empty and invalid input

    @Test
    public void anEmptySourceIsNotKeptEvenWhenTheProviderSaysNothing() {
        MediaCopy.CopyException e = copyFails(of(new byte[0], -1), rules(MB), go());
        assertEquals(MediaCopy.Kind.EMPTY, e.kind);
        assertFalse(e.kind.retryable());
        assertEquals(0, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void aProviderThatSaysZeroForUnknownDoesNotStopARealFile() throws Exception {
        byte[] bytes = data(4000, 5);
        MediaCopy.Result r = MediaCopy.copy(of(bytes, 0), rules(MB), go());  // some providers say 0 when they do not know
        assertArrayEquals(bytes, Files.readAllBytes(r.file.toPath()));
    }

    // ------------------------------------------------------------------ the size limit

    @Test
    public void aDeclaredSizeOverTheLimitIsRefusedBeforeAnythingIsWritten() {
        boolean[] opened = {false};
        MediaCopy.Source big = new MediaCopy.Source() {
            @Override
            public InputStream open() {
                opened[0] = true;
                return new ByteArrayInputStream(new byte[10]);
            }

            @Override
            public long size() {
                return 31 * MB;
            }
        };
        MediaCopy.CopyException e = copyFails(big, rules(30 * MB), go());
        assertEquals(MediaCopy.Kind.TOO_BIG, e.kind);
        assertTrue(e.getMessage().contains("30 MB"));
        assertFalse("not even opened", opened[0]);
        assertEquals(0, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void aStreamThatTurnsOutBiggerThanItSaidIsStoppedAtTheLimit() {
        byte[] bytes = data(100_000, 6);
        MediaCopy.CopyException e = copyFails(of(bytes, 1000), rules(50_000), go());  // says 1000, is 100 000, limit 50 000
        assertEquals(MediaCopy.Kind.TOO_BIG, e.kind);
        assertFalse(e.kind.retryable());
        assertEquals(0, inboxCount());
        assertEquals("the part copied so far is removed", 0, stagingCount());
    }

    @Test
    public void aFileExactlyAtTheLimitIsKept() throws Exception {
        MediaCopy.Result r = MediaCopy.copy(of(data(50_000, 7), 50_000), rules(50_000), go());
        assertEquals(50_000, r.file.length());
    }

    // ------------------------------------------------------------------ not enough storage

    @Test
    public void notEnoughRoomIsReportedBeforeAnythingIsWritten() {
        MediaCopy.Rules withReserve = new MediaCopy.Rules(inbox, staging, "shot_", ".jpg", 30 * MB, 100 * MB);
        MediaCopy.Control tight = new MediaCopy.Control() {
            @Override
            public boolean cancelled() {
                return false;
            }

            @Override
            public long freeSpace(File dir) {
                return 100 * MB + 1000;  // room for 1000 bytes and the reserve
            }
        };
        byte[] bytes = data(5000, 8);
        MediaCopy.CopyException e = copyFails(of(bytes, bytes.length), withReserve, tight);
        assertEquals(MediaCopy.Kind.NO_SPACE, e.kind);
        assertTrue(e.kind.retryable());
        assertEquals(0, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void theReserveIsKeptEvenForASourceThatDoesNotSayItsSize() {
        MediaCopy.Rules withReserve = new MediaCopy.Rules(inbox, staging, "shot_", ".jpg", 30 * MB, 100 * MB);
        MediaCopy.Control nearlyFull = new MediaCopy.Control() {
            @Override
            public boolean cancelled() {
                return false;
            }

            @Override
            public long freeSpace(File dir) {
                return 50 * MB;
            }
        };
        assertEquals(MediaCopy.Kind.NO_SPACE, copyFails(of(data(100, 9), -1), withReserve, nearlyFull).kind);
        assertEquals(0, inboxCount());
    }

    @Test
    public void aDiskThatFillsUpDuringTheCopyIsReportedAsNoSpaceAndCleanedUp() {
        MediaCopy.CopyException e = copyFails(breaksAfter(70_000, new IOException("write failed: ENOSPC (No space left on device)")), rules(MB), go());
        assertEquals(MediaCopy.Kind.NO_SPACE, e.kind);
        assertEquals(0, inboxCount());
        assertEquals(0, stagingCount());
    }

    // ------------------------------------------------------------------ stopping

    @Test
    public void stoppingInTheMiddleLeavesNothingAndIsNotAFailure() {
        int[] reads = {0};
        MediaCopy.Control stopAfterAFewBuffers = () -> ++reads[0] > 2;
        MediaCopy.CopyException e = copyFails(of(data(500_000, 10), -1), rules(MB), stopAfterAFewBuffers);
        assertEquals(MediaCopy.Kind.CANCELLED, e.kind);
        assertFalse(e.kind.retryable());
        assertEquals(0, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void aThreadThatIsInterruptedStopsTheCopy() throws Exception {
        MediaCopy.CopyException[] got = new MediaCopy.CopyException[1];
        Thread t = new Thread(() -> {
            Thread.currentThread().interrupt();
            got[0] = copyFails(of(data(100_000, 11), -1), rules(MB), go());
        });
        t.start();
        t.join();
        assertEquals(MediaCopy.Kind.CANCELLED, got[0].kind);
        assertEquals(0, inboxCount());
        assertEquals(0, stagingCount());
    }

    // ------------------------------------------------------------------ the same share again

    @Test
    public void theSameContentSharedAgainIsKeptOnlyOnce() throws Exception {
        byte[] bytes = data(120_000, 12);
        MediaCopy.Result first = MediaCopy.copy(of(bytes, bytes.length), rules(MB), go());
        MediaCopy.Result again = MediaCopy.copy(of(bytes, -1), rules(MB), go());  // a retry, or the same picture shared twice
        assertFalse(first.alreadyThere);
        assertTrue(again.alreadyThere);
        assertEquals(first.file, again.file);
        assertEquals(1, inboxCount());
        assertEquals(0, stagingCount());
    }

    @Test
    public void aRetryAfterAFailureKeepsTheFileOnce() throws Exception {
        byte[] bytes = data(150_000, 13);
        assertNotNull(copyFails(breaksAfter(60_000, new IOException("lost")), rules(MB), go()));
        assertEquals(0, inboxCount());
        MediaCopy.Result ok = MediaCopy.copy(of(bytes, bytes.length), rules(MB), go());
        assertFalse(ok.alreadyThere);
        assertEquals(1, inboxCount());
    }

    @Test
    public void aDamagedFileWithTheSameNameIsReplacedByTheCompleteCopy() throws Exception {
        byte[] bytes = data(80_000, 14);
        MediaCopy.Result first = MediaCopy.copy(of(bytes, bytes.length), rules(MB), go());
        Files.write(first.file.toPath(), Arrays.copyOf(bytes, 1000));  // cut short by something else
        MediaCopy.Result again = MediaCopy.copy(of(bytes, bytes.length), rules(MB), go());
        assertFalse(again.alreadyThere);
        assertArrayEquals(bytes, Files.readAllBytes(again.file.toPath()));
        assertEquals(1, inboxCount());
    }
}
