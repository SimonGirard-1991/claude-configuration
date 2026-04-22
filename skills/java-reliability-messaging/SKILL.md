---
name: java-reliability-messaging
description: Use when designing or reviewing message-driven or cross-service Java backends — Kafka/RabbitMQ/SQS consumers and producers, retryable HTTP endpoints, cross-aggregate workflows, or anywhere a use case must update a database AND publish an event. Covers transactional boundaries, idempotency keys, the Transactional Outbox pattern, exponential backoff with jitter, Dead Letter Queues, poison-message handling, at-least-once vs exactly-once semantics, and Saga choreography vs orchestration. Skip for throwaway scripts, purely synchronous single-DB CRUD, or non-Java code.
---

# Java Reliability & Messaging

This skill encodes the rules for making Java backends **reliable under failure** — specifically the class of failures that show up the moment a use case crosses a process boundary (DB + broker, service-to-service, cross-aggregate workflow). These are the bugs that do not appear in a green test suite and only surface under partial failure in production: duplicate charges, lost events, silently dropped messages, poison-pilled partitions, sagas wedged halfway.

Defaults assume Spring Boot + Kafka + a relational DB (Postgres/MySQL) + jOOQ. The principles carry to RabbitMQ, SQS, and Pulsar; the concrete knobs differ. Quarkus and Micronaut ship equivalent primitives.

## When to use

- Designing a Kafka (or RabbitMQ / SQS / Pulsar) consumer or producer.
- Adding a retryable HTTP endpoint (webhooks, payment callbacks, anything with a client retry budget).
- A use case that must update the DB **and** publish an event in the same logical unit of work.
- Cross-aggregate or cross-service workflow that cannot fit in a single DB transaction (reservation → payment → fulfillment).
- Reviewing a PR for reliability gaps: missing idempotency, dual writes, unbounded retries, no DLQ, saga with no compensation path.
- Post-incident: duplicate processing, phantom events, stuck consumer lag, poison messages blocking a partition.

## When NOT to use

- Throwaway spikes or one-shot scripts.
- Synchronous single-DB CRUD with no messaging and no external calls.
- Internal in-process domain events between modules of a monolith where the listener runs in the **same transaction** as the publisher (a Java record on an in-process event bus suffices — no broker, no outbox).
- Non-Java code (principles transfer; tooling does not).

## Core principles

1. **Every cross-boundary operation fails halfway.** Network partitions, broker restarts, pod kills, slow DBs — they all happen. Design for "the producer committed the DB row, then crashed before the broker acked." If your code path has no answer for that, it has a bug.
2. **Dual writes are a bug.** Writing to the DB and then publishing to Kafka in the same method is a dual write. Under failure they will diverge. Use the **Transactional Outbox** or an equivalent single-source-of-truth pattern.
3. **At-least-once is the honest default.** Exactly-once across a broker and a DB is a marketing phrase. Engineer for **at-least-once + idempotency** and sleep at night.
4. **Idempotency is a property of the consumer, not the broker.** No broker configuration makes a non-idempotent consumer safe. The consumer must be able to see the same message twice and produce the same outcome.
5. **Retries without jitter are a self-DoS.** Synchronized retries from N instances pile onto the downstream the moment it recovers. Always exponential backoff **with jitter** and a bounded retry budget.
6. **A poison message must never block a partition forever.** Bounded retries, then DLQ with full context, then alert. "Retry forever and hope" is how consumer lag reaches a million.
7. **Sagas need compensations, not just happy paths.** For every forward step, define the backward step. A saga that can only move forward is a transaction pretending not to be one.
8. **Observability is part of reliability.** Outbox lag, retry counts, DLQ depth, saga state — all must emit metrics. A system you cannot see failing is a system that fails silently. See the `java-observability` skill.

## Transactional boundaries

**The unit of business consistency is the use case, not the controller and not the repository.**

- Open the transaction at the use-case entry point (application service / command handler). Commit it at the exit.
- The controller is a thin adapter — it does not start transactions. If two different controllers kick off the same use case, they get identical transactional behavior because transactions live in the use case.
- The repository is a thin adapter — it does not start transactions. A repo that opens its own transaction per call forces the caller into N little transactions when it wanted one big one.
- A use case that touches two aggregates in one transaction is a **design smell** — it says the aggregate boundary is wrong, or you need a saga. Aggregates are transactional units by design.

