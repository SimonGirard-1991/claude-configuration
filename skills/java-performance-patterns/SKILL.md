---
name: java-performance-patterns
description: Use when profiling, optimizing, or reviewing performance-sensitive paths in a Java backend — caching layers (Caffeine, Redis), pagination at scale, database and HTTP batching, N+1 query detection, virtual threads vs bounded pools for I/O vs CPU work, HikariCP sizing, and index/execution-plan discipline. The headline rule is profile-first: no recommendation without a flame graph, allocation profile, or execution plan that justifies it. Skip for throwaway scripts, spikes, non-Java code, or "just make it faster" requests with no measurement.
---

# Java Performance Patterns

This skill encodes the rules for making Java backends **fast where it matters** without guessing. The defining failure mode it prevents: a well-meaning engineer tunes a GC flag, doubles a pool size, or bolts on a cache because a dashboard looked slow, and either moves the bottleneck elsewhere, masks a real bug, or makes things worse under a different load shape. Every pattern in this skill is gated on evidence — a profile, a plan, a metric — not intuition.

Defaults assume Spring Boot + jOOQ + Postgres/MySQL + a JVM on a current LTS. The principles carry to Quarkus and Micronaut; the instrumentation hooks differ.

## When to use

- A real latency/throughput regression is under investigation, with traces/logs/metrics in hand.
- Designing a new read path that will hit tables with non-trivial row counts (>10k) or fan-in patterns (aggregations, joins across aggregates).
- Designing a write path with high fan-out to a database or broker (bulk imports, batch jobs, backfills).
- Choosing between synchronous blocking I/O, virtual threads, and reactive for an I/O-bound workload.
- Reviewing a PR that adds a cache, changes pagination, introduces async boundaries, or touches connection-pool configuration.
- Post-incident: saturation, thread exhaustion, pool starvation, slow query, OOM, GC pauses.

## When NOT to use

- "Make it faster" with no measurement attached. The correct first step is profiling, not pattern selection.
- Throwaway scripts, spikes, or one-shot jobs where operational cost dominates developer cost.
- Non-Java code (principles transfer; tools do not).
- JVM tuning questions without a profile. The right response is "let's profile first," not a set of `-XX:` flags.

## Core principles

1. **Measure before you optimize. Measure after you optimize.** No recommendation survives contact with "we don't have a profile yet." The tools are JFR, async-profiler, APM traces (Datadog / Dynatrace / Honeycomb), and database execution plans. Use them.
2. **The bottleneck is almost never where you think it is.** The intuition-driven fix pessimizes a different code path while leaving the real hotspot untouched. Let the profile pick the target.
3. **Tuning without a baseline is fiction.** Record p50/p95/p99 latency, throughput, CPU, memory, and GC time **before** the change. If you cannot prove the change helped, it did not.
4. **Latency is a distribution, not an average.** Averages hide the long tail. Optimize for p99 (and sometimes p999) — that is what users and SLOs feel. An average that looks fine with a p99 cliff is still a production problem.
5. **The cheapest query is the one you don't run.** Caches, batching, and keyset pagination all exist to cut work, not to do the same work faster. Prefer work elimination over micro-optimization.
6. **Performance features that cannot be observed regress silently.** A cache without hit-ratio metrics, a pool without saturation metrics, a batch without throughput metrics — each is a time bomb. Instrumentation is part of the feature, not a follow-up.
7. **Correctness first. A fast wrong answer is a bug, not an optimization.** Stale cache reads, torn pagination, dropped batch items, and unsafe concurrent access are bugs that wear performance clothing.
8. **"Scale" is not a justification on its own.** Many patterns that are correct at 100 QPS are also correct at 10k QPS — premature optimization for hypothetical scale produces complexity that makes the real future optimization harder. The exception is any pattern whose cost scales with data size or request volume (offset pagination, N+1 queries, unbounded caches, unbounded retry loops) — those must be right from day one, because the failure mode arrives on its own schedule, not yours.

## Profiling — the non-negotiable starting point

Before choosing any pattern in this skill, answer three questions with data:

