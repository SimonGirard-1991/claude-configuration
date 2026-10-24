package probe.app;

import org.springframework.dao.PessimisticLockingFailureException;
import org.springframework.resilience.annotation.Retryable;
import org.springframework.stereotype.Service;

@Service
public class RetryingCounter {

    private final CounterTransaction transaction;

    public RetryingCounter(CounterTransaction transaction) {
        this.transaction = transaction;
    }

    @Retryable(includes = PessimisticLockingFailureException.class, maxRetries = 2, delay = 50, jitter = 10)
    public long increment(long id) {
        return transaction.incrementOnce(id);
    }

    @Retryable(predicate = SqlStateRetryPredicate.class, maxRetries = 2, delay = 50, jitter = 10)
    public long incrementBySqlState(long id) {
        return transaction.incrementOnce(id);
    }
}
