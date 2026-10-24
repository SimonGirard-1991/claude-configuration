package probe.app;

import java.sql.SQLException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.support.TransactionSynchronizationManager;

final class CounterBody {

    private CounterBody() {
    }

    static long readModifyWrite(JdbcClient jdbc, Attempts attempts, long id) {
        String tx = TransactionSynchronizationManager.isActualTransactionActive() ? "in a transaction" : "no transaction";
        try {
            long value = jdbc.sql("SELECT value FROM counters WHERE id = :id").param("id", id).query(Long.class).single();
            String xid = jdbc.sql("SELECT pg_current_xact_id()::text").query(String.class).single();
            attempts.runHookOnce();
            jdbc.sql("UPDATE counters SET value = :value WHERE id = :id").param("value", value + 1).param("id", id).update();
            attempts.log.add("attempt %d %s xid %s: ok".formatted(attempts.log.size() + 1, tx, xid));
            return value + 1;
        } catch (RuntimeException e) {
            attempts.log.add("attempt %d %s: %s (%s)".formatted(attempts.log.size() + 1, tx,
                    e.getClass().getSimpleName(), sqlState(e)));
            throw e;
        }
    }

    static String sqlState(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t instanceof SQLException s) {
                return "SQLSTATE " + s.getSQLState();
            }
        }
        return "no SQLSTATE";
    }
}
