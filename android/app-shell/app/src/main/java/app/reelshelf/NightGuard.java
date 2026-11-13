package app.reelshelf;

import java.util.concurrent.atomic.AtomicLong;

/**
 * Whether the nightly run may start, and the claim that keeps two nightly runs from overlapping. The run is skipped when
 * Reel Shelf is on screen (you are using it), when a job you started is still running, and when a nightly run is
 * already starting or running. The claim is taken before the service starts, so two alarms at the same moment cannot
 * both start one. It is released when the run ends, and expires on its own after a while in case the service never
 * got going. Pure Java, tested on a computer.
 */
final class NightGuard {
    /** Why a run may not start now. */
    enum Verdict { START, SKIP_VISIBLE, SKIP_JOB, SKIP_DUPLICATE }

    private final AtomicLong since = new AtomicLong(0);
    private final long expireMs;

    NightGuard(long expireMs) {
        this.expireMs = expireMs;
    }

    /** Decides, and when the answer is START takes the claim. now: any clock in milliseconds (above 0). */
    Verdict tryStart(boolean appVisible, boolean jobRunning, long now) {
        if (appVisible) return Verdict.SKIP_VISIBLE;
        if (jobRunning) return Verdict.SKIP_JOB;
        while (true) {
            long cur = since.get();
            if (cur != 0 && now - cur < expireMs) return Verdict.SKIP_DUPLICATE;
            if (since.compareAndSet(cur, now)) return Verdict.START;
        }
    }

    /** A nightly run is starting or running. */
    boolean active(long now) {
        long cur = since.get();
        return cur != 0 && now - cur < expireMs;
    }

    /** The run ended (or never started): the next night may claim again. */
    void release() {
        since.set(0);
    }
}