1. **Where is time spent?** CPU-bound or I/O-bound? Flame graph from async-profiler or JFR, broken down by thread state.
2. **Where is memory going?** Allocation profile. A high allocation rate is a leading indicator of GC pressure even when heap looks fine.
3. **What does the database see?** Slow-query log, `pg_stat_statements` / MySQL performance schema, `EXPLAIN (ANALYZE, BUFFERS)` for the specific query under suspicion.

If the answer to any of the three is "I don't know," fix that before picking a pattern.

**Tools by layer**:

- **JVM CPU/allocation**: async-profiler (recommended), JFR, perf (Linux). Datadog Continuous Profiler / Dynatrace / Pyroscope if on a platform.
- **Distributed traces**: OpenTelemetry spans end-to-end; tail-sample errors and slow traces. See `java-observability` for the instrumentation rules.
- **DB**: `EXPLAIN (ANALYZE, BUFFERS)` for plan + actual row counts + I/O. `pg_stat_statements` for top queries by total time.
- **Thread/lock contention**: async-profiler `-e lock` or JFR "Java Monitor Blocked" events.
- **Heap/GC**: GC logs, JFR GC events, heap dumps for leak-hunting.

**Output of a profiling session is a target**, e.g., "92% of the p99 latency is in a single SQL query that does a sequential scan on `orders` because the `(customer_id, created_at)` index is missing." That sentence tells you exactly which pattern to reach for. A vague "it's slow" does not.

## Caching

Caching is work elimination. It is also a new correctness surface (staleness, invalidation, memory pressure) and a new failure mode (hot keys, thundering herds, cache stampedes). Apply it deliberately.

### Caffeine (in-process, default)

Use Caffeine for in-process caching when (a) the data is cacheable, (b) the hit-ratio will plausibly exceed 50% at steady state, and (c) staleness is bounded and acceptable.

**Non-negotiables**:

- **Bounded size.** `maximumSize(n)` or `maximumWeight(w)` — never unbounded. An unbounded cache is a memory leak with a rebrand.
- **Explicit TTL.** `expireAfterWrite(Duration)` (entry invalidates regardless of use) or `expireAfterAccess(Duration)` (LRU-ish). Pick based on staleness tolerance.
- **Hit/miss/eviction metrics exposed via Micrometer.** `Caffeine.newBuilder().recordStats()` + `CaffeineCacheMetrics.monitor(registry, cache, "cache.name")`. Without metrics the cache is invisible — you cannot tell if it is helping, hurting, or dead.
- **Explicit invalidation strategy documented on day one.** What writes invalidate which keys? If the answer is "we hope TTL is short enough," the TTL is doing invalidation's job.
- **Loader semantics are part of correctness.** `LoadingCache` with a synchronous loader serializes duplicate concurrent misses (good — prevents stampede). `AsyncLoadingCache` does the same asynchronously. Manual `getIfPresent` + `put` without synchronization re-opens the stampede.

```java
Cache<OrderId, Order> cache = Caffeine.newBuilder()
    .maximumSize(10_000)
    .expireAfterWrite(Duration.ofMinutes(5))
    .recordStats()
    .build();

CaffeineCacheMetrics.monitor(meterRegistry, cache, "orders.cache");
```

**Review red flags**:

- `Caffeine.newBuilder().build()` with no `maximumSize`.
- No `recordStats()` or no Micrometer binding.
- Writes that update the DB but do not invalidate or update the cache.
- A TTL chosen by feel rather than by "how stale is acceptable for this caller."

### Redis (distributed)

Use Redis when multiple instances must share cache state, or when the working set is too large for in-process caching. Costs: a network hop, a new failure domain, serialization overhead.

**Defaults**:

- **Explicit TTL on every key.** `SETEX` / `SET ... EX`. Keys without TTL accumulate forever.
- **Serialization is not free.** JSON is portable but expensive. For hot paths, consider a compact binary format (MessagePack, Protobuf) — but profile first.
- **Cache stampede protection.** A popular key that expires while 1,000 requests are in flight will cause 1,000 cache misses and 1,000 DB hits simultaneously. Mitigations: probabilistic early expiration, per-key locking, `SINGLEFLIGHT`-style coalescing.
- **Distinguish cache from primary store.** `@Cacheable` is acceptable for cache; Redis as a primary data store has different operational requirements (persistence, backups, replication) and belongs in a different design conversation.
- **Client-side circuit breaker.** Redis outages should degrade to DB reads, not cascade into failures. A dead Redis must not take the service down.

