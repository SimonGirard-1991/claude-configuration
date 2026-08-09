# Delivery semantics — an honest taxonomy

Reference for the `java-reliability-messaging` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Delivery semantics — an honest taxonomy

### At-most-once

Fire-and-forget. Message may be lost, never duplicated. Rarely acceptable; reserve for truly non-critical signals (cache invalidation hints, debug telemetry) where loss is cheaper than the complexity of the alternative.

### At-least-once (the default)

Message is delivered one or more times. **The consumer is responsible for deduplication via idempotency.** This is what you should assume unless proven otherwise.

Kafka defaults: `enable.auto.commit=false`, commit offsets **after** successful processing. A crash between processing and commit means reprocessing — which your idempotency handles.

**Commit ordering is the subtle trap.** For at-least-once to actually hold, the offset commit must be *causally after* the DB write commits. If you commit the offset first and then the DB write fails, the message is lost — that is at-most-once semantics dressed up as at-least-once, and it looks correct on a code review. Two correct patterns:

1. **DB commit first, then offset commit** (the simple form). A crash between them replays the message; idempotency absorbs the duplicate. This is what `enable.auto.commit=false` + "commit after successful processing" buys you — but only if you mean it, and the processing path does not itself commit the offset earlier.
2. **Compose Kafka's transactional producer with the DB transaction manager.** The Kafka offset commit participates in the same transactional scope as the DB write; a failure on either side rolls the other back. Historically this was wired via `ChainedKafkaTransactionManager`, which newer Spring Kafka de-emphasizes in favor of composing `KafkaTransactionManager` with the DB `PlatformTransactionManager` directly (or `@Transactional` with a transactional Kafka producer). The concept is what matters; pin the mechanism to your Spring Kafka version. Stronger guarantees, more moving parts.

Pattern 1 + Pattern A (processed_messages; Pattern A is defined in `transactions-and-idempotency.md`) is what most services should reach for. Pattern 2 is worth it when the idempotency key is hard to derive or the side effects are especially expensive. **Either way, never commit the offset before the DB commits succeed.**

### Exactly-once — the nuanced truth

Kafka's "exactly-once semantics" (EOS) holds **only** within a Kafka-to-Kafka pipeline using the transactional producer API + `isolation.level=read_committed` on consumers. The moment the consumer writes to a **database, external API, or any non-Kafka sink**, EOS **does not apply** — you are back to at-least-once + idempotency.

**Consequences**:

- A consumer that reads from Kafka and writes to Postgres is at-least-once. Treat it as such.
- A Kafka Streams topology that reads from Kafka and writes to Kafka can be exactly-once (`processing.guarantee=exactly_once_v2`). Worth it for stream-processing pipelines.
- "We need exactly-once for our payment flow" almost always means "we need idempotency + at-least-once." The idempotency key + processed-messages table is the implementation, not EOS.

**Bottom line**: stop reaching for EOS. Design for at-least-once + idempotency. It is simpler, correct, and honest about what the infrastructure actually guarantees.
