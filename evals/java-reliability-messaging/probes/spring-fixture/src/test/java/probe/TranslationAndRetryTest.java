package probe;

import static probe.Facts.describe;
import static probe.Facts.fact;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;
import org.jooq.DSLContext;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import probe.app.ProbeApplication;
import probe.app.CallerTransaction;
import probe.app.CounterTransaction;
import probe.app.NowaitReader;
import probe.app.RetryingCounter;
import probe.app.SameMethodCounter;

@SpringBootTest(classes = ProbeApplication.class)
class TranslationAndRetryTest {

    @Autowired JdbcClient jdbc;
    @Autowired DSLContext dsl;
    @Autowired PlatformTransactionManager transactionManager;
    @Autowired SameMethodCounter sameMethod;
    @Autowired RetryingCounter retrying;
    @Autowired CounterTransaction counterTransaction;
    @Autowired CallerTransaction caller;
    @Autowired NowaitReader nowait;

    @BeforeEach
    void rows() {
        jdbc.sql("DELETE FROM counters").update();
        jdbc.sql("INSERT INTO counters VALUES (1, 0), (2, 0)").update();
    }

    private void concurrentIncrementCommitted() {
        CompletableFuture.runAsync(() -> jdbc.sql("UPDATE counters SET value = value + 100 WHERE id = 1").update()).join();
    }

    private TransactionTemplate tx(int isolation) {
        var template = new TransactionTemplate(transactionManager);
        template.setIsolationLevel(isolation);
        return template;
    }

    @Test
    void serializationFailureThroughJdbcClientAndJooq() {
        try {
            tx(TransactionDefinition.ISOLATION_REPEATABLE_READ).executeWithoutResult(s -> {
                jdbc.sql("SELECT value FROM counters WHERE id = 1").query(Long.class).single();
                concurrentIncrementCommitted();
                jdbc.sql("UPDATE counters SET value = 1 WHERE id = 1").update();
            });
            fact("40001-jdbcclient", "no exception");
        } catch (RuntimeException e) {
            fact("40001-jdbcclient", describe(e));
        }
        try {
            tx(TransactionDefinition.ISOLATION_REPEATABLE_READ).executeWithoutResult(s -> {
                dsl.fetchValue("SELECT value FROM counters WHERE id = 1");
                concurrentIncrementCommitted();
                dsl.execute("UPDATE counters SET value = 1 WHERE id = 1");
            });
            fact("40001-jooq", "no exception");
        } catch (RuntimeException e) {
            fact("40001-jooq", describe(e));
        }
    }

    private record AccessPath(String name, Consumer<String> select, Consumer<String> update) {
    }

    private List<AccessPath> paths() {
        return List.of(
                new AccessPath("jdbcclient", sql -> jdbc.sql(sql).query().listOfRows(), sql -> jdbc.sql(sql).update()),
                new AccessPath("jooq", sql -> dsl.fetch(sql), sql -> dsl.execute(sql)));
    }

    @Test
    void lockFailuresPerAccessPath() throws Exception {
        for (AccessPath path : paths()) {
            var held = new CountDownLatch(1);
            var release = new CountDownLatch(1);
            var holder = CompletableFuture.runAsync(() -> tx(TransactionDefinition.ISOLATION_READ_COMMITTED)
                    .executeWithoutResult(s -> {
                        jdbc.sql("SELECT id FROM counters WHERE id = 1 FOR UPDATE").query(Long.class).single();
                        held.countDown();
                        await(release);
                    }));
            held.await(10, TimeUnit.SECONDS);
            try {
                path.select().accept("SELECT id FROM counters WHERE id = 1 FOR UPDATE NOWAIT");
                fact("55P03-nowait " + path.name(), "no exception");
            } catch (RuntimeException e) {
                fact("55P03-nowait " + path.name(), describe(e));
            }
            try {
                tx(TransactionDefinition.ISOLATION_READ_COMMITTED).executeWithoutResult(s -> {
                    path.update().accept("SET LOCAL lock_timeout = '500ms'");
                    path.select().accept("SELECT id FROM counters WHERE id = 1 FOR UPDATE");
                });
                fact("55P03-lock_timeout " + path.name(), "no exception");
            } catch (RuntimeException e) {
                fact("55P03-lock_timeout " + path.name(), describe(e));
            }
            release.countDown();
            holder.join();

            var bothLocked = new CountDownLatch(2);
            Runnable first = () -> tx(TransactionDefinition.ISOLATION_READ_COMMITTED).executeWithoutResult(s -> {
                path.update().accept("UPDATE counters SET value = value + 1 WHERE id = 1");
                bothLocked.countDown();
                await(bothLocked);
                path.update().accept("UPDATE counters SET value = value + 1 WHERE id = 2");
            });
            Runnable second = () -> tx(TransactionDefinition.ISOLATION_READ_COMMITTED).executeWithoutResult(s -> {
                path.update().accept("UPDATE counters SET value = value + 1 WHERE id = 2");
                bothLocked.countDown();
                await(bothLocked);
                path.update().accept("UPDATE counters SET value = value + 1 WHERE id = 1");
            });
            var a = CompletableFuture.runAsync(first);
            var b = CompletableFuture.runAsync(second);
            for (var f : new CompletableFuture<?>[] {a, b}) {
                try {
                    f.join();
                } catch (RuntimeException e) {
                    fact("40P01-deadlock " + path.name(), describe(e.getCause() == null ? e : e.getCause()));
                }
            }
        }
    }