```java
// Application layer — transaction boundary lives here.
@Transactional
public OrderPlaced place(PlaceOrderCommand cmd) {
  var order = Order.place(cmd, clock);          // domain
  orders.save(order);                            // adapter (no @Transactional of its own)
  outbox.enqueue(OrderPlacedEvent.from(order)); // same tx — see Outbox section
  return OrderPlaced.from(order);
}
```

**Rule**: if a method has `@Transactional`, it is an application-layer use case. Domain objects are never `@Transactional`. Repositories are never `@Transactional` at the public method level (internal implementation detail only).

## Idempotency

Every Kafka consumer and every retryable HTTP endpoint must be idempotent. Two patterns, pick based on the shape of the operation:

### Pattern A — Idempotency key + dedicated table

Best for: external-facing retryable endpoints (payments, webhooks), or consumers where the message carries a natural unique ID.

Schema:

```sql
CREATE TABLE processed_messages (
  idempotency_key   TEXT PRIMARY KEY,
  result_hash       BYTEA NOT NULL,
  processed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Flow:

1. Client (or upstream producer) supplies an idempotency key. For Kafka, use a business key (`orderId`) or `topic+partition+offset` if no business key exists.
2. Inside the same DB transaction as the business update, `INSERT` into `processed_messages`. On unique-violation, the message has already been processed → short-circuit and return the stored result.
3. Otherwise do the work, write the business changes, commit.

**Critical**: the `INSERT` into `processed_messages` and the business write must share a transaction. If they don't, you have a dual write.

**External side effects inside Pattern A need their own idempotency.** The `processed_messages` row dedupes the *DB work*, not external calls. If the use case also calls a payment gateway, sends an email, or hits a third-party API inside the transaction, and the DB commit fails after the external call succeeded, the retry will re-invoke that external call — charging twice, emailing twice. Two correct patterns:

1. **Propagate an idempotency key to the downstream.** Stripe, Adyen, and most mature payment APIs accept an `Idempotency-Key` header. Use the same key you stored in `processed_messages`. The downstream then dedupes for you.
2. **Move the side effect behind its own outbox row**, consumed by a dedicated worker whose job is exactly "call the external API." That worker has its own idempotency layer. This keeps the transactional core pure and moves the external-call retry semantics where they belong.

Never rely on "the transaction will roll back" to undo an external call. It won't — the external system has already acted.

**TTL / cleanup**: `processed_messages` grows unbounded. Add a background job that deletes rows older than the upstream retry window (24h is typical for Kafka, 7 days for payment webhooks — match the producer's retry horizon, not a guess).

### Pattern B — Natural idempotency via state check

Best for: state-transition operations where the target state is its own proof of completion.

```java
public void markPaid(OrderId id) {
  var order = orders.findById(id).orElseThrow();
  if (order.status() == PAID) return;   // already applied — safe no-op
  order.markPaid(clock);
  orders.save(order);
  outbox.enqueue(OrderPaidEvent.from(order));
}
```

This only works if the state transition is genuinely idempotent at the domain level (PAID → PAID is a no-op, never a double-charge). If the operation has **side effects that are not captured in the state** (calling an external API, sending an email), Pattern B is **not enough** — use Pattern A, or move the side effect behind its own outbox/idempotency layer.

### What does NOT count as idempotency

- "Kafka is configured with `enable.idempotence=true`." That makes the **producer** idempotent within a single producer session. The consumer is still responsible for its own idempotency.
- "We use exactly-once semantics." See the delivery semantics section — EOS only holds within Kafka's own read/process/write cycle. The moment you cross to a DB, you're back to at-least-once + idempotency.
- "Our DB has a unique constraint." Unique constraints catch the duplicate *after* the redundant work is done (external API already called, email already sent). Idempotency must short-circuit before side effects.

## Transactional Outbox Pattern

**The canonical answer to "update the DB AND publish an event."** Never dual-write. Never.

### Schema

```sql
CREATE TABLE outbox (
  id              BIGSERIAL PRIMARY KEY,
  aggregate_type  TEXT NOT NULL,
  aggregate_id    TEXT NOT NULL,
  event_type      TEXT NOT NULL,
  payload         JSONB NOT NULL,
  headers         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  published_at    TIMESTAMPTZ
);

