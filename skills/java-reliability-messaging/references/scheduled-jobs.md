# Scheduled jobs

How a scheduled job runs once per schedule when several instances run the application, and
what each run needs to survive an overlap, a crash or a missed schedule. The facts were
checked on 2026-10-24 on Spring Boot 4.1.2 (Spring Framework 7.0.10), ShedLock 7.10.1 with
its `JdbcTemplateLockProvider`, PostgreSQL 18.6 and pg_cron 1.6.8. The rules come from
[ShedLock's README](https://github.com/lukas-krecan/ShedLock),
[pg_cron's README](https://github.com/citusdata/pg_cron) and Prometheus's
[instrumentation practices](https://prometheus.io/docs/practices/instrumentation/).
`~/.claude/evals/java-reliability-messaging/probes/spring-fixture.sh` reruns the ShedLock
and pooled-lock cases, and `pg-cron.sh` beside it the pg_cron cases, named F1 to F5 below.
`concurrency-control.md` holds the claims and advisory locks this file relies on.

## Contents

- Decide by the instance count
- ShedLock
- Other ways to run once
- Zone and schedule
- Idempotent, chunked and resumable runs
- Missed runs
- Last success and its alert

## Decide by the instance count

- Every instance that has the bean runs a `@Scheduled` method. Two Spring contexts on one
  database each ran a job due every two seconds, at the same seconds.
- One instance needs no lock when that is a written constraint: an ADR, a replica count of
  one, and a deploy that stops the old instance before it starts the new one. A deploy that
  starts the new instance first runs two for a while. The constraint names what ends it: a
  second instance needs a lock first.
- One instance can still overlap itself. With `spring.threads.virtual.enabled=true`, Spring
  Boot schedules on a `SimpleAsyncTaskScheduler`. A 2.5 s job ran 7 times in 6.5 s, up to 3
  at once, as a cron or fixed-rate job due every second, and twice, one at a time, as a
  fixed-delay job with a 1 s delay. The default `ThreadPoolTaskScheduler` ran each of the
  three one at a time. On virtual threads, a cron or fixed-rate job whose run, with a
  timeout on each call, can still outlast its interval takes a lock even on one instance. A
  fixed-delay job does not overlap itself. A run that can hang needs the timeout, not a
  lock: an advisory lock held by the hung run makes every later run skip, and ShedLock lets
  the next run in once `lockAtMostFor` has passed.
- With several instances, one of these makes the work run once:
  - a lock the instances share: ShedLock, or an advisory lock;
  - a claim on each work item, so whichever instance takes an item processes it alone;
  - a scheduler outside the application: pg_cron for SQL work, or a single scheduler for the
    deployment.
- ShedLock with a `lockAtLeastFor` lets one instance run per schedule. An advisory lock,
  released at commit or at the unlock, only keeps runs from overlapping: an instance whose
  trigger fires after the commit takes it and runs again (`concurrency-control.md`, E2), so
  once per schedule then comes from the run's own record, such as a unique key on the job
  and its business date. Either way the run is idempotent, because a lock can expire under
  it, an instance can crash halfway and a person can start a run by hand.

## ShedLock

- The lock is a row of a `shedlock` table, created by a migration with the README's
  PostgreSQL columns. The provider is a `JdbcTemplateLockProvider` built with
  `.usingDbTime()`, `@EnableSchedulerLock(defaultLockAtMostFor = ...)` turns it on, and
  `@SchedulerLock(name = ...)` sits beside each `@Scheduled`.
- An instance that finds the lock taken skips the run; it does not wait. With the lock, the
  two contexts ran the job once per tick, on one or the other.
- `lockAtMostFor` frees the lock of an instance that died. It does not stop the run: a 3 s
  run under a 1 s `lockAtMostFor` started on one instance while the other instance's run was
  still going, every time. It is set well above the longest run.
- `lockAtLeastFor` keeps the lock after a short run, so an instance whose trigger fires a
  little later finds it taken. With 0, a run triggered on the second instance 500 ms after
  the first ran again; with 5 s it was skipped. It is set below the interval and above the
  clock difference between instances.
- `usingDbTime()` takes the lock's times from the database's clock. Without it, each
  instance writes and compares `lock_until` with its own clock: an instance 11 minutes ahead
  took a lock still held for 10 minutes, and with `usingDbTime()` it was refused.

## Other ways to run once

- An advisory lock keeps runs from overlapping. `pg_try_advisory_xact_lock(key)` at the
  start of a run that is one transaction skips the run while another instance holds the key,
  and the lock ends with the transaction, a crash included. A chunked run commits many
  transactions, so it holds a session lock on one connection for the whole run and unlocks
  on it in a `finally`. Held that way while three batches ran on other pooled connections,
  the lock refused a second instance, which took it after the unlock. PgBouncer's
  transaction pooling breaks that (`concurrency-control.md` § Advisory locks), and ShedLock
  or a claim per item works there.
- A claim per item: each instance claims a batch with `UPDATE ... SET state = 'claimed'
  WHERE id IN (SELECT id ... ORDER BY id LIMIT :n FOR UPDATE SKIP LOCKED) RETURNING ...` and
  commits, so the instances share the work. Two concurrent claims took disjoint items, and
  under `REPEATABLE READ` a claim needs the retry (`concurrency-control.md` § Row locks). An
  item a crashed instance claimed needs a rule that hands it back, such as a claim older
  than the longest run. Work that finishes inside one short transaction can lock its batch
  with `SELECT ... FOR UPDATE SKIP LOCKED` instead, as `outbox.md`'s relay does.
- pg_cron runs SQL inside the database on a schedule, however many application instances
  there are:
  - it runs one instance of a job at a time: a job due every 2 s whose run took 5 s ran
    twice in 15 s, the second run starting 0.01 s after the first ended (F2);
  - it reads a schedule in GMT unless `cron.timezone` is set at server start (F1, F4);
  - `cron.job_run_details` keeps each run's status, message and end time (F3). The README
    has a scheduled `DELETE` keep it bounded, and its retention outlasts the longest
    interval, or a weekly job's last success disappears;
  - it fits SQL work, such as `outbox.md`'s partition drops. Java logic stays in the
    application.

## Zone and schedule

- `@Scheduled(cron = ..., zone = "Europe/Zurich")` names its zone; without one the cron
  follows the scheduler's default zone. `java-financial-correctness`'s `time.md` § Scheduled
  jobs has the probe, the DST gap and overlap, and the key on a run's business date.
- pg_cron reads a schedule in `cron.timezone`. The same daily schedule, the next whole
  minute but one in Zurich's local time, ran at that minute on a server set to
  `Europe/Zurich` and not at that minute on one left at GMT (F4).

## Idempotent, chunked and resumable runs

- Idempotent: a second run for the same schedule finds the work done. A unique key on what
  the run produces makes a repeat conflict instead of doing it twice, as `time.md` shows for
  interest entries, and per-item state does the same for work items.
- Chunked: the run works in batches, each its own short transaction, walking a key range.
  One transaction over the whole run holds its row locks and its snapshot until the end.
  `java-schema-migrations`' `online-changes.md` § Backfills measured the key-range walk.
- Resumable: each batch commits its progress with its work, as per-item state or the last
  key done, so the next run continues where a crash stopped.
- Work outside the database, such as an email or an HTTP call, is claimed and committed,
  then done, then marked done. A crash between the call and the mark repeats the call, so
  the call carries an idempotency key wherever the other side accepts one
  (`transactions-and-idempotency.md`).
- A run selects what is still due, not only what fell due since the last run, so an item
  that failed is taken again.

## Missed runs

- A schedule fires only while its scheduler runs. pg_cron did not make up the minutes its
  server was down (F5). An instance that died holding ShedLock's lock keeps the job from
  running until `lockAtMostFor` has passed.
- Each job states what happens to a missed run:
  - skip: the next run covers the gap, because it takes everything still due;
  - catch up: the run works out the business dates since its last success and processes
    each, keyed so a date already done is a no-op;
  - alert only: a person decides.

## Last success and its alert

- Prometheus's practice for a batch job is to export the Unix time of its last success as a
  gauge, not the time since, and to compute the age with `time() - metric`.
  `java-observability`'s `pillars.md` has the naming and label rules, and the job's name is
  a bounded label.
- The alert fires when that age passes the interval plus the longest normal run plus a
  margin. It is a freshness signal (`java-observability`'s `slos-and-dashboards.md`), and it
  catches a job that failed, never started or was skipped.
- With several instances the time lives in the database, not in each instance's memory: only
  the instance that ran holds a recent value, and a restart forgets it. A table of runs, or
  pg_cron's `cron.job_run_details` filtered on `status = 'succeeded'` (F3), gives every
  instance the same value. The last success outlives the history's pruning: a row per job,
  or a retention longer than the longest interval.
- Before a job's first success, the gauge reports the time the job was deployed, kept in a
  row the job's migration seeds rather than taken from an instance's start, which every
  restart resets. A job that never succeeds then still ages into the alert.
- Failed runs are a second signal, counted per job.
