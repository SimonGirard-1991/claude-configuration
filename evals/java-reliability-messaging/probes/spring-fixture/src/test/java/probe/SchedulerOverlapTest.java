package probe;

import static probe.Facts.fact;

import org.junit.jupiter.api.Test;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.scheduling.TaskScheduler;
import probe.overlap.OverlapApplication;
import probe.overlap.RunCounter;

class SchedulerOverlapTest {

    @Test
    void oneInstanceOverlapsItselfOnVirtualThreads() throws Exception {
        for (String job : new String[] {"cron", "fixed-rate", "fixed-delay"}) {
            for (boolean virtual : new boolean[] {true, false}) {
                RunCounter.reset();
                var context = new SpringApplicationBuilder(OverlapApplication.class)
                        .web(WebApplicationType.NONE)
                        .properties("probe.overlap.job=" + job, "spring.threads.virtual.enabled=" + virtual,
                                "spring.datasource.url=" + System.getenv().getOrDefault("PROBE_JDBC_URL",
                                        "jdbc:postgresql://localhost:55432/probe_java"),
                                "spring.datasource.username=" + System.getenv().getOrDefault("PROBE_JDBC_USER", "postgres"),
                                "logging.level.root=WARN", "spring.main.banner-mode=off")
                        .run();
                String scheduler = context.getBean(TaskScheduler.class).getClass().getSimpleName();
                Thread.sleep(6_500);
                context.close();
                int runs = RunCounter.RUNS.get();
                int maxRunning = RunCounter.MAX_RUNNING.get();
                for (int polls = 0; RunCounter.RUNNING.get() > 0 && polls < 100; polls++) {
                    Thread.sleep(50);
                }
                if (RunCounter.RUNNING.get() > 0) {
                    throw new IllegalStateException(RunCounter.RUNNING.get() + " " + job
                            + " runs still in flight 5 s after close; the next case's counts would be wrong");
                }
                String cadence = job.equals("fixed-delay") ? " job with a 1 s delay" : " job due every second";
                fact("one-instance-overlap " + job + " virtual=" + virtual, scheduler + ": a 2.5 s " + job + cadence
                        + " ran " + runs + " times in 6.5 s, at most " + maxRunning + " at once");
            }
        }
    }
}
