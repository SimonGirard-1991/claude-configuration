# Pagination at scale

Reference for the `java-performance-patterns` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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
