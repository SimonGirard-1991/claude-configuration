# Online schema changes

How to judge a PostgreSQL schema change by its context, and the online form of each change
when the context needs one. The facts were checked on 2026-10-23 and 2026-10-24 on
PostgreSQL 18.6, and each statement here ran there. A time in ms or s is one measurement on
a laptop container, not a guarantee. The guarantees come from the PostgreSQL 18 manual:
[explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html),
[ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html),
[CREATE INDEX](https://www.postgresql.org/docs/18/sql-createindex.html),
[pg_index](https://www.postgresql.org/docs/18/catalog-pg-index.html) and
[lock_timeout](https://www.postgresql.org/docs/18/runtime-config-client.html).
`~/.claude/evals/java-schema-migrations/probes/lock-and-visibility.sh` reruns the
concurrent build's waits and the plain build's lock lifetime. The earlier experiments'
scripts were not kept.

## Contents

- Judge the change by its context
- Locks and rewrites per statement
- The lock queue and lock_timeout
- Indexes
- NOT NULL and CHECK constraints
- Foreign keys
- Backfills
- Expand and contract

## Judge the change by its context

A migration's lock is a risk when, held until its transaction commits, it stops traffic the
service must serve. That is one risk among others: code the previous release cannot run
against (§ Expand and contract), a non-transactional migration that fails halfway
(`flyway-mechanics.md` § A failed migration and repair), and a step that outlasts the
application's startup (§ Indexes). Four things decide what the lock costs:

1. **The operation:** the lock it takes, and whether it scans or rewrites the table.
2. **The table:** its size, which sets how long the lock is held, and its read and write
   rate, which sets how much traffic waits behind it.
3. **The deployment:** one instance stopped in a maintenance window, so nothing touches the
   table during the change, or a rolling deploy, where the previous release keeps serving
   while Flyway migrates.
4. **The availability the tier requires:** how long a blocked write may wait before it
   counts against the target.

- The direct form is right when nothing uses the table during the change, or when the table
  is small enough for the lock to last milliseconds. A plain `CREATE INDEX` on 5,000 rows
  took 2 ms here. On 10 million narrow rows it took 1.4 s, and an insert waited 0.8 s
  behind it. A production table is wider and its disk busier, so time a production-sized
  copy before relying on such a figure.
- The online form is right when a large or busy table keeps taking traffic during the
  migration, and the tier cannot absorb the blocked writes for the change's duration.
- So a migration without `CONCURRENTLY` or `NOT VALID` is not a defect in itself. In
  review it is a finding only when the context the repo states, in a README, an ADR or the
  deploy configuration, makes its lock an outage. When the repo states no context, the
  review asks for it instead of assuming either way. A reviewer that cannot ask reports
  the finding conditionally, naming the context in which the lock is an outage.
- The online forms cost more migrations, more releases and more ways to fail halfway, so
  each one needs that reason.

## Locks and rewrites per statement

Each row was measured inside a transaction, with `pg_locks` for the lock and the table's
file node for a rewrite. ACCESS EXCLUSIVE blocks reads and writes. SHARE and SHARE ROW
EXCLUSIVE block writes. SHARE UPDATE EXCLUSIVE blocks neither, only other DDL, `VACUUM`
and `ANALYZE` on the table.

| Statement | Lock | Work done under it |
|---|---|---|
| `ADD COLUMN`, nullable or with a constant default, `NOT NULL` included | ACCESS EXCLUSIVE | Catalog only |
| `ADD COLUMN` with a volatile default such as `clock_timestamp()`, a stored generated column or an identity column | ACCESS EXCLUSIVE | Rewrites the table and its indexes |
| `ADD COLUMN … GENERATED ALWAYS AS (…)`, virtual by default in 18 | ACCESS EXCLUSIVE | Catalog only |
| `ALTER COLUMN TYPE` to a longer `varchar(n)`, or from `varchar` to `text` | ACCESS EXCLUSIVE | Catalog only: the table and its index kept their files |
| `ALTER COLUMN TYPE` to another collation, such as `text COLLATE "C"` | ACCESS EXCLUSIVE | Rebuilds the column's indexes, not the table |
| `ALTER COLUMN TYPE` otherwise: `int` to `bigint`, a shorter `varchar(n)`, `text` to `varchar(n)` | ACCESS EXCLUSIVE | Rewrites the table and its indexes |
| `SET NOT NULL` | ACCESS EXCLUSIVE | Scans the table, unless a valid `CHECK` proves it |
| `ADD CONSTRAINT` with a `CHECK` or a not-null constraint | ACCESS EXCLUSIVE | Scans the table |
| The same, `NOT VALID` | ACCESS EXCLUSIVE | Catalog only |
| `VALIDATE CONSTRAINT` | SHARE UPDATE EXCLUSIVE | Scans the table |
| `ADD FOREIGN KEY` | SHARE ROW EXCLUSIVE on both tables | Scans the referencing table |
| `ADD FOREIGN KEY … NOT VALID` | SHARE ROW EXCLUSIVE on both tables | Catalog only |
| `CREATE TABLE` with a foreign key to an existing table | SHARE ROW EXCLUSIVE on the referenced table | Catalog only |
| `CREATE INDEX` | SHARE | Builds the index in one scan |
| `CREATE INDEX CONCURRENTLY` | SHARE UPDATE EXCLUSIVE | Builds the index in two scans |
| `ADD CONSTRAINT … UNIQUE` or `PRIMARY KEY` | ACCESS EXCLUSIVE | Builds its index |
| `ADD CONSTRAINT … UNIQUE USING INDEX`, or `PRIMARY KEY USING INDEX` on columns already NOT NULL | ACCESS EXCLUSIVE | Catalog only |
| `ADD CONSTRAINT … PRIMARY KEY USING INDEX` on a nullable column | ACCESS EXCLUSIVE | Scans the table |
| `DROP INDEX`, `RENAME COLUMN`, `DROP COLUMN`, `SET DEFAULT` | ACCESS EXCLUSIVE | Catalog only |
| `CREATE TRIGGER` | SHARE ROW EXCLUSIVE | Catalog only |
| `SET STATISTICS`, `COMMENT ON` | SHARE UPDATE EXCLUSIVE | Catalog only |

`VALIDATE CONSTRAINT` on a foreign key also takes ROW SHARE on the referenced table. Several
subcommands in one `ALTER TABLE` take the strictest lock any of them needs.

PostgreSQL holds a lock until the transaction ends, not the statement. So the work after a
lock-taking statement in the same transaction runs under that lock too:

- An `ADD CONSTRAINT … NOT VALID` followed by its `VALIDATE` in one transaction kept a
  reader waiting 2.0 s, until the commit. In two transactions, the reader took 0.5 ms.
- An `ADD COLUMN` followed by a backfill `UPDATE` in one transaction held a reader for
  2.3 s.
- A Flyway migration is one transaction, so the `VALIDATE` or the backfill goes in a later
  migration. Flyway's `group=true` wraps the whole run in one transaction and undoes that
  split: with it, a reader waited 1.6 s for the run to commit, and 0.7 ms without it.

## The lock queue and lock_timeout

- A lock request waits behind every conflicting lock already held, and every later request
  that conflicts with it waits behind it. A catalog-only `ADD COLUMN` waited 5 s for an
  open transaction that had read the table, and a plain `SELECT` sent after it waited
  4.5 s. So even an instant statement stops a busy table while a long transaction is open.
- `lock_timeout` bounds that wait. With it set, the same `ADD COLUMN` failed with
  "canceling statement due to lock timeout" when it expired, and the `SELECT` behind it ran.
- It bounds only the wait to acquire the lock. Once a plain index build has its lock, it
  blocks writes until its transaction commits. `statement_timeout` bounds the whole
  statement, and it cancelled a concurrent build too.
- So every migration on a busy table runs under a `lock_timeout`. Flyway's
  `beforeEachMigrate.sql` sets it before each migration, and `SET LOCAL` changes it inside
  one transactional migration (`flyway-mechanics.md` § Session settings). A concurrent
  build may take another, chosen as below.
- A migration that times out fails. A transactional one rolls back, and the next deploy
  retries it. A non-transactional one leaves a failed row in Flyway's history, which needs
  a repair first (`flyway-mechanics.md` § A failed migration and repair).

## Indexes

- `CREATE INDEX` takes SHARE: reads go on, and inserts, updates and deletes wait until its
  transaction ends. It may share a transaction with other DDL, which keeps writes waiting
  past the build: an insert sent once the build had finished still waited 2.9 s, until the
  commit 3 s later.
- `CREATE INDEX CONCURRENTLY` takes SHARE UPDATE EXCLUSIVE, so writes go on. An insert took
  0.8 ms during a concurrent build of 10 million rows, against 838 ms behind a plain one.
  The two scans cost time: 2.3 s where the plain build took 1.4 s.
- Its limits, each reproduced on 18.6:
  - It cannot run in a transaction block, so it needs a migration of its own that Flyway
    runs outside a transaction, with Flyway's session lock (`flyway-mechanics.md`).
  - Before each scan, it waits for transactions that have written to the table. At the end,
    it waits for any session holding an older snapshot: a query still running, on any
    table, or a REPEATABLE READ transaction. A READ COMMITTED transaction idle between
    statements held no snapshot and did not delay it, even after reading the table, and
    neither did an idle session. Writes went on while it waited. Other DDL and
    `VACUUM` on the table waited behind it, and so would a second concurrent build. Reads
    then queue behind that DDL: an `ALTER TABLE … ADD COLUMN` waited behind a waiting
    build, and a plain `SELECT` waited 5.5 s behind the `ALTER`.
  - A failure leaves an `INVALID` index, which the planner ignores. A duplicate in a unique
    build left one, and so did a `lock_timeout` or a `statement_timeout` that cancelled the
    build. What the leftover still does depends on `pg_index.indisready`:
    - Cancelled before its first scan, it was not ready. Writes ignored it: it stayed at
      0 bytes through 50,000 inserts, and a unique one let a duplicate in.
    - Cancelled while waiting for an older snapshot, after its scans, it was ready. Every
      insert maintained it, and a unique one rejected a duplicate.
  - `IF NOT EXISTS` checks the name only. It skipped the build over an invalid leftover,
    and over a same-named index on another column, so a rerun keeps whatever was there.
  - A partitioned table refuses it. Build each partition's index concurrently, create the
    parent's with `CREATE INDEX … ON ONLY`, then attach each partition's index with
    `ALTER INDEX … ATTACH PARTITION`. The parent index turned valid once every partition
    was attached.
  - A unique build enforces uniqueness on other transactions from its second scan on, before
    the index is usable (PostgreSQL docs).
- `lock_timeout` bounds each of those waits, not the build. Under 1 s, a 2.4 s build of
  10 million rows finished with no blocker. It failed after 1.0 s behind an uncommitted
  writer, and after 3.3 s behind an older snapshot.
- The build's waits block no reads or writes, only DDL and what queues behind it (above).
  So its timeout is an operational choice:
  - the run's short one where no long writer or snapshot is expected;
  - a longer one of its own where one is, below what the deploy allows.

  Each firing costs a failed row, an invalid index and a repair (`flyway-mechanics.md`
  § A failed migration and repair).
- The migration drops a leftover before it builds. A `SET lock_timeout` beside the build
  made Flyway refuse the migration as a mix, so a migration that sets its own holds
  `executeInTransaction=false` in its `.sql.conf`:

  ```sql
  SET lock_timeout = '10min';
  DROP INDEX CONCURRENTLY IF EXISTS shipments_carrier_id_idx;
  CREATE INDEX CONCURRENTLY shipments_carrier_id_idx ON shipments (carrier_id);
  ```

  - It was measured against an application transaction that had written to the table and
    stayed open 8 s. With the run's 5 s instead of the first line, the build failed after
    5 s and left an invalid index. With the first line, it waited the transaction out and
    built a valid index, and the next migration ran under `beforeEachMigrate.sql`'s 5 s
    again.
  - `SELECT indisvalid FROM pg_index WHERE indexrelid = 'shipments_carrier_id_idx'::regclass`
    confirms the result.
  - The drop also removes a valid index of that name. An index first built by hand, during
    an incident say, is codified with `IF NOT EXISTS` once its `indisvalid` and its
    definition, from `pg_get_indexdef`, are checked in every environment.
- A killed instance does not stop its build. The backend kept waiting after its client was
  killed, and later built a valid index that no history recorded. With
  `client_connection_check_interval` set, the backend ended with "connection to client
  lost" and left an invalid index, which the next run's drop clears.
  `beforeEachMigrate.sql` sets it (`flyway-mechanics.md` § Session settings).
- A build, or a `VALIDATE`, that can run longer than the application's startup allows runs
  as a migration step outside the application: the Flyway CLI or Maven plugin in the
  pipeline, or a job.
- A unique constraint is built online the same way: `CREATE UNIQUE INDEX CONCURRENTLY`, then
  `ADD CONSTRAINT … UNIQUE USING INDEX`, which changed the catalog only. A primary key
  `USING INDEX` also needs its columns NOT NULL first. Over a nullable column it scanned
  the table, and over a `NOT VALID` not-null it failed with "incompatible NOT VALID
  constraint".
- A plain index is right on a small table, or when nothing writes to the table during the
  migration, and it can then share a transaction with the DDL around it.

## NOT NULL and CHECK constraints

- `SET NOT NULL` and a new `CHECK` scan the whole table under ACCESS EXCLUSIVE, so reads and
  writes wait for the scan.
- The online path adds the constraint `NOT VALID`, a catalog change that every later insert
  and update must satisfy, and validates it in a later migration under SHARE UPDATE
  EXCLUSIVE. An insert took 0.6 ms during a 281 ms `VALIDATE` of 10 million rows.
- On PostgreSQL 18 a not-null constraint can itself be `NOT VALID`:

  ```sql
  ALTER TABLE shipments ADD CONSTRAINT shipments_service_level_not_null NOT NULL service_level NOT VALID;
  -- in a later migration
  ALTER TABLE shipments VALIDATE CONSTRAINT shipments_service_level_not_null;
  ```

  - After the `VALIDATE`, the column is NOT NULL and the planner removes `IS NULL` tests on
    it. No `SET NOT NULL` follows. On a column with an invalid not-null constraint,
    `SET NOT NULL` validates it with a full scan under ACCESS EXCLUSIVE.
  - Until then the catalog already reports the column NOT NULL, in `pg_attribute.attnotnull`
    and in `information_schema.columns.is_nullable`. A code generator or a schema diff
    reads NOT NULL while old rows may still hold nulls. The planner does not trust it yet:
    `WHERE service_level IS NULL` still returned the null row.
- The `CHECK` form also works on 18, and it is the only one before 18, whose release notes
  added `NOT VALID` to not-null constraints: `CHECK (service_level IS NOT NULL) NOT VALID`,
  then `VALIDATE CONSTRAINT`, then `SET NOT NULL`, then drop the `CHECK`. `SET NOT NULL`
  skipped its scan because the valid `CHECK` proved it. With `client_min_messages = debug1`
  it logged "existing constraints on column … are sufficient to prove that it does not
  contain nulls". A `NOT VALID` check proves nothing. Neither does a check that a NULL
  passes, such as `c IN ('a', 'b')`, since a check fails only on false.
- For a NOT NULL or a `CHECK` that existing rows still violate, the order matters. Such a
  `NOT VALID` constraint applies to every later update, so updating any column of a row
  that still holds a NULL fails: "null value in column … violates not-null constraint".
  So every writer fills the column first, the backfill finishes, and then the constraint is
  added `NOT VALID` and validated.
  - Every writer means every release still running, under a rolling deploy the previous one
    too. A column default (`SET DEFAULT`) or a `BEFORE INSERT` trigger each filled the
    column for an insert that left it out.
  - A `CHECK` that every existing row already meets needs no backfill: added `NOT VALID`,
    then validated, it let updates through in between.
  - A foreign key `NOT VALID` let an orphan row's other columns change, and refused only a
    change of the key to a missing value.
- A new column with one value for every existing row needs none of this:
  `ADD COLUMN tier text NOT NULL DEFAULT 'standard'` changed the catalog only, in 1.3 ms on
  10 million rows.
- A direct `SET NOT NULL` or `CHECK` is right in the same contexts as a plain index.

## Foreign keys

- `ADD FOREIGN KEY` takes SHARE ROW EXCLUSIVE on both tables and scans the referencing one,
  so writes to both wait for the scan.
- The online path is `ADD CONSTRAINT … FOREIGN KEY … NOT VALID`, then
  `VALIDATE CONSTRAINT`. The second takes SHARE UPDATE EXCLUSIVE on the referencing table
  and ROW SHARE on the referenced one.
- A new table with a foreign key to a busy table takes SHARE ROW EXCLUSIVE on the busy
  table. It is brief, but it queues like any DDL and needs the `lock_timeout` too.

## Backfills

- An `UPDATE` holds its row locks until it commits, so one statement over a large table
  blocks every concurrent update of those rows for its whole duration. A large table is
  backfilled in batches, each in its own short transaction.
- Each batch walks a range of the key and keeps the filter in its own `WHERE`:

  ```sql
  UPDATE shipments SET service_level = 'standard'
  WHERE id > :last_id AND id <= :last_id + 10000 AND service_level IS NULL;
  ```

  - The batches run from `min(id)` to the `max(id)` read at the start. Rows inserted later
    already carry the value, because every writer fills the column before the backfill
    starts (§ NOT NULL and CHECK constraints).
  - A batch that picks its rows with `WHERE service_level IS NULL ORDER BY id LIMIT 10000`
    walks the key from the start every time, past every row already done. On 2 million
    rows its batches grew from 121 ms to 423 ms, and the key-range batches stayed at 13 ms.
  - Under `READ COMMITTED`, a batch that waits for the application's update of a row
    re-checks only its own `WHERE` against the new row. With the filter only in a subquery
    that picks the batch, the batch overwrote the application's new value. With the filter
    in its own `WHERE`, it skipped the row.
  - Under `REPEATABLE READ`, the batch failed with "could not serialize access due to
    concurrent update", so a batch at that level is retried.
- A backfill that takes longer than a deploy may wait runs as a job outside the migrations.
  A shorter one can run in a non-transactional migration, where a `DO` block loops over
  the key ranges and commits after each batch (`flyway-mechanics.md` § Transactions). In a
  transactional migration the whole backfill is one transaction.

## Expand and contract

- Under a rolling deploy, two releases run against one schema, so each migration must work
  with the previous release's code. A rename, a type change, a split column or a new NOT
  NULL rule then spans several releases:
  1. **Expand:** add the new shape beside the old one, and release code that writes both.
  2. **Migrate:** backfill, then add and validate the constraints.
  3. **Switch:** release code that reads the new shape only.
  4. **Contract:** drop the old shape once no running release uses it.
- The extra releases are worth it when old and new code overlap on one schema: rolling
  deploys, or several services sharing it. With one instance stopped in a window, a direct
  `RENAME COLUMN` ships with the code that uses the new name.
- `DROP COLUMN` changes the catalog only, but the release that drops a column starts while
  the previous release still reads it. So the drop ships one release after the last code
  that reads the column.