    @Test
    void retryableOnTheTransactionalMethodItself() {
        sameMethod.attempts().log.clear();
        sameMethod.attempts().afterFirstRead = this::concurrentIncrementCommitted;
        try {
            long value = sameMethod.increment(1);
            fact("retry-same-method", "returned " + value + "; " + sameMethod.attempts().log);
        } catch (RuntimeException e) {
            fact("retry-same-method", "failed with " + describe(e) + "; " + sameMethod.attempts().log);
        }
        long stored = jdbc.sql("SELECT value FROM counters WHERE id = 1").query(Long.class).single();
        fact("retry-same-method", "stored value " + stored + " (100 from the concurrent writer, +1 if a retry committed)");
    }

    @Test
    void retryableAroundASeparateTransactionalBean() {
        counterTransaction.attempts().log.clear();
        counterTransaction.attempts().afterFirstRead = this::concurrentIncrementCommitted;
        try {
            long value = retrying.increment(1);
            fact("retry-outer-bean", "returned " + value + "; " + counterTransaction.attempts().log);
        } catch (RuntimeException e) {
            fact("retry-outer-bean", "failed with " + describe(e) + "; " + counterTransaction.attempts().log);
        }
        long stored = jdbc.sql("SELECT value FROM counters WHERE id = 1").query(Long.class).single();
        fact("retry-outer-bean", "stored value " + stored);
    }

    @Test
    void retryableInsideACallersTransaction() {
        counterTransaction.attempts().log.clear();
        counterTransaction.attempts().afterFirstRead = this::concurrentIncrementCommitted;
        try {
            long value = caller.incrementInsideCallersTransaction(1);
            fact("retry-inside-caller-tx", "returned " + value + "; " + counterTransaction.attempts().log);
        } catch (RuntimeException e) {
            fact("retry-inside-caller-tx", "failed with " + describe(e) + "; " + counterTransaction.attempts().log);
        }
        long stored = jdbc.sql("SELECT value FROM counters WHERE id = 1").query(Long.class).single();
        fact("retry-inside-caller-tx", "stored value " + stored);
    }

    @Test
    void retryPredicateByTypeOrBySqlState() throws Exception {
        var held = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var holder = CompletableFuture.runAsync(() -> tx(TransactionDefinition.ISOLATION_READ_COMMITTED)
                .executeWithoutResult(s -> {
                    jdbc.sql("SELECT id FROM counters WHERE id = 1 FOR UPDATE").query(Long.class).single();
                    held.countDown();
                    await(release);
                }));
        held.await(10, TimeUnit.SECONDS);
        for (boolean bySqlState : new boolean[] {false, true}) {
            nowait.attempts().set(0);
            String outcome;
            try {
                if (bySqlState) {
                    nowait.lockBySqlState(1);
                } else {
                    nowait.lockByType(1);
                }
                outcome = "no exception";
            } catch (RuntimeException e) {
                outcome = e.getClass().getSimpleName();
            }
            fact("retry-nowait-jooq " + (bySqlState ? "predicate 40001/40P01" : "includes PessimisticLockingFailureException"),
                    nowait.attempts().get() + " attempt(s), then " + outcome);
        }
        release.countDown();
        holder.join();
        counterTransaction.attempts().log.clear();
        counterTransaction.attempts().afterFirstRead = this::concurrentIncrementCommitted;
        try {
            long value = retrying.incrementBySqlState(1);
            fact("retry-40001 predicate 40001/40P01", "returned " + value + "; " + counterTransaction.attempts().log);
        } catch (RuntimeException e) {
            fact("retry-40001 predicate 40001/40P01", "failed with " + describe(e) + "; " + counterTransaction.attempts().log);
        }
    }

    private static void await(CountDownLatch latch) {
        try {
            latch.await(10, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
