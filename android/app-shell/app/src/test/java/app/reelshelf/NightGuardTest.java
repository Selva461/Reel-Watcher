package app.reelshelf;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;

/** When the nightly run may start: never over the app on screen, never twice at once. */
public class NightGuardTest {
    private static final long HOUR = 3_600_000L;
    private static final long T0 = 1_000_000L;

    @Test
    public void anIdlePhoneWithTheAppClosedStartsTheRun() {
        NightGuard g = new NightGuard(4 * HOUR);
        assertEquals(NightGuard.Verdict.START, g.tryStart(false, false, T0));
        assertTrue(g.active(T0 + 1));
    }

    @Test
    public void theRunIsSkippedWhileTheAppIsOnScreen() {
        NightGuard g = new NightGuard(4 * HOUR);
        assertEquals(NightGuard.Verdict.SKIP_VISIBLE, g.tryStart(true, false, T0));
        assertEquals("a skipped night takes no claim", NightGuard.Verdict.START, g.tryStart(false, false, T0 + 1));
    }

    @Test
    public void theAppOnScreenWinsOverEverythingElse() {
        NightGuard g = new NightGuard(4 * HOUR);
        assertEquals(NightGuard.Verdict.SKIP_VISIBLE, g.tryStart(true, true, T0));
    }

    @Test
    public void aJobYouStartedKeepsTheNightFromStarting() {
        NightGuard g = new NightGuard(4 * HOUR);
        assertEquals(NightGuard.Verdict.SKIP_JOB, g.tryStart(false, true, T0));
        assertFalse(g.active(T0));
    }

    @Test
    public void aSecondAttemptWhileARunIsStartingOrGoingIsADuplicate() {
        NightGuard g = new NightGuard(4 * HOUR);
        assertEquals(NightGuard.Verdict.START, g.tryStart(false, false, T0));
        assertEquals(NightGuard.Verdict.SKIP_DUPLICATE, g.tryStart(false, false, T0));
        assertEquals(NightGuard.Verdict.SKIP_DUPLICATE, g.tryStart(false, false, T0 + HOUR));
        assertTrue(g.active(T0 + HOUR));
    }

    @Test
    public void whenTheRunEndsTheNextNightMayStart() {
        NightGuard g = new NightGuard(4 * HOUR);
        g.tryStart(false, false, T0);
        g.release();
        assertFalse(g.active(T0 + 1));
        assertEquals(NightGuard.Verdict.START, g.tryStart(false, false, T0 + 24 * HOUR));
    }

    @Test
    public void aClaimThatWasNeverReleasedExpiresSoTheNightsAreNotBlockedForGood() {
        NightGuard g = new NightGuard(4 * HOUR);
        g.tryStart(false, false, T0);
        assertEquals(NightGuard.Verdict.SKIP_DUPLICATE, g.tryStart(false, false, T0 + 4 * HOUR - 1));
        assertEquals(NightGuard.Verdict.START, g.tryStart(false, false, T0 + 4 * HOUR));
    }

    @Test
    public void releasingWithNothingClaimedChangesNothing() {
        NightGuard g = new NightGuard(4 * HOUR);
        g.release();
        assertEquals(NightGuard.Verdict.START, g.tryStart(false, false, T0));
    }

    @Test
    public void manyAlarmsAtTheSameMomentStartExactlyOneRun() throws Exception {
        // Every thread waits at a start gate and is let go together, many times over, so the claim really is contested
        // (without the gate a thread often finishes before the next one has started, and a claim that is not atomic passes).
        for (int round = 0; round < 1000; round++) {
            NightGuard g = new NightGuard(4 * HOUR);
            AtomicInteger started = new AtomicInteger();
            CountDownLatch ready = new CountDownLatch(16);
            CountDownLatch gate = new CountDownLatch(1);
            Thread[] ts = new Thread[16];
            for (int i = 0; i < ts.length; i++) {
                ts[i] = new Thread(() -> {
                    ready.countDown();
                    try {
                        gate.await();
                    } catch (InterruptedException e) {
                        return;
                    }
                    if (g.tryStart(false, false, T0) == NightGuard.Verdict.START) started.incrementAndGet();
                });
                ts[i].start();
            }
            ready.await();  // all 16 are waiting at the gate
            gate.countDown();
            for (Thread t : ts) t.join();
            assertEquals("round " + round, 1, started.get());
        }
    }