CREATE INDEX outbox_unpublished_idx ON outbox (created_at) WHERE published_at IS NULL;
```

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

## Retries, backoff, and jitter

**Rule**: every retry loop has a bounded budget and jittered exponential backoff.

### Parameters that matter

- **Base delay**: 100ms–1s depending on downstream.
- **Multiplier**: typically 2×.
- **Max delay (cap)**: 30s–5min; don't let a single retry sleep forever.
- **Max attempts**: 3–10 for synchronous calls; higher for messaging where a DLQ catches the remainder.
- **Jitter**: **full jitter** by default (`delay = random(0, exponentialBackoff)`), not "equal jitter" or "decorrelated jitter" unless you have a reason. Full jitter is the simplest and performs well for most workloads. The AWS Architecture Blog post on exponential backoff and jitter is the reference.

### Spring Retry (HTTP, synchronous)

```java
@Retryable(
  retryFor = TransientException.class,
  maxAttempts = 5,
  backoff = @Backoff(delay = 200, multiplier = 2, maxDelay = 10_000, random = true)
)
public PaymentResult authorize(PaymentRequest req) { ... }
```

### Kafka consumer retries (Spring Kafka)

Use a `DefaultErrorHandler` with `ExponentialBackOffWithMaxRetries` and a **non-blocking retry topology** (`@RetryableTopic`) for anything where blocking the partition is unacceptable. Note: the attribute and type casing on `@RetryableTopic` has shifted across Spring Kafka majors — older examples in the wild use `backoff = @Backoff(...)` (lowercase, from `org.springframework.retry.annotation`), current Spring Kafka uses `backOff = @BackOff(...)` (capital O, Spring Kafka's own annotation). **Pin the form to your version** — don't copy between codebases on different Spring Kafka majors.

```java
@RetryableTopic(
  attempts = "5",
  backOff = @BackOff(delay = 1000, multiplier = 2, maxDelay = 60_000),
  include = { TransientException.class },
  dltTopicSuffix = "-dlt"
)
@KafkaListener(topics = "orders.placed")
public void onOrderPlaced(OrderPlacedEvent event) { ... }

