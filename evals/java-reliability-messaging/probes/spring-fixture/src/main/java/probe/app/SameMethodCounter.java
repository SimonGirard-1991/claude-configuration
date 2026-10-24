package probe.app;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.resilience.annotation.Retryable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class SameMethodCounter {

    private final Attempts attempts = new Attempts();
    private final JdbcClient jdbc;

    public SameMethodCounter(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public Attempts attempts() {
        return attempts;
    }

    @Retryable(maxRetries = 2, delay = 50)
    @Transactional(isolation = Isolation.REPEATABLE_READ)
    public long increment(long id) {
        return CounterBody.readModifyWrite(jdbc, attempts, id);
    }
}