    // ------------------------------------------------------------------ touch: a run that is still going keeps its claim

    @Test
    public void aTouchedClaimStaysActiveBeyondTheOriginalExpiry() {
        NightGuard g = new NightGuard(4 * HOUR);
        g.tryStart(false, false, T0);
        g.touch(T0 + 3 * HOUR);  // the run's 60 second check, hours in
        assertTrue("past the original 4 hours", g.active(T0 + 5 * HOUR));
        assertEquals(NightGuard.Verdict.SKIP_DUPLICATE, g.tryStart(false, false, T0 + 5 * HOUR));
        assertFalse("but 4 hours after the last touch it is over", g.active(T0 + 7 * HOUR));
    }

    @Test
    public void aRunTouchedEveryMinuteNeverExpires() {
        NightGuard g = new NightGuard(4 * HOUR);
        g.tryStart(false, false, T0);
        for (long t = T0 + 60_000L; t <= T0 + 10 * HOUR; t += 60_000L) g.touch(t);
        assertTrue(g.active(T0 + 10 * HOUR));
        assertEquals(NightGuard.Verdict.SKIP_DUPLICATE, g.tryStart(false, false, T0 + 10 * HOUR));
    }

    @Test
    public void touchingAnIdleGuardDoesNotCreateAClaim() {
        NightGuard g = new NightGuard(4 * HOUR);
        g.touch(T0);
        assertFalse(g.active(T0));
        assertEquals(NightGuard.Verdict.START, g.tryStart(false, false, T0));
    }

    @Test
    public void touchingAfterTheRunEndedDoesNotBringTheClaimBack() {
        NightGuard g = new NightGuard(4 * HOUR);
        g.tryStart(false, false, T0);
        g.release();
        g.touch(T0 + 60_000L);  // a last tick of the run's timer
        assertFalse(g.active(T0 + 60_000L));
        assertEquals(NightGuard.Verdict.START, g.tryStart(false, false, T0 + 120_000L));
    }

    @Test
    public void anExpiredClaimIsNotRevivedByATouch() {
        NightGuard g = new NightGuard(4 * HOUR);
        g.tryStart(false, false, T0);
        g.touch(T0 + 4 * HOUR);  // too late: it had already expired
        assertFalse(g.active(T0 + 4 * HOUR));
        assertEquals(NightGuard.Verdict.START, g.tryStart(false, false, T0 + 4 * HOUR));
    }

    @Test
    public void anUntouchedClaimStillExpiresAsBefore() {
        NightGuard g = new NightGuard(4 * HOUR);
        g.tryStart(false, false, T0);
        assertTrue(g.active(T0 + 4 * HOUR - 1));
        assertFalse(g.active(T0 + 4 * HOUR));
        assertEquals(NightGuard.Verdict.START, g.tryStart(false, false, T0 + 4 * HOUR));
    }

    @Test
    public void touchingWhileOtherThreadsClaimAndReleaseNeverLeavesAClaimBehind() throws Exception {
        NightGuard g = new NightGuard(4 * HOUR);
        g.tryStart(false, false, T0);
        Thread toucher = new Thread(() -> {
            for (int i = 0; i < 5000; i++) g.touch(T0 + i);
        });
        toucher.start();
        g.release();  // the run ends while the timer is still ticking
        toucher.join();
        assertFalse("the last word is the release", g.active(T0 + 10_000));
    }
}
