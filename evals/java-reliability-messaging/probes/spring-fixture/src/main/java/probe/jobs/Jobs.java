package probe.jobs;

import java.time.OffsetDateTime;
import net.javacrumbs.shedlock.spring.annotation.SchedulerLock;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class Jobs {

    private final JdbcClient jdbc;
    private final String instance;

    public Jobs(JdbcClient jdbc, @Value("${instance}") String instance) {
        this.jdbc = jdbc;
        this.instance = instance;
    }

    @Scheduled(cron = "*/2 * * * * *")
    public void unlocked() throws InterruptedException {
        run("unlocked", 200);
    }

    @Scheduled(cron = "*/2 * * * * *")
    @SchedulerLock(name = "locked", lockAtLeastFor = "PT1S")
    public void locked() throws InterruptedException {
        run("locked", 200);
    }

    @Scheduled(cron = "*/2 * * * * *")
    @SchedulerLock(name = "outlives-its-lock", lockAtMostFor = "PT1S")
    public void outlivesItsLock() throws InterruptedException {
        run("outlives-its-lock", 3000);
    }

    private void run(String job, long millis) throws InterruptedException {
        long id = jdbc.sql("INSERT INTO job_runs (job, instance, started_at) VALUES (:job, :instance, now()) RETURNING id")
                .param("job", job).param("instance", instance).query(Long.class).single();
        Thread.sleep(millis);
        jdbc.sql("UPDATE job_runs SET finished_at = now() WHERE id = :id").param("id", id).update();
    }
}
