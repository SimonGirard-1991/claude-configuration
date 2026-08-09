# Connection pools, indexes, execution plans, replicas

Reference for the `java-performance-patterns` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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