@DltHandler
public void handleDlt(OrderPlacedEvent event, @Header(KafkaHeaders.RECEIVED_TOPIC) String topic) {
  // Persist, alert, or forward for operator review. Never re-throw — DLT is the end of the line.
}
```

This produces `orders.placed-retry-0`, `orders.placed-retry-1`, ..., `orders.placed-dlt`. The main partition keeps flowing while failed messages retry out-of-band.

**Ops cost to understand before choosing it:** non-blocking retries are not free. Each retry level spawns its own topic, its own consumer container, and its own listener group-offset bookkeeping. A `attempts = 5` config creates **4 retry topics + 1 DLT** per listener, all of which must exist, be monitored, and be cleaned up when retention expires. For high-fanout services this adds up quickly. If partition throughput is not a concern and the downstream is usually fast, a blocking `DefaultErrorHandler` with `ExponentialBackOffWithMaxRetries` + explicit DLT publish is simpler and cheaper to operate. Choose non-blocking when head-of-line blocking is a real concern (slow downstreams, mixed-SLA messages on one topic); choose blocking when you want fewer moving parts.

### What NOT to do

- Unbounded retries (`while (true) { try { ... } catch { sleep } }`). A permanently-broken downstream pins a consumer forever.
- Fixed-delay retries from N pods. Synchronized hammering of a recovering service is a classic outage amplifier.
- Retrying on non-transient errors (4xx, validation failures, deserialization failures). Those are poison messages — send them to the DLQ, don't retry them.

## Dead Letter Queues and poison messages

A **poison message** is one that will never succeed — malformed payload, missing foreign key, schema mismatch, semantic invariant violation. Retrying it wastes resources and blocks the partition behind it.

### DLQ design

- **Separate topic** (`<original>-dlt` or `<original>.DLQ`), same partitioning scheme.
- **Full context in headers**: original topic, partition, offset, timestamp, exception class, exception message (truncated), stack trace (truncated), trace ID, consumer group, attempt count.
- **Original payload preserved verbatim.** Do not transform or re-serialize — you need the exact bytes for replay.
- **DLQ depth is an SLI.** Alert when the rate of messages arriving in DLQs exceeds a threshold. A DLQ that nobody watches is a silent failure.
- **Replay tooling is a deliverable.** Once the bug is fixed, someone must be able to replay DLQ messages back onto the original topic. Build this on day one, not on day one of the incident.

### Classifying errors

| Error class | Retry? | Destination |
|---|---|---|
| Transient (timeout, broker unavailable, 5xx, deadlock) | Yes, with backoff | Retry topics |
| Permanent (deserialization failure, schema mismatch, 4xx, domain invariant violated) | **No** | DLQ immediately |
| Unknown | Treat as transient until proven otherwise; bound retries aggressively | Retry then DLQ |

Spring Kafka's `DefaultErrorHandler.addNotRetryableExceptions(...)` lets you declare permanent errors explicitly. Use it.

## Delivery semantics — an honest taxonomy

### At-most-once

Fire-and-forget. Message may be lost, never duplicated. Rarely acceptable; reserve for truly non-critical signals (cache invalidation hints, debug telemetry) where loss is cheaper than the complexity of the alternative.

### At-least-once (the default)

Message is delivered one or more times. **The consumer is responsible for deduplication via idempotency.** This is what you should assume unless proven otherwise.

Kafka defaults: `enable.auto.commit=false`, commit offsets **after** successful processing. A crash between processing and commit means reprocessing — which your idempotency handles.

**Commit ordering is the subtle trap.** For at-least-once to actually hold, the offset commit must be *causally after* the DB write commits. If you commit the offset first and then the DB write fails, the message is lost — that is at-most-once semantics dressed up as at-least-once, and it looks correct on a code review. Two correct patterns:

1. **DB commit first, then offset commit** (the simple form). A crash between them replays the message; idempotency absorbs the duplicate. This is what `enable.auto.commit=false` + "commit after successful processing" buys you — but only if you mean it, and the processing path does not itself commit the offset earlier.
2. **Compose Kafka's transactional producer with the DB transaction manager.** The Kafka offset commit participates in the same transactional scope as the DB write; a failure on either side rolls the other back. Historically this was wired via `ChainedKafkaTransactionManager`, which newer Spring Kafka de-emphasizes in favor of composing `KafkaTransactionManager` with the DB `PlatformTransactionManager` directly (or `@Transactional` with a transactional Kafka producer). The concept is what matters; pin the mechanism to your Spring Kafka version. Stronger guarantees, more moving parts.

Pattern 1 + Pattern A (processed_messages) is what most services should reach for. Pattern 2 is worth it when the idempotency key is hard to derive or the side effects are especially expensive. **Either way, never commit the offset before the DB commits succeed.**

### Exactly-once — the nuanced truth

Kafka's "exactly-once semantics" (EOS) holds **only** within a Kafka-to-Kafka pipeline using the transactional producer API + `isolation.level=read_committed` on consumers. The moment the consumer writes to a **database, external API, or any non-Kafka sink**, EOS **does not apply** — you are back to at-least-once + idempotency.

**Consequences**:

- A consumer that reads from Kafka and writes to Postgres is at-least-once. Treat it as such.
- A Kafka Streams topology that reads from Kafka and writes to Kafka can be exactly-once (`processing.guarantee=exactly_once_v2`). Worth it for stream-processing pipelines.
- "We need exactly-once for our payment flow" almost always means "we need idempotency + at-least-once." The idempotency key + processed-messages table is the implementation, not EOS.

**Bottom line**: stop reaching for EOS. Design for at-least-once + idempotency. It is simpler, correct, and honest about what the infrastructure actually guarantees.

## Saga pattern — cross-aggregate, cross-service workflows

When a business process touches multiple aggregates or multiple services and cannot fit into a single DB transaction, use a **saga**: a sequence of local transactions, each with a **compensating action** to undo its effect.

### Choreography (preferred default)

Each service reacts to events, emits its own events, and the workflow emerges from the event graph. No central coordinator.

```
OrderPlaced → (Payment service) → PaymentAuthorized → (Inventory) → InventoryReserved → (Shipping) → Shipped
                                ↓ PaymentDeclined
                                 → (Order) → OrderCancelled
