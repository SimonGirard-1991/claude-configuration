---
name: java-observability
description: Use when instrumenting a Java backend (Spring Boot by default; Quarkus/Micronaut noted where they differ) with metrics, traces, logs, and audit trails — or when reviewing a service for operability. Covers Micrometer, OpenTelemetry, structured logging, correlation across the three pillars, SLO/SLI thinking, dashboards-as-deliverables, and the technical-vs-audit-log split required in regulated contexts. Skip for throwaway scripts, spikes, or non-Java code.
---

# Java Observability

This skill encodes the rules for making a Java backend operable in production. Observability is **not optional and not an afterthought** — a service you cannot see is a service you cannot run. The bar applies uniformly to any service intended for production; adjust only for throwaway code.

Defaults assume Spring Boot + Micrometer + OpenTelemetry + SLF4J/Logback with a JSON encoder. Quarkus and Micronaut ship equivalent primitives (Micrometer is first-class in both); the strategy below is framework-agnostic, but exact annotations differ.

## When to use

- Designing a new service, module, or bounded context that will run in production.
- Adding a new inbound entry point (HTTP endpoint, Kafka consumer, scheduled job) and deciding what to emit.
- Reviewing a PR for operability gaps (missing metrics, no trace propagation, unstructured logs, no correlation).
- Defining SLOs/SLIs for a service, or wiring dashboards.
- Debugging a production incident where the first question is "what do we even have to look at?".

## When NOT to use

- Throwaway spikes that will be deleted.
- One-shot scripts with no production footprint.
- Non-Java code (the principles transfer; the tooling recommendations do not).

## Core principles

1. **The three pillars are complementary, not redundant.** Metrics answer *what is happening at scale*, traces answer *where is the latency in this one request*, logs answer *why did this specific thing happen*. A service missing any one of the three has a blind spot.
2. **Correlation is the whole point.** A request must be traceable end-to-end across logs, metrics exemplars, and traces via a single trace ID. Without correlation, the three pillars are three disconnected haystacks.
3. **Emit business signals, not just technical ones.** JVM heap and HTTP p99 matter, but `orders_placed_total` and `payment_success_rate` are what the business is actually asking about. Label them as business metrics and separate them from technical telemetry in dashboards.
4. **Observability is a deliverable.** A service is not "done" without a dashboard covering its key SLIs and an on-call runbook linked from it. If you cannot demonstrate how to detect a regression, the service is not ready.
5. **Cardinality is a budget.** High-cardinality labels (user IDs, request IDs, free-form strings) explode metric storage and cost. Keep labels to bounded sets; push unbounded identifiers into traces and logs instead.
6. **Ingest volume is a budget too.** Log lines, trace spans, and high-cardinality metrics all bill per unit. "Turn everything on at INFO/100% sampling" is how observability becomes the second-biggest line item after compute. Design for signal density, not completeness.
7. **Never log secrets or PII unmasked.** Regulated or not, this is a review-blocker. Use allow-lists for loggable fields, not block-lists.

## Reference map

Open a reference when you need the mechanics — instrumentation code, config,
worked examples.

| I need to… | Open | Contains |
|---|---|---|
| Instrument metrics, traces or logs; wire correlation across HTTP/Kafka/async | `references/pillars.md` | Business-vs-technical metric split, label cardinality discipline, exemplars, OpenTelemetry propagation and sampling, JSON+MDC logging, three-pillar correlation via `traceId` |
| Define an SLO/SLI, or build the dashboard that ships with a service | `references/slos-and-dashboards.md` | SLI selection, error budgets, the dashboard-as-deliverable checklist |
| Split technical logs from business audit logs; wire health/readiness probes; review actuator or management-endpoint exposure | `references/audit-logs-and-health.md` | Why technical logs and business audit logs must not share a channel, liveness vs readiness semantics, actuator exposure rules (`show-details`, management port binding). The audit-event field list and retention rules live in the `java-security-baseline` skill, not here. |

## Observability review checklist

When reviewing a service or PR, verify:

