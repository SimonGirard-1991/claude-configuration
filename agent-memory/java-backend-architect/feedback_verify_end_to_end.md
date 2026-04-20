---
name: Verify end-to-end through the full chain, not just the producer side
description: For any observability / integration change, verification must traverse the whole pipeline (producer → transport → consumer → presentation), not stop at the first hop.
type: feedback
---

When shipping any change that spans multiple systems — observability
wiring, message queues, database replication, API integrations — the
verification phase must walk the **entire** chain, not just the first hop.

**Concrete failure mode I fell into:** enabled `pg_stat_statements` in
Postgres, verified the DB was collecting stats (`SELECT FROM
pg_stat_statements` returned rows), declared the step done. Missed that
`postgres_exporter`'s stat_statements collector is `defaultDisabled`
upstream — so zero metrics flowed through to Prometheus. The DB was doing
all the work; nothing was consuming the output. A reviewer caught it.

**Why:** verification that stops at the producer proves "data exists"
but not "data is observable." For observability work in particular,
"observable" is the entire point. Half-wired pipelines look fine on the
producer side and silently fail on the consumer side.

**How to apply — write exit criteria that walk the chain:**

For observability changes (metrics/logs/traces):
1. Producer emits the signal (DB / app / service).
2. Transport carries it (Prometheus scrape / log shipper / OTel collector).
3. Storage holds it (Prometheus TSDB / Loki / Tempo).
4. Presentation surfaces it (queryable via API, visible in Grafana).

For messaging integrations:
1. Producer writes to the broker.
2. Broker persists (check offset/retention).
3. Consumer group reads (check lag = 0).
4. Downstream system reflects the message (read model / projection).

For database replication (including CDC):
1. Source commits the change.
2. WAL / replication slot captures it.
3. Replica / CDC consumer receives it.
4. Target system applies it (search for the row, count, checksum).

Every step must be asserted, not assumed. A test like `curl /metrics |
grep <expected_metric>` at the consumer end is not optional — it is the
only proof that the change actually delivers the value it promises.

**How to spot I'm about to make this mistake:**

- I'm writing exit criteria that only involve the system I just changed.
- I'm using `psql` / `kubectl exec` / local tooling to verify, without
  ever hitting the scrape endpoint, the consumer API, or Grafana.
- I'm declaring "step done" after confirming only that the change
  "took effect" in the narrow system where I applied it.

Stop, add the missing hop.

**Does NOT apply to:**

- Pure refactors with no runtime effect.
- Build/tooling changes that don't reach runtime.
- Docs-only changes.
