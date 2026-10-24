package probe;

import static probe.Facts.fact;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicInteger;
import javax.sql.DataSource;
import net.javacrumbs.shedlock.core.ClockProvider;
import net.javacrumbs.shedlock.core.DefaultLockingTaskExecutor;
import net.javacrumbs.shedlock.core.LockConfiguration;
import net.javacrumbs.shedlock.provider.jdbctemplate.JdbcTemplateLockProvider;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import probe.jobs.JobsApplication;

class ShedLockTest {

    private final DataSource dataSource = new DriverManagerDataSource(
            System.getenv().getOrDefault("PROBE_JDBC_URL", "jdbc:postgresql://localhost:55432/probe_java"),
            System.getenv().getOrDefault("PROBE_JDBC_USER", "postgres"), "");
    private final JdbcClient jdbc = JdbcClient.create(dataSource);

    @AfterEach
    void resetClock() {
        ClockProvider.setClock(Clock.systemUTC());
    }

    private JdbcTemplateLockProvider provider(boolean dbTime) {
        var builder = JdbcTemplateLockProvider.Configuration.builder().withJdbcTemplate(new JdbcTemplate(dataSource));
        return new JdbcTemplateLockProvider(dbTime ? builder.usingDbTime().build() : builder.build());
    }

    @Test
    void twoInstancesOfTheScheduledJobs() throws Exception {
        jdbc.sql("DELETE FROM job_runs").update();
        jdbc.sql("DELETE FROM shedlock").update();
        ConfigurableApplicationContext a = start("A");
        ConfigurableApplicationContext b = start("B");
        Thread.sleep(7_500);
        a.close();
        b.close();
        for (String job : new String[] {"unlocked", "locked"}) {
            var perTick = jdbc.sql("""
                    SELECT string_agg(instance, '+' ORDER BY instance) FROM job_runs WHERE job = :job
                    GROUP BY date_trunc('second', started_at) ORDER BY min(started_at)""")
                    .param("job", job).query(String.class).list();
            fact("two-instances " + job, "runs per tick: " + perTick);
        }
        var overlaps = jdbc.sql("""
                SELECT count(*) FROM job_runs x JOIN job_runs y
                  ON x.job = y.job AND x.id < y.id AND y.started_at < coalesce(x.finished_at, 'infinity')
                WHERE x.job = 'outlives-its-lock'""").query(Long.class).single();
        var runs = jdbc.sql("SELECT string_agg(instance || ' ' || to_char(started_at, 'SS.MS') || '-' || coalesce(to_char(finished_at, 'SS.MS'), 'running'), ', ' ORDER BY started_at) FROM job_runs WHERE job = 'outlives-its-lock'")
                .query(String.class).single();
        fact("lockAtMostFor 1s, run 3s", "overlapping pairs: " + overlaps + "; runs: " + runs);
    }

    private ConfigurableApplicationContext start(String instance) {
        return new SpringApplicationBuilder(JobsApplication.class)
                .web(WebApplicationType.NONE)
                .properties("instance=" + instance, "spring.task.scheduling.pool.size=4",
                        "spring.datasource.url=" + System.getenv().getOrDefault("PROBE_JDBC_URL",
                                "jdbc:postgresql://localhost:55432/probe_java"),
                        "spring.datasource.username=" + System.getenv().getOrDefault("PROBE_JDBC_USER", "postgres"),
                        "logging.level.root=WARN", "spring.main.banner-mode=off")
                .run();
    }

    @Test
    void clockSkewWithAndWithoutDatabaseTime() {
        for (boolean dbTime : new boolean[] {false, true}) {
            jdbc.sql("DELETE FROM shedlock").update();
            ClockProvider.setClock(Clock.systemUTC());
            var lockA = provider(dbTime).lock(new LockConfiguration(ClockProvider.now(), "skew", Duration.ofMinutes(10), Duration.ZERO));
            ClockProvider.setClock(Clock.offset(Clock.systemUTC(), Duration.ofMinutes(11)));
            var lockB = provider(dbTime).lock(new LockConfiguration(ClockProvider.now(), "skew", Duration.ofMinutes(10), Duration.ZERO));
            fact("skew usingDbTime=" + dbTime, "A acquired " + lockA.isPresent()
                    + "; B, with a clock 11 min ahead, acquired " + lockB.isPresent() + " while A still held it");
        }
    }

    @Test
    void lockAtLeastForAgainstAnOffsetTrigger() throws Exception {
        for (Duration atLeast : new Duration[] {Duration.ZERO, Duration.ofSeconds(5)}) {
            jdbc.sql("DELETE FROM shedlock").update();
            var runs = new AtomicInteger();
            var executorA = new DefaultLockingTaskExecutor(provider(true));
            var executorB = new DefaultLockingTaskExecutor(provider(true));
            executorA.executeWithLock((Runnable) runs::incrementAndGet,
                    new LockConfiguration(Instant.now(), "short-job", Duration.ofMinutes(1), atLeast));
            Thread.sleep(500);
            executorB.executeWithLock((Runnable) runs::incrementAndGet,
                    new LockConfiguration(Instant.now(), "short-job", Duration.ofMinutes(1), atLeast));
            fact("lockAtLeastFor=" + atLeast, "a 0 ms job triggered on B 500 ms after A ran " + runs.get() + " time(s)");
        }
    }
}
