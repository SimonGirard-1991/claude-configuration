package probe.overlap;

import java.util.concurrent.atomic.AtomicInteger;

public final class RunCounter {

    public static final AtomicInteger RUNS = new AtomicInteger();
    public static final AtomicInteger RUNNING = new AtomicInteger();
    public static final AtomicInteger MAX_RUNNING = new AtomicInteger();

    private RunCounter() {
    }

    public static void reset() {
        RUNS.set(0);
        RUNNING.set(0);
        MAX_RUNNING.set(0);
    }

    static void runFor(long millis) throws InterruptedException {
        RUNS.incrementAndGet();
        MAX_RUNNING.accumulateAndGet(RUNNING.incrementAndGet(), Math::max);
        try {
            Thread.sleep(millis);
        } finally {
            RUNNING.decrementAndGet();
        }
    }
}
