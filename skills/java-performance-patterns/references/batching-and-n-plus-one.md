# Batching and N+1 elimination

Reference for the `java-performance-patterns` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Batching

**Never make N calls in a loop when one batched call is possible.** This applies to DB writes, broker publishes, HTTP calls, and RPCs.

### Database writes

- **jOOQ**: `batchInsert(records)`, `batchUpdate(records)`, `batchStore(records)`. These use JDBC batching under the hood.
- **Plain JDBC**: `PreparedStatement.addBatch()` + `executeBatch()`. Set `reWriteBatchedInserts=true` on the Postgres JDBC URL to get the 10–100× speedup from multi-row `INSERT`.
- **Batch size**: 500–5000 rows per batch is a reasonable starting range; tune empirically. Too-small batches waste round-trips; too-large batches inflate memory, lock duration, and WAL spikes.
- **Chunk long-running batches** into committed sub-batches so a failure 80% through a million-row insert does not roll back everything.

### Bulk ingest (Postgres) — COPY supersedes batched INSERT

For backfills, imports, seed jobs, and batch jobs that write tens of thousands of rows or more, **`COPY` is typically 10–100× faster than batched `INSERT`** — it bypasses SQL parsing and per-row planning, and streams rows directly into the table. Reach for it before reaching for a larger JDBC batch size.

- pgjdbc exposes it via `CopyManager` / `copyIn` (obtainable from the Postgres `Connection` via `unwrap(PGConnection.class).getCopyAPI()`).
- `COPY ... FROM STDIN (FORMAT binary)` for maximum throughput; `FORMAT csv` when ergonomics matter more than the last 20% of speed.
- Trade-offs: `COPY` does not fire triggers identically to `INSERT` (check per-statement vs per-row semantics for your triggers), does not return generated keys trivially, and is awkward across many small transactions. It shines for a few large transactions — the opposite profile of the retryable message-consumer write path.
- For idempotent bulk loads: stage to a `_staging` table via `COPY`, then merge with a single `INSERT ... ON CONFLICT DO UPDATE`. Gives you the speed of `COPY` with the correctness of an upsert.

If the code path is "batch job that ingests a file" and the current answer is `batchInsert` in a loop, `COPY` is almost certainly the right tool.

### Kafka producers

Tune `linger.ms` and `batch.size` together. Defaults (`linger.ms=0`, `batch.size=16384`) optimize for low latency and poor throughput — one message per produce request. For throughput-sensitive producers:

- `linger.ms=5–50`: wait briefly to fill a batch. Latency cost is bounded; throughput gain is often 5–10×.
- `batch.size=32768–262144`: larger batches pack more messages per request.
- `compression.type=lz4` or `zstd`: compression ratio on batched payloads is much higher than single messages.

These knobs trade latency for throughput. Pick intentionally, document the choice, and measure.

### HTTP / RPC

If the downstream API supports a batch endpoint, use it. `POST /items/batch` with 100 items in one call beats 100 individual `POST /items` calls by one to two orders of magnitude when the latency is WAN-dominated.

### What batching is not

- **Batching for its own sake.** A batched call that forces you to hold state across unrelated requests or invent artificial flush triggers is probably the wrong abstraction. Profile to confirm the per-call overhead is worth the added complexity.
- **Client-side batching of unrelated requests.** Coalescing two different users' requests into one DB batch because it looks neat is a latency-leak waiting for the quiet user to get stuck behind the noisy one.

## N+1 queries

The single most common, single most preventable performance bug in any backend that talks to a database. **Mandatory code review item.**

### What it looks like

```java
// Red flag: one query for the list, N more for each item's children.
var orders = orderRepo.findByCustomer(customerId);  // 1 query
for (Order o : orders) {
  o.setItems(itemRepo.findByOrderId(o.id()));        // N queries
}
```

### How to catch it

- **SQL logging in tests.** Enable slow-query or all-query logging in the integration-test profile. Assert query counts on hot paths (`datasource-proxy` or Hibernate's `Statistics` are easy hooks).
- **Explicit test**: `@Test void loadingOrdersWithItemsIssuesAtMostTwoQueries()`. Guard the contract explicitly.
- **Tracing**: an APM trace on a list endpoint that shows dozens of identical queries in a fan-out is an N+1 you can see at a glance.
- **jOOQ** makes it visible because the SQL is explicit in the code — but the loop form above still compiles. The review still matters.
- **JPA/Hibernate**: particularly prone, because lazy loading makes N+1 invisible in the code. Enable `hibernate.generate_statistics` + alerts on `query.count` per request.

### How to fix it

- **Single query with a join**: `LEFT JOIN order_items ON order_items.order_id = orders.id`, then assemble aggregates in application code.
- **Two queries with an `IN`**: fetch orders, then `SELECT * FROM items WHERE order_id IN (:ids)`. Two queries total, constant regardless of list size.
- **jOOQ `MULTISET`**: returns nested collections as a single round-trip, preserving aggregate structure with no manual assembly. Works across most dialects jOOQ supports — it is emulated via JSON/array aggregation in the underlying DB, so verify on your specific dialect before relying on it in a hot path.

Pick based on selectivity and payload size. Join is cheapest for small parent-to-child ratios; `IN` is cheapest for sparse reads over a cached parent set; `MULTISET` is cleanest when you want strongly-typed nested results.
