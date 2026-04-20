# Plan: Decouple Outbox Partition Execution from Observability

## Context

The `OutboxCleanupScheduler` currently couples two responsibilities: executing partition management (DDL) and tracking Micrometer metrics. This creates a false dependency — if the JVM scheduler is unhealthy (throttled by macOS App Nap, restarting, etc.), partitions don't get managed. The function should be owned by pg_cron in production, and Spring should only observe the results.

Additionally, `outbox_cleanup_log` only records successful completions (failures roll back the entire transaction, including the log INSERT). This makes pure-DB observability insufficient — the observer can't distinguish "cleanup failed" from "cleanup never ran."

## Files to modify

| File | Action |
|---|---|
| `src/main/resources/db/migration/account/V16__outbox_cleanup_observability.sql` | **Create** — new migration: alter table + restructure function |
| `src/main/java/org/girardsimon/wealthpay/account/infrastructure/db/repository/OutboxCleanupScheduler.java` | **Rename & rewrite** → `OutboxCleanupObserver.java` (poll-only) |
| `src/main/java/org/girardsimon/wealthpay/account/infrastructure/db/repository/OutboxCleanupFallbackScheduler.java` | **Create** — property-gated Spring execution fallback |
| `src/test/java/org/girardsimon/wealthpay/account/infrastructure/db/repository/OutboxCleanupSchedulerTest.java` | **Rename & rewrite** → `OutboxCleanupObserverTest.java` |
| `src/test/java/org/girardsimon/wealthpay/account/infrastructure/db/repository/OutboxCleanupFallbackSchedulerTest.java` | **Create** — test for fallback scheduler |
| `src/main/resources/application.properties` | **Edit** — add fallback toggle property |
| jOOQ generated sources | **Regenerate** after migration |

## Step 1: New Flyway migration — V16

### 1a. Evolve `outbox_cleanup_log` schema

Add columns to capture failures and timing:

```sql
ALTER TABLE account.outbox_cleanup_log
    ADD COLUMN status       text        NOT NULL DEFAULT 'success',
    ADD COLUMN started_at   timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN completed_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN error_message text;
```

- `status`: `'success'` or `'failure'`
- `started_at` / `completed_at`: use `clock_timestamp()` in the function (wall-clock, not transaction-start)
- `error_message`: nullable, populated only on failure
- Defaults ensure backward compatibility with existing rows (all treated as success)

### 1b. Restructure `manage_outbox_partitions()` with top-level EXCEPTION block

```
DECLARE
    v_started_at timestamptz := clock_timestamp();
    ...existing variables...
BEGIN
    -- A. Create future partitions (same logic)
    -- B. Drop old partitions (same logic)
    -- C. Count remaining
    -- D. Insert SUCCESS row with clock_timestamp() for completed_at

EXCEPTION WHEN OTHERS THEN
    -- Insert FAILURE row with SQLERRM as error_message
    -- The work above is rolled back (PL/pgSQL subtransaction semantics)
    -- Only the failure log INSERT commits
    RAISE; -- re-raise so pg_cron/caller sees the error
END;
```

Key behavior:
- **On success**: all DDL work committed + success row logged
- **On failure**: DDL work rolled back (PostgreSQL subtransaction), failure row still inserted and committed, exception re-raised

### 1c. Updated pg_cron comment with explicit UTC

```sql
-- SELECT cron.schedule(
--     'outbox-partition-cleanup',
--     '0 3 * * *',
--     $$SELECT account.manage_outbox_partitions(3)$$
-- );
-- Note: ensure cron.timezone = 'UTC' or PostgreSQL timezone GUC is UTC
```

## Step 2: Rename `OutboxCleanupScheduler` → `OutboxCleanupObserver`

Single responsibility: **observe and report**, never execute.

- Remove `manageOutboxPartitions()` call entirely
- Remove `retentionDays` field and `@Value` injection
- Replace `@Scheduled(cron = "0 0 3 * * *")` with `@Scheduled(fixedDelayString = "${outbox.cleanup.poll-interval-ms:300000}")` (5 min default)
- Method body: query latest row from `outbox_cleanup_log`, update gauges:
  - `outbox.cleanup.last_run.seconds` — `completed_at` of latest successful row (existing gauge, same semantics)
  - `outbox.cleanup.last_status` — new gauge: `1` for success, `0` for failure (from most recent row)
- Keep `initLastRunFromLog()` for startup initialization
- Keep `Clock` injection for consistency

The existing Prometheus alerts (`OutboxCleanupStale`, `OutboxTableGrowing`) continue to work unchanged — the gauge name and semantics are the same.

## Step 3: New `OutboxCleanupFallbackScheduler`

Property-gated execution for environments without pg_cron (dev, CI):

- `@ConditionalOnProperty(name = "outbox.cleanup.spring-execution.enabled", havingValue = "true")`
- `@Scheduled(cron = "0 0 3 * * *", zone = "UTC")` — explicit UTC
- Calls `manageOutboxPartitions(retentionDays)` — same as current code
- Minimal: no metrics responsibility (observer handles that)
- Catches `DataAccessException` to prevent scheduler thread death

## Step 4: Update `application.properties`

```properties
# Outbox cleanup
outbox.cleanup.retention-days=${OUTBOX_CLEANUP_RETENTION_DAYS:3}
outbox.cleanup.spring-execution.enabled=${OUTBOX_CLEANUP_SPRING_EXECUTION:false}
```

## Step 5: Rework tests

### `OutboxCleanupObserverTest`
- Seed `outbox_cleanup_log` with known rows (success + failure), call poll method, assert:
  - `last_run.seconds` gauge matches the latest successful `completed_at`
  - `last_status` gauge reads `1` when latest is success, `0` when latest is failure
- Test startup initialization from log (existing `initLastRunFromLog` behavior)
- No partition creation tests — that's the function's job, not the observer's

### `OutboxCleanupFallbackSchedulerTest`
- Call `cleanupPartitions()`, verify partitions are created (reuse existing test logic)
- Verify failure is caught and doesn't throw

### Existing function tests
- The PostgreSQL function is already tested via the current partition creation tests — keep that coverage but it naturally lives in the fallback scheduler test since it calls the function

## Step 6: Regenerate jOOQ

After V16 migration adds new columns, regenerate jOOQ sources so `OutboxCleanupLog` table class includes `STATUS`, `STARTED_AT`, `COMPLETED_AT`, `ERROR_MESSAGE` fields.

## What we are NOT doing

- **No ShedLock** — pg_cron owns execution, no distributed locking needed
- **No `outbox_cleanup_log` schema redesign beyond the 4 new columns** — keep it simple
- **No merge of `OutboxMetrics` and `OutboxCleanupObserver`** — different concerns, different lifecycles
- **No custom `TaskScheduler` bean** — only one `@Scheduled` method in prod (the observer's `fixedDelay`), single thread is fine
- **No alert rule changes** — existing expressions work unchanged with the new design

## Verification

1. `./mvnw test` — all tests pass (observer + fallback + function)
2. Verify jOOQ regeneration succeeds and compiles
3. Verify `OutboxCleanupFallbackScheduler` does NOT load without the property (default off)
4. Verify `OutboxCleanupObserver` loads and polls correctly
5. Verify the V16 migration applies cleanly on top of V14/V15
