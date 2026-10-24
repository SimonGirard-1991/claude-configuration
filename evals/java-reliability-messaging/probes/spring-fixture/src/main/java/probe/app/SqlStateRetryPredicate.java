package probe.app;

import java.lang.reflect.Method;
import java.sql.SQLException;
import java.util.Set;
import org.springframework.resilience.retry.MethodRetryPredicate;

public class SqlStateRetryPredicate implements MethodRetryPredicate {

    private static final Set<String> RETRIED = Set.of("40001", "40P01");

    @Override
    public boolean shouldRetry(Method method, Throwable failure) {
        for (Throwable t = failure; t != null; t = t.getCause()) {
            if (t instanceof SQLException e) {
                return RETRIED.contains(e.getSQLState());
            }
        }
        return false;
    }
}
