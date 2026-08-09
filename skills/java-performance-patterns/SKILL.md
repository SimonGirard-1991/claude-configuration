---
name: java-performance-patterns
description: >-
  Use when profiling, optimizing, or reviewing performance-sensitive paths in a Java
  backend — caching layers (Caffeine, Redis), pagination at scale, database and HTTP
  batching, N+1 query detection, virtual threads vs bounded pools for I/O vs CPU work,
  HikariCP sizing, and index/execution-plan discipline. The headline rule is
  profile-first: no recommendation without a flame graph, allocation profile, or
  execution plan that justifies it. Skip for throwaway scripts, spikes, non-Java code,
  or "just make it faster" requests with no measurement.
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

## Reference map

Profile first: for code that already runs, a recommendation needs a profile,
allocation dump or execution plan behind it. That is a rule about **evidence for
a claim**, not a gate on reading — when you are designing new work or reviewing
someone else's, no profile exists yet and you should still open the reference
that covers what the change touches.

| The profile points at (or you are designing/reviewing)… | Open | Contains |
|---|---|---|
| Repeated expensive reads | `references/caching.md` | Caffeine sizing and eviction, Redis and its failure modes, cache metrics, patterns that only look like caching |
| A slow or deepening list endpoint | `references/pagination.md` | Keyset/seek pagination as the default, when offset is acceptable, total-count traps |
| Chatty database or HTTP access | `references/batching-and-n-plus-one.md` | Batched writes, Postgres `COPY` for bulk ingest, Kafka producer batching, detecting and fixing N+1 |
| Thread starvation or blocked I/O | `references/async-and-threading.md` | Virtual threads for I/O, bounded pools for CPU work, the shrinking reactive niche, never blocking an event loop |
| Pool exhaustion, slow queries, replica lag | `references/database-tuning.md` | HikariCP sizing formula, index selection and `EXPLAIN (ANALYZE, BUFFERS)`, read-replica lag handling |

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
