# Caching — Caffeine and Redis

Reference for the `java-performance-patterns` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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
- **Precomputed materialized views**: this is a read model, not a cache — see the "CQRS read models — an escalation, not a default" section in this skill's `SKILL.md` for the three costs (eventual consistency, the projector as a new failure domain, the replay story) you must design up front.
- **DB query result caching via ORM second-level cache**: generally more trouble than it is worth with jOOQ; if using JPA, know the invalidation rules cold before enabling it.
