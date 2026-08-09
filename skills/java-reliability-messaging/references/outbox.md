# The Transactional Outbox pattern

Reference for the `java-reliability-messaging` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Transactional Outbox Pattern

**The canonical answer to "update the DB AND publish an event."** Never dual-write. Never.

### Schema

```sql
CREATE TABLE outbox (
  id              BIGSERIAL,
  aggregate_type  TEXT NOT NULL,
  aggregate_id    TEXT NOT NULL,
  event_type      TEXT NOT NULL,
  payload         JSONB NOT NULL,
  headers         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  published_at    TIMESTAMPTZ,
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE INDEX outbox_unpublished_idx ON outbox (created_at) WHERE published_at IS NULL;
```

**Why the composite key.** PostgreSQL requires every unique constraint on a partitioned table to contain all partition-key columns, so a bare `id BIGSERIAL PRIMARY KEY` makes `PARTITION BY RANGE (created_at)` fail outright — and partitioning is what the retention rule in *Non-negotiables* depends on. `id` stays globally unique via the sequence; `created_at` rides along to satisfy the constraint. If you genuinely do not need retention (a low-volume outbox you prune by hand), drop the `PARTITION BY` clause and `PRIMARY KEY (id)` alone is fine — but then delete the partitioning advice too, rather than leaving a schema that cannot support it.

### Write path (inside the use case's transaction)

```java
@Transactional
public void place(PlaceOrderCommand cmd) {
  var order = Order.place(cmd, clock);
  orders.save(order);                                 // business write
  outbox.enqueue(                                     // outbox row — same tx
    "Order", order.id().value(),
    "OrderPlaced", payloadFor(order),
    traceHeaders()                                    // propagate traceId for cross-service tracing
  );
}
```

Both writes commit together or neither does. No divergence possible.

### Publish path (separate process / thread)

Two implementations, pick one:

**Option 1 — Debezium CDC (preferred for scale).** Debezium tails the DB's WAL/binlog and emits every outbox row to Kafka. No polling, sub-second latency, exactly-once into Kafka (within Debezium's semantics).

**Option 2 — Polling publisher.** A background worker selects unpublished rows, publishes to Kafka, then updates `published_at`. Simpler to operate, adequate for moderate throughput. Use `FOR UPDATE SKIP LOCKED` to allow multiple workers without contention:

```sql
SELECT * FROM outbox
WHERE published_at IS NULL
ORDER BY id
LIMIT 100
FOR UPDATE SKIP LOCKED;
```

### Non-negotiables

- **Publish must be idempotent on the Kafka side.** Use `enable.idempotence=true` + a deterministic message key. Republishing the same outbox row must produce the same effective result downstream.
- **Consumer must still be idempotent.** Outbox guarantees at-least-once delivery to the broker — consumers can still see duplicates.
- **Monitor outbox lag.** `outbox_unpublished_count` and `outbox_oldest_unpublished_age_seconds` are critical SLIs. A stuck publisher is invisible until you measure it.
- **Don't put outbox rows in the same table as business data.** Separate table, separate concern.
- **Plan retention on day one.** Published rows accumulate forever by default — heap bloats, autovacuum cost rises, backups and replication windows grow. The cheapest correct answer is **range-partition the outbox by day** (`outbox_YYYY_MM_DD`) on the event timestamp, pre-create partitions ahead of the write path, and drop old partitions via a scheduled job (pg_cron or equivalent). `DROP TABLE` on a partition is O(1) — no dead tuples, no vacuum pressure — versus `DELETE WHERE created_at < …` which is O(N) and fights the write path for locks. For CDC setups, publish via the partition root (`publish_via_partition_root=true` on the PostgreSQL publication) so Debezium sees all child-partition changes as originating from the parent table. Retention window = Kafka's upstream replay horizon + a safety margin; 3–14 days is typical. Surface cleanup success/failure and table size as metrics — a silently-broken cleanup job is how this bites you in month six.
- **Avoid `TRUNCATE` and row-level `DELETE` for cleanup.** `TRUNCATE` takes `ACCESS EXCLUSIVE` and blocks inserts on a write-path-critical table. Per-row `DELETE` doubles WAL volume (every outbox row also generates a delete entry Debezium has to process) and contends with concurrent inserts.

### When outbox is overkill

- In-process domain events where the handler runs in the same transaction as the publisher (module-to-module in a monolith, synchronous listener): just use an in-process event bus — a Java record published on a `ApplicationEventPublisher` or equivalent. No broker, no outbox.
- One-shot scripts with no retry semantics.