**Metrics**
- [ ] Business metrics exist for the service's primary flows, named in business vocabulary.
- [ ] Technical metrics are exposed (HTTP, DB pool, JVM, Kafka lag where applicable).
- [ ] No high-cardinality labels (no user IDs, request IDs, free-form strings, or unbounded error messages).
- [ ] Histograms are used for latency (not gauges or simple averages).

**Traces**
- [ ] Inbound requests open a trace; trace context propagates across HTTP and Kafka boundaries.
- [ ] Manual spans wrap use case entry points where the business boundary differs from auto-instrumentation.
- [ ] Errored/slow requests are sampled at 100% (via tail sampling or equivalent).
- [ ] Span attributes use business-meaningful keys (`order.id`, `tenant.id`), not implementation details.

**Logs**
- [ ] JSON-structured in production.
- [ ] MDC populated with `trace_id`, `span_id`, and relevant business IDs at every entry point.
- [ ] No secrets, tokens, or unmasked PII in log output.
- [ ] No log-per-iteration inside hot loops.
- [ ] Log levels used correctly (ERROR is actionable; INFO is significant events, not trace output).

**Correlation**
- [ ] `trace_id` links logs → traces.
- [ ] Histogram exemplars (where supported) link metrics → traces.
- [ ] Async boundaries propagate MDC and trace context (verified by an end-to-end test).

**SLOs and dashboards**
- [ ] SLIs are named and each maps to a concrete Micrometer instrument.
- [ ] A Grafana dashboard (or equivalent) covers RED metrics + business flows + saturation.
- [ ] Alerts are SLO-based where possible, not raw thresholds.
- [ ] A runbook is linked from the dashboard.

**Health and exposure**
- [ ] Liveness stays cheap and does not fan out to dependencies; readiness checks only dependencies whose outage should drain traffic.
- [ ] Management endpoints are on a separate port bound to an internal interface, and `show-details` is not `always`. `java-security-baseline` refuses actuator on the business API port outright, so port separation is the binding requirement here and `show-details=when-authorized` is a second layer, not an alternative to it. Detail in `references/audit-logs-and-health.md`.

**Regulated context (if applicable)**
- [ ] Business audit events flow through a dedicated channel (not mixed into technical logs).
- [ ] Audit writes are transactional with the action being audited.
- [ ] Audit retention matches the regulatory requirement, not the technical-log retention.

## Common pushback

| Request | Response |
|---|---|
| "We'll add metrics after launch once we see what matters" | No — after launch you have no signal to *decide* what matters. Ship with the RED metrics and primary business counters; iterate from there. |
| "Just log everything at INFO, we can grep later" | No — log volume is cost and noise. INFO is for significant events; DEBUG exists for the firehose. |
| "Let's label the metric by user ID so we can drill in" | No — that's a cardinality bomb. Put the user ID on the trace; keep the metric on bounded labels. |
| "Tracing is too expensive, let's sample at 0.1%" | Head-sample low if you must, but tail-sample errors and slow requests at 100%. A sampled-out error is a debugging dead end. |
| "Health check can hit the DB and Kafka and Redis" | Only for readiness, and only the ones whose outage should actually drain traffic. Liveness stays cheap. Never fan out. |
| "We'll use the same log index for audit and technical logs, it's simpler" | No — retention and immutability requirements differ. Technical log rotation will delete your audit trail. |
| "Just turn everything on — DEBUG logs, 100% sampling, all metrics" | No — ingest volume is the bill. You'll get a surprise invoice and drown the signal in noise. Start at INFO + head-sampled traces + tail-sample errors at 100%, then open the tap where a real investigation needs it. |
| "Why do we need a runbook, the dashboard is self-explanatory" | The dashboard is self-explanatory to the person who built it. On-call at 3am needs the runbook. |

## Relationship to other skills

- **`hexagonal-ddd-java`** — observability instrumentation sits in the infrastructure/adapter layer (OTel agent, logging config) and at use case entry points (manual spans, business metrics). The domain layer stays pure; it does not import Micrometer or OTel.
- **`java-testing-strategy`** — verify async MDC/trace propagation with an end-to-end test (the one place this can be checked reliably). Don't assert on log output in unit tests; that couples tests to a debugging concern.