### Patterns that look like caching but are not

- **Memoization across a single request**: this is a local variable or a request-scoped map, not a cache. No TTL, no eviction, no metrics needed.
- **Precomputed materialized views**: this is a read model, see the CQRS section.
- **DB query result caching via ORM second-level cache**: generally more trouble than it is worth with jOOQ; if using JPA, know the invalidation rules cold before enabling it.

## Pagination

Pagination is where the difference between "works in dev" and "falls over in prod" shows up most reliably.

### Keyset (seek) pagination — the default

Every `LIMIT` / page-size query on a table that can grow past a few thousand rows should use keyset pagination.

**Why**: offset pagination scans everything it skips. `OFFSET 100000 LIMIT 20` requires the database to produce 100,020 rows and discard the first 100,000. Latency grows linearly with page number. Keyset pagination uses `WHERE (sort_col, id) > (:lastSortCol, :lastId) LIMIT 20` — constant time per page given the right index.

```sql
-- First page
SELECT * FROM orders
WHERE customer_id = :c
ORDER BY created_at DESC, id DESC
LIMIT 20;

-- Subsequent pages — client passes back (created_at, id) of the last row seen
SELECT * FROM orders
WHERE customer_id = :c
  AND (created_at, id) < (:last_created_at, :last_id)
ORDER BY created_at DESC, id DESC
LIMIT 20;
```

**Index requirement**: the `ORDER BY` columns must be a prefix of an index. `(customer_id, created_at DESC, id DESC)` for the query above.

**API contract**: return the keyset as an opaque `next_cursor` (base64-encoded `(sort, id)` tuple). Do not expose `OFFSET` or `page=N` in new APIs — they bake the scaling failure into the contract.

**jOOQ** makes this natural with `seek(...)`:

```java
dsl.selectFrom(ORDERS)
   .where(ORDERS.CUSTOMER_ID.eq(c))
   .orderBy(ORDERS.CREATED_AT.desc(), ORDERS.ID.desc())
   .seek(lastCreatedAt, lastId)
   .limit(20)
   .fetch();
```

### When offset pagination is acceptable

- Admin tools and internal dashboards over small tables (< a few thousand rows).
- Pages 1–10 of a UI where the user almost never navigates past page 5 — and the table is indexed enough that early pages are fast.
- Never for a public API. Public APIs constrain future scale; a public offset-pagination contract is a liability you will pay for later.

### Total-count traps

`SELECT COUNT(*)` alongside a paginated query is a full-table (or full-filtered-set) count. At scale this dominates the request. Options:

- Don't show total counts. "Load more" / infinite scroll works without one.
- Show an approximate count from stats (`pg_class.reltuples`, `ANALYZE` output) — unfiltered table only, useless for `WHERE`-bounded counts, and only as fresh as the last `ANALYZE`.
- Cache the count separately with a TTL.

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

## CQRS read models — an escalation, not a default

Command/Query Responsibility Segregation (a separate read model optimized for queries, asynchronously projected from the write model) is a real tool, not a default. It is justified when:

- The read shape structurally diverges from the write shape — aggregated dashboards, cross-aggregate reports, search over denormalized joins.
- Read latency requirements cannot be met by the write-model schema even with good indexes.
- Read and write loads are so imbalanced that a single store cannot serve both efficiently.

It is **not** justified when:

- A single `findAll` is slow. Fix the query, add an index, or paginate correctly first.
- "We might want analytics later." Build it when you need it; a read model maintained for a hypothetical consumer is pure overhead.
- The team does not have the operational capacity for a second store and a projection pipeline. A projection that falls behind silently is worse than a slow query.

Costs: eventual consistency (the read model lags the write), a new failure domain (the projector), a new schema to evolve, and a new replay story when schemas change. Design all three before introducing one.

## Async boundaries and threading

Choose the concurrency model based on the workload shape, not on fashion.

### I/O-bound work — use virtual threads (Project Loom)

For workloads dominated by blocking I/O (DB calls, HTTP calls, broker publishes), virtual threads are now **the default on a current LTS (JDK 25)**. They let you write straightforward synchronous code (`var result = client.call(...)`) without paying the platform-thread cost, and they scale to hundreds of thousands of concurrent blocked operations.

