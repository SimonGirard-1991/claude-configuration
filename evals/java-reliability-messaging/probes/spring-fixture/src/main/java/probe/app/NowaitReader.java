package probe.app;

import java.util.concurrent.atomic.AtomicInteger;
import org.jooq.DSLContext;
import org.springframework.dao.PessimisticLockingFailureException;
import org.springframework.resilience.annotation.Retryable;
import org.springframework.stereotype.Service;

@Service
public class NowaitReader {

    private final DSLContext dsl;
    private final AtomicInteger attempts = new AtomicInteger();

    public NowaitReader(DSLContext dsl) {
        this.dsl = dsl;
    }

    public AtomicInteger attempts() {
        return attempts;
    }

    @Retryable(includes = PessimisticLockingFailureException.class, maxRetries = 2, delay = 10)
    public void lockByType(long id) {
        attempts.incrementAndGet();
        dsl.fetch("SELECT id FROM counters WHERE id = ? FOR UPDATE NOWAIT", id);
    }

    @Retryable(predicate = SqlStateRetryPredicate.class, maxRetries = 2, delay = 10)
    public void lockBySqlState(long id) {
        attempts.incrementAndGet();
        dsl.fetch("SELECT id FROM counters WHERE id = ? FOR UPDATE NOWAIT", id);
    }
}
