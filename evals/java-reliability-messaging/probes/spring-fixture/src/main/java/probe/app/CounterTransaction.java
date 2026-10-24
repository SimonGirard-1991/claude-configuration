package probe.app;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CounterTransaction {

    private final Attempts attempts = new Attempts();
    private final JdbcClient jdbc;

    public CounterTransaction(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public Attempts attempts() {
        return attempts;
    }

    @Transactional(isolation = Isolation.REPEATABLE_READ)
    public long incrementOnce(long id) {
        return CounterBody.readModifyWrite(jdbc, attempts, id);
    }
}