**What changed with JDK 24 / JDK 25 LTS**: pre-JDK 24, JDBC drivers' `synchronized` internals meant virtual threads pinned on nearly every DB call — so "use virtual threads for I/O" had a hidden asterisk big enough to disqualify it for transactional request paths. JEP 491 (shipped in JDK 24, included in JDK 25 LTS) eliminates that pinning for nearly all `synchronized` usage. On the declared baseline, **virtual threads + blocking JDBC is genuinely the default**, not the aspirational answer.

**When they shine**: request handlers, Kafka listeners, HTTP clients, JDBC calls — anywhere a thread spends most of its time waiting on something external.

**Gotchas**:

- **Synchronized used to pin the carrier thread; on JDK 25 it does not.** JEP 491 covers nearly all `synchronized` usage. Residual pinning to watch for: native frames, `Object.wait` inside `synchronized`, and a handful of JDK internals not yet migrated. If the deployment target is still JDK 21 LTS, prefer `java.util.concurrent.locks.ReentrantLock` across I/O and audit `synchronized` hot paths — that caveat is obsolete on JDK 25+.
- **ThreadLocals do not scale the same way.** With millions of virtual threads, a per-thread-local allocation becomes per-virtual-thread. Use **`ScopedValue`** (finalized in JDK 25 via JEP 506) for per-request/per-task context — it inherits into forked subtasks without per-virtual-thread allocation overhead. On JDK 21 targets, fall back to lazily-allocated `ThreadLocal`s.
- **`StructuredTaskScope` is still preview.** Despite being Loom-adjacent and tempting to reach for alongside virtual threads, Structured Concurrency is still a preview API as of JDK 25 (JEP 505/525, re-preview in JDK 26). Do not use it on production paths yet — the shape will still shift. Stick with `ExecutorService` + `Future`/`CompletableFuture` for now.
- **Not a throughput multiplier on CPU-bound code.** Virtual threads do not speed up computation — they only remove the cost of blocking. A CPU-bound task on a virtual thread is the same work on a different thread abstraction.

Spring Boot enables virtual threads with `spring.threads.virtual.enabled=true` on a supporting version. Verify and profile — on older JDKs, confirm carrier threads are not pinned under load; on JDK 25+, confirm observed concurrency matches the virtual-thread model.

### CPU-bound work — dedicated bounded pool

A bounded `ExecutorService` sized to the number of cores (plus or minus) is the right shape for CPU-bound tasks: data transformation, hashing, compression, serialization at scale.

```java
int cores = Runtime.getRuntime().availableProcessors();
ExecutorService pool = Executors.newFixedThreadPool(cores);
```

Do not use virtual threads for CPU-bound work — they will happily schedule more work than you have cores to run, and the only result is scheduling overhead plus OS contention.

### Reactive (Project Reactor, WebFlux, Mutiny) — the shrinking niche

Reactive is still the right tool for specific shapes: streaming a million-row response, backpressure-sensitive pipelines, websocket fan-outs. It is **no longer the default for HTTP request handlers** — virtual threads provide the same concurrency with straightforward code. If you are not in a reactive codebase already, the burden of proof for adopting reactive style is on the proposer: show the workload that needs it.

### Never block an event loop

If the codebase uses Netty, Reactor, or any event-loop-based runtime, a synchronous blocking call on an event-loop thread freezes the whole server under load. Use `subscribeOn(Schedulers.boundedElastic())` or the equivalent, or — better — migrate to virtual threads where the answer is "just let it block."

## Connection pooling

HikariCP is the default. The only remaining interesting question is pool size.

**Pool size is calculated, not guessed.** A common starting heuristic is:

```
pool_size = ((core_count * 2) + effective_spindle_count)
```

For modern databases on SSD/NVMe, `effective_spindle_count ≈ 1`. For a 4-core DB host, that is ~9. This is a **starting point**, not a target — tune empirically against real load.

**Caveat on the formula**: it is calibrated for short, CPU-bound transactions. Under long-lived or I/O-bound queries (calls into PL/pgSQL, large result sets, chatty transactions), the formula underestimates and the pool needs to be larger to keep cores busy. The upper bound is still DB `max_connections`, not wishful thinking.

