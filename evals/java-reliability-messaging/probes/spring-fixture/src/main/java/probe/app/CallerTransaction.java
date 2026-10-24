package probe.app;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CallerTransaction {

    private final RetryingCounter retrying;

    public CallerTransaction(RetryingCounter retrying) {
        this.retrying = retrying;
    }

    @Transactional(isolation = Isolation.REPEATABLE_READ)
    public long incrementInsideCallersTransaction(long id) {
        return retrying.increment(id);
    }
}
