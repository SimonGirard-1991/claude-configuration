# Retries, backoff, jitter, and dead letter queues

Reference for the `java-reliability-messaging` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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