**Split pools for mixed workloads.** When a service runs a few long-running reports or batch jobs alongside many short transactional queries, a single oversized pool couples their failure modes — the batch path holds connections long enough to starve the realtime path. Wooldridge's own guidance for mixed workloads is two pools: one sized tightly for the realtime path, one bounded explicitly for the batch path, each with its own `connectionTimeout`. The two pools share the DB `max_connections` budget; do the arithmetic across both.

**An oversized pool is usually worse than an undersized one.**

- DB CPU saturates long before the pool fills.
- Connection context-switching costs rise.
- Locks held by one connection block many others.
- Autovacuum and replication fall behind the write volume.

**Observe**: pool-usage metrics (`hikaricp.connections.active`, `hikaricp.connections.pending`, `hikaricp.connections.timeout`) are critical SLIs for any DB-bound service. A pending queue with non-zero depth at p95 is the pool telling you it is undersized — or the queries telling you they are too slow.

**`connectionTimeout`**: the time a request waits for a connection before failing. Default 30s is too generous; 2–5s fails fast and protects the request budget.

**`maximumPoolSize` per instance × number of instances ≤ DB max connections.** Do the arithmetic. A 20-connection pool × 50 pods = 1000 connections on the DB — is that within budget?

## Indexing and execution plans

If a query touches a table with more than ~10k rows, verify its execution plan. Always.

**`EXPLAIN ANALYZE` is the authoritative answer.** `EXPLAIN` alone shows the planner's guess; `EXPLAIN ANALYZE` runs the query and reports actual row counts, timing, and I/O. In Postgres, prefer `EXPLAIN (ANALYZE, BUFFERS)` to see buffer hit/miss — a cold cache hides a sequential scan that looks fine on a warm run.

**Red flags in a plan**:

- `Seq Scan` on a large table with a selective `WHERE`.
- `Rows Removed by Filter` in the thousands or millions — the index is not selective enough, or the wrong index was chosen.
- A plan where `rows` (estimated) and `actual rows` diverge by orders of magnitude — stats are stale, run `ANALYZE`.
- `Nested Loop` over two large inputs — the planner should prefer `Hash Join` or `Merge Join`; something is off.

**Index hygiene**:

- Composite index column order matters: `(tenant_id, created_at)` serves `WHERE tenant_id = ? ORDER BY created_at` efficiently; the reverse does not.
- Over-indexing is a write-path cost. Every index adds per-row work on `INSERT`/`UPDATE`.
- `pg_stat_user_indexes` / MySQL equivalents show which indexes are never used — candidates for removal.
- Partial indexes (`WHERE status = 'active'`) and expression indexes (`LOWER(email)`) shrink index size and speed up specific queries.

**Missing indexes are the single most common cause of production latency cliffs.** A query that was fine in dev falls over in prod because prod has 1000× the rows. Check the plan for every new query on a growing table, not just the slow ones.

## Read replicas

Useful for read-heavy workloads where the primary is CPU- or IOPS-bound. Costs:

- **Replication lag.** Reads from a replica may see state from seconds (or minutes, under load) ago. Code that reads its own writes on a replica will see staleness or appear broken.
- **Failover semantics.** Promotion of a replica to primary under failover is a real ops discipline — test it, don't hope it.
- **Routing logic.** Which reads go to the replica? Typically long-running analytical reads, reports, unauthenticated public reads. Transactional reads and read-your-own-writes stay on the primary.

**Never introduce replicas without explicit lag handling in code.** `@Transactional(readOnly = true)` to a replica for a read that immediately follows a write is a bug generator.

## Common performance bugs that look like patterns

- **"Let's add a cache"** when the actual problem is a missing index. Profile first.
- **"Let's switch to reactive"** when the actual problem is a synchronous call holding a JDBC connection. Virtual threads + the existing synchronous code usually solves this with far less churn.
- **"Let's bump the pool size"** when the pool is full because every query holds a connection for 5 seconds. Fix the queries.
- **"Let's add a read replica"** when the primary is 90% idle and the slow queries are 3 unindexed scans. Replicas move load; they do not speed up slow queries.
- **"Let's tune GC"** when allocation rate is 2 GB/s because of JSON serialization on the hot path. Reduce allocation; GC will take care of itself.
- **"Let's batch harder"** on a path where p99 latency matters and the current batch size is already well past the point where added batching only adds queueing delay.
- **"Let's precompute a materialized view"** for a query that would be fine with a composite index.

