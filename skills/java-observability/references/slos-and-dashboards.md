# SLOs, SLIs and dashboards-as-deliverables

Reference for the `java-observability` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## SLOs and SLIs — think about them proactively

When designing a service, name the SLIs before the first line of code goes to prod. Typical shapes:

- **Availability SLI**: fraction of requests that succeed (2xx/3xx, or business-success for async flows). SLO e.g. 99.9% over 30 days.
- **Latency SLI**: fraction of requests served under a threshold (e.g. p99 < 300ms). Target the percentile that matters; averages hide the tail.
- **Correctness SLI** (for data pipelines): fraction of events processed without DLQ routing, within a freshness window.
- **Freshness SLI** (for async/event-driven flows): time between event production and downstream visibility.

**Every SLI must be measurable from existing metrics.** If you cannot point to the Micrometer timer or counter that implements the SLI, the SLI is aspirational, not operational.

**Mention SLOs in design discussions.** When proposing a new service, the first observability question is "what are its SLOs and what Micrometer instruments measure them?" Teams that skip this end up debating reliability in retrospect instead of designing for it upfront.

## Dashboards as deliverables

A service is not "done" until it has:

1. **A Grafana dashboard (or equivalent)** with, at minimum:
   - Request rate, error rate, latency (the RED method) per major endpoint.
   - Business metrics for its primary flows.
   - Saturation signals — DB pool usage, consumer lag, thread pool queue depth.
2. **An alert or two** tied to SLO burn — not to raw thresholds. "Error rate > 5%" is a threshold alert; an SLO alert fires on error-budget burn rate. The current SRE default is **multi-window, multi-burn-rate**: a fast-burn rule when 1h *and* 5m windows both exceed ~14.4× burn (pages within minutes on a major outage) plus a slow-burn rule on 6h/30m windows at ~6× burn (catches the slow leak). Single-window burn alerts either page late or flap; reach for the multi-window pattern. SLO alerts page less and mean more.
3. **A runbook** linked from the dashboard explaining, for each alert, how to triage it. Without a runbook, the on-call engineer re-derives the response every page.

Treat these as code review deliverables, not "we'll do it after launch." After launch never comes.