```

**When**: 2–4 steps, stable workflow, services are already event-driven.

**Pros**: no central coupling, each service owns its piece, scales naturally.

**Cons**: the workflow is implicit in the event wiring — hard to visualize and reason about as it grows. Debugging "why did this saga stop at step 3?" means tracing events across services.

### Orchestration (escalation)

A dedicated orchestrator service (or state machine) drives the workflow, calling services in sequence and issuing compensations on failure.

**When**: 5+ steps, complex conditional branching, workflow changes frequently, explicit visibility into saga state is a business requirement (audit, support, observability).

**Tools**: Camunda, Temporal, Netflix Conductor, or a hand-rolled state machine persisted in the DB. **Temporal** is a strong default once a hand-rolled state machine starts accumulating retries, timeouts, and compensations you'd otherwise have to build and test yourself — its workflow-as-code model handles all of that with deterministic replay. Not worth the operational weight for a 2-step workflow.

**Pros**: workflow is explicit and inspectable. Easier to add steps, branch, debug.

**Cons**: the orchestrator is a new deployable, a new failure domain, and a new coupling point.

### Non-negotiables for any saga

- **Every forward step has a compensating step.** Write them at the same time. A saga with no compensation for step N is a bug waiting for step N+1 to fail.
- **Compensations are idempotent.** They will be retried. `refund(paymentId)` on an already-refunded payment must be a safe no-op.
- **Compensations are not perfect rollbacks.** "Refund" is not the inverse of "charge" — the money moved, a fee was incurred, an audit trail exists. Design compensations as *business reversals*, not technical undo.
- **Saga state is persisted and observable.** For orchestration, the orchestrator persists state. For choreography, emit `SagaStepCompleted` events so the journey is reconstructable. A saga you cannot inspect is a saga you cannot operate.
- **Timeouts at every step.** A saga step that hangs forever wedges the whole workflow. Bound every wait.

## Review checklist

When reviewing a PR involving messaging, cross-service calls, or cross-aggregate workflows, check:

- [ ] **At-least-once actually holds** — two halves of the same concern, check both:
  - [ ] **Idempotency**: every consumer and retryable endpoint has an explicit idempotency strategy (key + table, or natural state check). Not "probably idempotent" — explicitly so.
  - [ ] **Offset commit after DB commit** — never the reverse. External side effects inside a transactional path use a downstream idempotency key or their own outbox.
- [ ] **No dual writes**: a use case that writes to DB + publishes to Kafka uses the outbox. No `save(); publish();` in the same method.
- [ ] **Transaction boundary**: `@Transactional` lives on the use case, not the controller, not the repo.
- [ ] **Retries are bounded and jittered**: no `while(true) { retry }`, no fixed delays, exponential + jitter + cap + max attempts.
- [ ] **DLQ exists** for every consumer, with full context in headers and a replay path.
- [ ] **Error classification**: permanent errors go straight to DLQ (Spring Kafka `addNotRetryableExceptions`), transient errors retry.
- [ ] **Delivery semantics stated honestly**: "at-least-once + idempotency" not "exactly-once" unless the whole pipeline is Kafka-to-Kafka with EOS.
- [ ] **Sagas have compensations** for every forward step, and those compensations are idempotent.
- [ ] **Outbox retention is designed, not deferred**: partitioned + scheduled drop, or an equivalent O(1) cleanup. Cleanup success and table size are metrics with alerts.
- [ ] **Observability wired**: outbox lag, DLQ depth, retry counts, saga step durations, cleanup freshness. See the `java-observability` skill.
- [ ] **Replay tooling exists** for the outbox and the DLQs — not a TODO, an actual tool.

## Anti-patterns to refuse

- **Dual writes** (`repo.save(); kafka.send();` in the same method). Non-negotiable — this is a bug, not a style preference.
- **Unbounded retry loops**. A retry with no budget is a way to pretend the downstream is always healthy.
- **"We'll add idempotency later."** No. Retrofitting idempotency onto a consumer that has already been in production is a migration project with real incident risk. Build it in on day one.
- **Logging-only error handling on a consumer.** A caught-and-logged exception that does not retry and does not DLQ is a silent data-loss bug.
- **Manual offset commits before processing.** `commitSync()` at the top of the handler is at-most-once semantics dressed up as at-least-once — and worse, it looks correct at a glance.
- **Sagas with no compensations.** "We'll just alert on failure" is not a compensation strategy.
- **"Exactly-once" claims for pipelines that write to a DB.** Push back. The semantics are at-least-once + idempotency; naming it correctly is part of the design.
- **Retrying on `DeserializationException` or `MethodArgumentNotValidException`.** These are permanent errors. Retrying them is wasted cycles and partition blockage.
- **An outbox with no lag metric.** An outbox you cannot see falling behind is an outbox you will discover falling behind during an incident.

## Cross-references

- **Transactional boundaries and use-case layering**: `hexagonal-ddd-java` (the use case is the transactional unit because the application layer owns orchestration).
- **Metrics, traces, and logs for outbox lag, DLQ depth, retry counters, saga state**: `java-observability`.
- **Testing messaging reliability** (Testcontainers Kafka, consumer idempotency tests, outbox integration tests, saga compensation tests): `java-testing-strategy`.
- **Scaffolding for outbox tables, retry topologies, and saga state persistence**: `hexagonal-module-bootstrap`.