Each of these has the same root cause: applying a pattern from the toolkit before knowing what the bottleneck actually is.

## Review checklist

When reviewing a PR that claims a performance improvement — or that introduces a cache, pagination, async boundary, batch, or pool change — check:

- [ ] **Profile or measurement attached.** A flame graph, execution plan, trace, or before/after latency numbers. If absent, the change is unjustified.
- [ ] **Baseline numbers present.** p50/p95/p99 latency and throughput before the change. A single "it's faster now" is not a baseline.
- [ ] **Correctness invariants preserved.** Cache invalidation path named. Pagination tested for torn reads / missed rows at boundaries. Batching handles partial failure.
- [ ] **Observability wired.** Caches emit hit/miss/eviction metrics. Pools emit active/pending/timeout metrics. Batches emit throughput and failure metrics. New async boundaries emit queue-depth and rejection metrics.
- [ ] **Pagination uses keyset** on any query over a table that can grow past a few thousand rows. Offset pagination justified explicitly if used.
- [ ] **No N+1** in the new code. Test enforces the expected query count for list endpoints.
- [ ] **Query plan reviewed** for any new query on a table with >10k rows. `EXPLAIN (ANALYZE, BUFFERS)` output in the PR description is a good habit.
- [ ] **Pool sizes calculated**, not guessed. `maximumPoolSize × instance_count ≤ DB max_connections`. `connectionTimeout` is tight enough to protect the request budget.
- [ ] **Virtual threads used for I/O**, dedicated bounded pool for CPU work, no blocking calls on event loops.
- [ ] **Cache has bounded size, TTL, recorded stats, documented invalidation.** No `Caffeine.newBuilder().build()` with defaults.
- [ ] **No speculative optimization.** The PR does not add complexity for a workload that has not been measured.

## Anti-patterns to refuse

- **Tuning without a profile.** "We bumped `-XX:MaxGCPauseMillis`" with no GC log attached is not an optimization, it is a hope.
- **Unbounded caches.** A `HashMap` used as a cache is a memory leak. A `Caffeine` without `maximumSize` is the same bug with a nicer API.
- **Offset pagination on a growing table in a public API.** The page-100 performance cliff is baked into the contract.
- **N+1 in a loop over a collection.** Refuse in review. Every time.
- **Blocking calls on a reactive event loop.** Freezes the server under load.
- **`while (true) { /* do work */ }` without bounded backpressure.** A fast producer and a slow consumer is a memory leak or a dropped-data bug, depending on queue semantics.
- **`synchronized` blocks containing I/O on a virtual-thread-heavy path** (on JVM versions where this still pins). Migrate to `ReentrantLock` or redesign.
- **Pool sizes "set to 100 because that seemed safe"** with no DB `max_connections` budget check.
- **"We need a cache"** without a hit-ratio hypothesis. If the steady-state hit ratio will be 10%, the cache is net negative — latency on miss plus memory cost, no gain on hit.
- **Read replicas without lag handling.** Read-your-own-writes bugs after a `POST` are the classic symptom.
- **Tuning linger.ms/batch.size to "improve throughput"** on a latency-sensitive path. They trade latency for throughput; the tradeoff must be intentional.
- **Using reactive style** on a new service because "it scales better" without a workload that justifies it. Virtual threads have erased the default case for reactive in most request handlers.

## Cross-references

- **Metrics for cache hit ratios, pool saturation, outbox lag, query durations, GC pauses**: `java-observability`.
- **Per-layer testing (assertions on query counts, Testcontainers-backed repository tests, async timing)**: `java-testing-strategy`.
- **Transactional boundaries, batching inside a use case, outbox batching**: `java-reliability-messaging`.
- **Where caches, projectors, and read models fit in the hexagon**: `hexagonal-ddd-java` (read models are adapters over a query port; caches are infrastructure, never in the domain).
- **Scaffolding for jOOQ batch repositories, Caffeine wiring, HikariCP config**: `hexagonal-module-bootstrap`.
