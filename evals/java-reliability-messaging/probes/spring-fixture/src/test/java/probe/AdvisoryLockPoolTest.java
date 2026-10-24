package probe;

import static probe.Facts.fact;

import com.zaxxer.hikari.HikariDataSource;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.concurrent.CompletableFuture;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;

class AdvisoryLockPoolTest {

    private static final String URL = System.getenv().getOrDefault("PROBE_JDBC_URL", "jdbc:postgresql://localhost:55432/probe_java");
    private static final String USER = System.getenv().getOrDefault("PROBE_JDBC_USER", "postgres");

    @Test
    void sessionLockFollowsThePooledConnection() {
        try (var pool = new HikariDataSource()) {
            pool.setJdbcUrl(URL);
            pool.setUsername(USER);
            pool.setMaximumPoolSize(1);
            var pooled = JdbcClient.create(pool);
            var outside = JdbcClient.create(new DriverManagerDataSource(URL, USER, ""));
            boolean jobA = CompletableFuture.supplyAsync(() -> pooled.sql("SELECT pg_try_advisory_lock(4242)").query(Boolean.class).single()).join();
            boolean jobB = CompletableFuture.supplyAsync(() -> pooled.sql("SELECT pg_try_advisory_lock(4242)").query(Boolean.class).single()).join();
            boolean other = outside.sql("SELECT pg_try_advisory_lock(4242)").query(Boolean.class).single();
            fact("session-lock-through-pool", "job A acquired " + jobA + ", job B on the same pooled connection acquired "
                    + jobB + ", a separate connection acquired " + other);
            var tx = new TransactionTemplate(new DataSourceTransactionManager(pool));
            pooled.sql("SELECT pg_advisory_unlock_all()").query(String.class).optional();
            boolean inTx = tx.execute(s -> pooled.sql("SELECT pg_try_advisory_xact_lock(4243)").query(Boolean.class).single());
            boolean afterCommit = outside.sql("SELECT pg_try_advisory_xact_lock(4243)").query(Boolean.class).single();
            fact("xact-lock-through-pool", "acquired in a transaction " + inTx + ", free for another connection after commit "
                    + afterCommit);
        }
    }

    @Test
    void sessionLockOnOneHeldConnectionAcrossBatches() throws Exception {
        try (var pool = new HikariDataSource()) {
            pool.setJdbcUrl(URL);
            pool.setUsername(USER);
            pool.setMaximumPoolSize(3);
            var batches = JdbcClient.create(pool);
            var otherInstance = JdbcClient.create(new DriverManagerDataSource(URL, USER, ""));
            try (Connection held = pool.getConnection(); Statement lock = held.createStatement()) {
                boolean acquired = query(lock, "SELECT pg_try_advisory_lock(4244)");
                for (int batch = 0; batch < 3; batch++) {
                    batches.sql("SELECT pg_backend_pid()").query(Integer.class).single();
                }
                boolean otherDuring = otherInstance.sql("SELECT pg_try_advisory_lock(4244)").query(Boolean.class).single();
                boolean released = query(lock, "SELECT pg_advisory_unlock(4244)");
                boolean otherAfter = otherInstance.sql("SELECT pg_try_advisory_lock(4244)").query(Boolean.class).single();
                fact("session-lock-on-held-connection", "acquired " + acquired + ", another instance during three batches on other pooled connections "
                        + otherDuring + ", unlocked on the held connection " + released + ", another instance after " + otherAfter);
            }
        }
    }

    private static boolean query(Statement statement, String sql) throws SQLException {
        try (ResultSet rs = statement.executeQuery(sql)) {
            rs.next();
            return rs.getBoolean(1);
        }
    }
}
