---
name: Observability audience is service-on-call engineers (no-NOC model)
description: For dashboard descriptions and alert annotations in this project, target the service on-call engineer at a modern fintech (Option A), not Tier-1 NOC operators. Fintechs the user targets (Stripe/Wise/Revolut/Datadog-style) generally don't have NOCs.
type: feedback
---

When the user says dashboard content should be "operational," the target audience is a **service on-call engineer** in a no-NOC operating model — not a Tier-1/NOC responder, and not the dashboard's original author.

**Why:** The user's portfolio targets fintechs that don't have NOCs. Tier-1-register content (plain English, "Escalate to: <team>", restated color-band thresholds) erases the sophistication that makes these dashboards interesting to an SRE/platform interviewer (integrity tiles for exporter truncation, PG17/18 hazards, event-sourcing OCC framing of rollback ratio, track_io_timing prerequisites). The real problem with verbose original descriptions is register (they read like Slack messages to the author / internal diary), not audience — the fix is tightening, not re-registering.

**How to apply:** Evaluate every panel description against this 4-beat template, ≤3 technical sentences, PromQL and Postgres jargon fine where it earns its keep:

1. **What the metric is** — one clause; state a formula only if the formula IS the insight.
2. **What's normal on *this* system under *this* workload** — the piece generic Postgres docs can't give you; where the dashboard earns its keep.
3. **Where to look next when it goes bad** — cross-references to other panels or app-side metrics.
4. **Instrumentation gotchas** — only if non-obvious and material (e.g. `track_io_timing=on` required, `pg_stat_io` cluster-scoped, symlog-0-vs-near-0 aliasing). One clause, not a paragraph. Skip when the tile is unambiguous.

**What to move OUT of dashboards entirely:** implementer rationale (why `sum()` is load-bearing, why `scalar()` was avoided, why `clamp_min()` guards divide-by-zero, full rank-then-show argument). These belong in `docs/observability-design.md` or an ADR — valuable content, wrong home. The tell that prose is mis-homed: it starts with "Why..." — that's the author writing to a future maintainer, not to a current reader.

**Anti-pattern to flag:** developer-oriented prose that's been *shortened without being re-registered*. Compression alone doesn't fix register. Also flag the reverse — Tier-1-register content on a dashboard that should be service-on-call register, which erases the signal that makes the dashboard impressive in the first place.

**Note on review discipline:** when a user says an artifact is "operational," ask who uses it before accepting the audience claim. Cost of asking once << cost of two review rounds targeting the wrong audience.
