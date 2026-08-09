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

## Reference map

Open a reference when you are implementing a mechanism, or when judging one in
review needs its detail.

| I need to… | Open | Contains |
|---|---|---|
| Set a transaction boundary, or make a consumer idempotent | `references/transactions-and-idempotency.md` | Use-case-level transaction rules, idempotency key + table, natural state-check idempotency, what does *not* count |
| Update a database and publish an event atomically | `references/outbox.md` | Outbox schema, write path inside the transaction, Debezium CDC vs polling publisher, non-negotiables, when it is overkill |
| Configure retries, or design a DLQ | `references/retries-and-dlq.md` | Backoff parameters and jitter, Spring Retry for HTTP, Spring Kafka consumer retries, DLQ payload design, retryable vs poison classification |
| Reason about at-least-once / exactly-once guarantees | `references/delivery-semantics.md` | The three semantics, why Kafka EOS stops at the DB boundary, what to promise a stakeholder |
| Design a cross-aggregate or cross-service workflow | `references/sagas.md` | Choreography (default) vs orchestration (escalation), mandatory compensations |

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
