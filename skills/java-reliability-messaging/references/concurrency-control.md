# Concurrency control

How to keep concurrent writers from losing each other's changes: one conditional statement,
a row lock, a version check, a stricter isolation level or an advisory lock, chosen by the
conflict. The facts were checked on 2026-10-24 on PostgreSQL 18.6, Spring Boot 4.1.2 (Spring
Framework 7.0.10, Spring Data JDBC 4.1.2, HikariCP 7.0.2), jOOQ 3.21.9 and PgBouncer 1.26.1.
Each case cited here ran there, and the rest comes from the documentation below. A time in
ms or s is one measurement on a laptop container. The rules come from the PostgreSQL 18
manual:
[transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html),
[explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html),
[the locking clause](https://www.postgresql.org/docs/18/sql-select.html#SQL-FOR-UPDATE-SHARE),
[serialization failures](https://www.postgresql.org/docs/18/mvcc-serialization-failure-handling.html).
They also come from [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110) § 8.8 and § 13.1.1,
[RFC 6585](https://www.rfc-editor.org/rfc/rfc6585) § 3,
[Spring's resilience features](https://docs.spring.io/spring-framework/reference/core/resilience.html),
[jOOQ's optimistic locking](https://www.jooq.org/doc/3.21/manual/sql-execution/crud-with-updatablerecords/optimistic-locking)
and [PgBouncer's feature table](https://www.pgbouncer.org/features.html).
`~/.claude/evals/java-reliability-messaging/probes/concurrency.sh` reruns the PostgreSQL
cases, named A1 to E4 below, and `spring-fixture.sh` beside it the Spring and jOOQ ones.

## Contents

- Choose by the conflict
- Read-modify-write and isolation
- Row locks
- Optimistic locking
- Retrying a transaction
- If-Match and ETag
- Advisory locks

## Choose by the conflict

Five things decide it: how often writers meet on the same row, how long the transaction
runs, what a retry costs, whether a person must see the conflict, and how many instances
write. No form is wrong in itself.

| Situation | Default |
|---|---|
| The new value can be computed in SQL: a counter, a remaining quantity | One conditional `UPDATE` that computes it, and a check of the row count |
| A decision in Java between the read and the write, on a contended row, in a short transaction | Lock the row, then write (§ Row locks) |
| Rare conflicts, or a transaction that must not hold a lock across a remote call | A version column and `UPDATE ... WHERE version = :read` (§ Optimistic locking) |
| A person edited a copy, and only they can merge their change | Their version, sent back in `If-Match`; a conflict answers 412 and is never retried |
| The server can redo the decision from fresh data | A bounded retry of the whole transaction (§ Retrying a transaction) |
| An invariant across rows: one person always on duty, a sum under a limit | `SERIALIZABLE` with a retry, or a lock on one row that stands for the invariant |
| Work no row stands for: a job, an import per tenant | An advisory lock (§ Advisory locks) |

- A row lock suits a hot row whose transactions are short: writers queue for a moment each.
  An optimistic writer that loses redoes its whole transaction, so on a row many writers
  update at once the conditional `UPDATE` or the lock fits better. A lock held across a
  remote call, a person's think time or a long transaction makes every writer of the row
  wait for all of it.
- One instance does not remove the race: two requests, two threads or two browser tabs still
  write the same row.

## Read-modify-write and isolation

PostgreSQL defaults to `READ COMMITTED`. In C1 to C10, session A read `quotas.remaining` =
10 and wrote while B was open. B read before A's write, and its write waited for A's
uncommitted one; in the locking-read row, B's read itself waited for A's commit:

| B's form | READ COMMITTED | REPEATABLE READ |
|---|---|---|
| `SELECT`, then `UPDATE ... SET remaining = :computed` | 9: B waited 4.2 s for A's commit, then overwrote it | B failed with `40001` |
| `UPDATE ... SET remaining = remaining - 1 WHERE id = 1 AND remaining >= 1` | 8 | B failed with `40001` |
| `SELECT ... FOR UPDATE`, or `FOR NO KEY UPDATE` (C9, C10), then the computed write | 8: B's read waited about 8 s for A's commit and returned A's 9 | B's read waited, then failed with `40001` |
| `SELECT` with the version, then `UPDATE ... WHERE version = :read` | B updated 0 rows | B failed with `40001` |

- Under `READ COMMITTED`, an `UPDATE` that waited for another writer re-checks its `WHERE`
  against the newest row. A condition in the statement therefore holds, and a value Java
  computed from an earlier read does not: that is the lost update.
- `REPEATABLE READ` turns the lost update into an error. A writer that finds its row changed
  since its snapshot fails with "could not serialize access due to concurrent update"
  (SQLSTATE `40001`), whatever form it used. Every writing transaction at that level needs a
  retry. A version check there fails with `40001` instead of updating 0 rows when the other
  write committed after its snapshot (C8), so both mean a conflict.
- `REPEATABLE READ` lets write skew through. Two doctors each counted two on duty and went
  off duty: both committed, and nobody was left (D1). Under `SERIALIZABLE` one failed with
  "could not serialize access due to read/write dependencies among transactions" (D2).
  `SERIALIZABLE` blocks no more than `REPEATABLE READ`, but any of its transactions can fail
  with `40001`, so all of them run under the retry. The manual adds that a long read-only
  report runs as `SERIALIZABLE READ ONLY DEFERRABLE`, which cannot fail that way.

## Row locks

| Lock | Also taken by | Conflicts with |
|---|---|---|
| `FOR KEY SHARE` | the foreign key check of an inserted referencing row (A6) | `FOR UPDATE` |
| `FOR SHARE` | | `FOR NO KEY UPDATE`, `FOR UPDATE` |
| `FOR NO KEY UPDATE` | an `UPDATE` that changes no key column (A7) | `FOR SHARE`, `FOR NO KEY UPDATE`, `FOR UPDATE` |
| `FOR UPDATE` | `DELETE`, and an `UPDATE` of a column with a unique index a foreign key can use | all four |

- `SELECT ... FOR UPDATE` on a parent row blocked an insert of a child that references it
  (A1), for as long as the transaction lasts. `FOR NO KEY UPDATE` let the insert through
  (A2), and so did a plain `UPDATE` of a non-key column (A3). An uncommitted child insert
  blocked `FOR UPDATE` on its parent (A4) and not `FOR NO KEY UPDATE` (A5). A transaction
  that locks a row to change non-key columns takes `FOR NO KEY UPDATE`, and `FOR UPDATE` is
  for a delete or a key change.
- A lock waits as long as its holder's transaction unless `lock_timeout` is set: with
  `lock_timeout` at 1 s, the blocked insert failed after 1 s (A1). DDL's locks and
  `lock_timeout` are in `java-schema-migrations`.
- Two transactions that lock the same rows in opposite orders deadlock, and PostgreSQL
  aborts one with `40P01`. Locking in one order, such as `ORDER BY id`, avoids it.
- `NOWAIT` failed at once with "could not obtain lock on row" (SQLSTATE `55P03`, B2), and a
  `lock_timeout` cancellation carries the same SQLSTATE. What Spring makes of it depends on
  the access path (§ Retrying a transaction).
- `SKIP LOCKED` claims work from a queue-like table. A claim of two items passed over the
  locked one and returned 2 and 3 (B1), and two concurrent claims by `UPDATE ... WHERE id IN
  (SELECT ... FOR UPDATE SKIP LOCKED)` took disjoint items (B4). Under `REPEATABLE READ`,
  the same claim from a snapshot older than another session's committed claim failed with
  `40001` (B5), so a claim runs at `READ COMMITTED` or under the retry. It never feeds a
  decision: a count of five pending items through it returned 4 (B3). `outbox.md`'s relay
  locks its batch with `SELECT ... FOR UPDATE SKIP LOCKED` inside one transaction.
- The closed-period checkpoint that postings read `FOR SHARE` is in
  `java-financial-correctness`'s ledgers reference.

## Optimistic locking

- The version column, the `UPDATE ... WHERE id = ? AND version = ?` that bumps it, and
  `ConcurrentAggregateModificationException` on 0 rows are `hexagonal-module-bootstrap`'s
  templates: `aggregate.md`, `db-adapter-jooq.md`, and `db-adapter-jpa.md` for JPA's
  `@Version`.
- The version checked is the one the decision was made on. For an HTTP update that is the
  client's, from `If-Match`. A version read again in the same request passes the check over
  a change the client never saw.
- jOOQ's `UpdatableRecord.store()` checks a version only when the code generator's
  `<recordVersionFields>` names the column and
  `Settings.withExecuteWithOptimisticLocking(true)` is set. Then `store()` ran `update ...
  where (id = ? and version = ?)`, and a stale record threw
  `org.jooq.exception.DataChangedException`, which Spring Boot's jOOQ exception translation
  left as it was. With the setting at its default, false, a stale `store()` overwrote the
  other write and wrote version 1 again, the version the other write had already set, so a
  client holding version 1 passes a check over a change it never saw.
- Spring Data JDBC's `@Version` (`org.springframework.data.annotation.Version`) threw
  `OptimisticLockingFailureException` on a stale `save`.

## Retrying a transaction

- PostgreSQL retries nothing itself. Its manual says to retry the whole transaction,
  including the logic that decided what to write, on `40001`, and advises it on `40P01`. A
  `23505` is retried only when the transaction chose a key from what it read, since it can
  also be a lasting error.
- Spring Framework 7.0.10 translates by access path:

  | SQLSTATE | Spring Boot's jOOQ | `JdbcClient` |
  |---|---|---|
  | `40001` | `CannotSerializeTransactionException` | `CannotAcquireLockException` |
  | `40P01` | `DeadlockLoserDataAccessException` | `PessimisticLockingFailureException` |
  | `55P03`, from `NOWAIT` or `lock_timeout` | `CannotAcquireLockException` | `UncategorizedSQLException` |

  Every one but `JdbcClient`'s `55P03` is a `PessimisticLockingFailureException`. A retry on
  that type therefore also retries a `NOWAIT` or a lock timeout through jOOQ: a `NOWAIT`
  read ran 3 times under `maxRetries = 2`. A retry that must let those fail fast matches the
  SQLSTATE instead, with `@Retryable`'s `predicate`: one on `40001` and `40P01` ran the
  `NOWAIT` read once, and still retried a `40001` into a new transaction that committed. A
  match on `ConcurrencyFailureException` also retries `OptimisticLockingFailureException`, a
  conflict that may be the user's to resolve.
- The retry wraps the transaction. Spring Framework 7's `@Retryable`
  (`org.springframework.resilience.annotation`, enabled by `@EnableResilientMethods`) did so
  on the same method as `@Transactional`: attempt 1 failed with `40001`, and attempt 2 ran
  in a new transaction and committed. A `@Retryable` method that calls a `@Transactional`
  method of another bean gave the same result, and shows the order in the code.
  `RetryTemplate` (`org.springframework.core.retry`) is the programmatic form.
- The retry sits outside the outermost transaction. Called inside a caller's transaction,
  the `@Transactional` method joined it, and attempt 2 ran on the aborted transaction and
  failed with `25P02` ("current transaction is aborted"), an `UncategorizedSQLException` the
  retry did not match.
- `@Retryable` alone retries any exception three times, one second apart. A transaction
  retry sets `includes` or a `predicate`, a small `maxRetries` and a delay with jitter
  (`retries-and-dlq.md`). That reference shows the older Spring Retry project's
  `@Retryable`, now archived in favour of these features: its `maxAttempts` counts the first
  call, where `maxRetries` does not.
- A retried transaction repeats its side effects. A call to another system inside it needs
  an idempotency key or an outbox (`transactions-and-idempotency.md`).
- A conflict on the client's version is never retried: the retry would apply the client's
  change over one they never saw.

## If-Match and ETag

- A versioned resource's `ETag` is its version as a strong tag: Spring's
  `ResponseEntity.ok().eTag("7")` sent `ETag: "7"`. That is a strong validator only while
  every change to what `GET` returns changes the version (RFC 9110 § 8.8.1). A
  representation that also shows data the version does not cover needs another tag.
- A `PUT`, `PATCH` or `DELETE` on it requires `If-Match`. Without the header the server
  answers 428 Precondition Required, which RFC 6585 § 3 defines for the lost update. With a
  tag that is not current it answers 412 Precondition Failed and does not apply the method
  (RFC 9110 § 13.1.1).
- `If-Match` uses the strong comparison, so `W/"7"` never matches (RFC 9110 § 8.8.3.2).
  `If-Match: *` matches any current representation, so it checks existence, not the version.
- The version from `If-Match` goes into the conditional `UPDATE`, and 0 rows answers 412.
  Comparing it with a fresh read and then updating with the fresh version leaves a gap
  between the two statements.
- Spring MVC's `WebRequest.checkNotModified(etag)` on a `PUT` answered 412 to `"6"` and to
  `W/"7"`, and let `"7"`, `*` and `"6", "7"` through. It also let a request without
  `If-Match` through, so the 428 is the controller's.
- 412 reports a failed precondition. `hexagonal-module-bootstrap`'s `rest-adapter.md` maps
  `ConcurrentAggregateModificationException` to 409 for a conflict found without one; behind
  `If-Match`, 0 rows from the conditional `UPDATE` is the precondition failing. The
  operation's OpenAPI spec declares 412 and 428, as `rest-adapter.md` requires for every
  status a handler produces.

## Advisory locks

- An advisory lock locks a number the application picks, not a row: a key for a job or a
  tenant's import, for work no single row stands for.
- A session lock (`pg_advisory_lock`, `pg_try_advisory_lock`) lasts until
  `pg_advisory_unlock` or the end of the session, and ignores rollback: taken in a
  transaction that rolled back, it was still held (E1). A transaction lock
  (`pg_advisory_xact_lock`, `pg_try_advisory_xact_lock`) ends with its transaction (E2) and
  has no unlock.
- A session lock belongs to the database connection, and its holder can always take it
  again. Through HikariCP, a lock left on a pooled connection was acquired again by the next
  job that borrowed that connection, while a separate connection was refused.
- PgBouncer's transaction pooling does not support session locks ("Never" in its feature
  table). The lock outlived the client that took it, held by the server connection, and the
  next client on that connection acquired it too (E3). Transaction locks worked through it
  (E4).
- Through HikariCP, a job takes `pg_try_advisory_xact_lock` inside its own transaction, or
  holds one connection for its whole run and unlocks on it in a `finally`. A skipped unlock
  leaves the lock on a pooled connection until the pool closes it, and any job that borrows
  that connection takes it again. Behind PgBouncer's transaction pooling only the
  transaction lock works. Flyway's own advisory lock is in `java-schema-migrations`.
