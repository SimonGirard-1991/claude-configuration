# Transactional boundaries and idempotency

Reference for the `java-reliability-messaging` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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
  outbox.enqueue(OrderPlacedEvent.from(order)); // same tx — see outbox.md
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
- "We use exactly-once semantics." See `delivery-semantics.md` — EOS only holds within Kafka's own read/process/write cycle. The moment you cross to a DB, you're back to at-least-once + idempotency.
- "Our DB has a unique constraint." Unique constraints catch the duplicate *after* the redundant work is done (external API already called, email already sent). Idempotency must short-circuit before side effects.
