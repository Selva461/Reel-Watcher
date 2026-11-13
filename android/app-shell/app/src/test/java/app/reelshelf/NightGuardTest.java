package app.reelshelf;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

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
        NightGuard g = new NightGuard(4 * HOUR);
        AtomicInteger started = new AtomicInteger();
        Thread[] ts = new Thread[16];
        for (int i = 0; i < ts.length; i++) {
            ts[i] = new Thread(() -> {
                if (g.tryStart(false, false, T0) == NightGuard.Verdict.START) started.incrementAndGet();
            });
        }
        for (Thread t : ts) t.start();
        for (Thread t : ts) t.join();
        assertEquals(1, started.get());
    }
}
