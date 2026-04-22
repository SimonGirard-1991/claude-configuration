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

## The three pillars — what each one is for

### Metrics — aggregate signals

**Tool: Micrometer.** It abstracts over Prometheus, Datadog, CloudWatch, New Relic, etc. Write against Micrometer; swap the backend as needed.

**Emit both:**

- **Business metrics**: `orders_placed_total`, `payment_authorization_latency_seconds`, `account_creation_success_ratio`. Named in business vocabulary. These are what product and on-call care about.
- **Technical metrics**: JVM (heap, GC, threads), HTTP (request count/latency by route, status class), DB pool (HikariCP active/idle/wait), Kafka consumer lag, cache hit ratio. Spring Boot Actuator exposes most of these automatically — enable them explicitly.

**Keep them separate in dashboards.** A business-metrics view answers "is the product working"; a technical-metrics view answers "is the runtime healthy". Mixing them confuses both audiences.

**Label discipline:**

- Bounded sets only: `status_class=2xx|3xx|4xx|5xx`, `route=/orders/{id}` (the templated path, never the expanded URL), `result=success|declined|error`.
- Never label by user ID, order ID, trace ID, or any unbounded value. Those go on traces or logs.
- Watch out for `Timer.builder("...").tag("error", e.getMessage())` — error messages are unbounded. Use the exception class name instead, and bound it.

**Rule of thumb:** if you can enumerate the possible values of a label on a whiteboard, it's a safe label. If you cannot, it belongs in a trace or a log.

**Exemplars:** when the backend supports them (Prometheus + OpenMetrics), attach a trace ID exemplar to histogram buckets. A p99 spike in a dashboard then links directly to a slow trace. This is the cheapest way to bridge metrics → traces and should be on by default.

### Distributed tracing — per-request context

**Tool: OpenTelemetry (OTel).** The Java agent auto-instruments Spring MVC/WebFlux, JDBC, Kafka clients, HTTP clients, and most common libraries. Prefer the agent for breadth; add manual spans where the auto-instrumentation misses business boundaries (use case entry points, domain-significant operations).

**Rules:**

- **Every inbound request opens a trace** (or continues one from an incoming `traceparent` header).
- **Every outbound call is a child span** — HTTP, DB, Kafka producer send, Redis, external gRPC. Auto-instrumentation handles most of these; verify in a sample trace.
- **Trace context propagates across service boundaries.** Use W3C Trace Context (`traceparent`, `tracestate`) — it is the OTel default. Kafka messages carry trace context via headers; confirm your producer and consumer both propagate.
- **Name spans after the operation, not the implementation.** `POST /orders` or `place_order_use_case`, not `OrderController.handlePost` — renaming the class should not rename the span.
- **Attach business attributes to spans, not just technical ones.** `order.id`, `customer.tier`, `payment.method`. These are searchable and make traces useful beyond latency debugging. Still avoid PII.
- **Use OTel semantic conventions for technical attributes** (`http.*`, `db.*`, `messaging.*`, `server.*`). Reserve free-form names for business attributes. Every team reinvents `http_method` vs `http.method` vs `request.method`; the semconv spec already picked.
- **Sampling:** head-based sampling at the edge is fine for high-volume services (1–10% is typical). **Always sample errored and slow requests at 100%** — tail-based sampling via the OTel Collector solves this. A sampled-out error trace is a debugging dead end.

**Manual span example (only where auto-instrumentation misses the boundary):**

```java
Span span = tracer.spanBuilder("place_order").startSpan();
try (Scope __ = span.makeCurrent()) {
  span.setAttribute("order.id", orderId.value());
  span.setAttribute("customer.tier", customer.tier().name());
  return useCase.place(command);
} catch (RuntimeException e) {
  span.recordException(e);
  span.setStatus(StatusCode.ERROR);
  throw e;
} finally {
  span.end();
}
```

### Structured logging — per-event narrative

**Tool: SLF4J + Logback (or Log4j2) with a JSON encoder** (`logstash-logback-encoder` is the common choice). Quarkus ships JSON logging out of the box; Micronaut via `micronaut-logging`.

**Rules:**

- **Always JSON in production.** Pretty-printed plaintext is a local-dev convenience — configure profiles so JSON is the default anywhere a log aggregator will ingest it.
- **MDC carries correlation context.** At minimum: `traceId`, `spanId`, and any business correlation IDs relevant to the current request (`orderId`, `accountId`, `tenantId`). Populate MDC at the edge (filter, interceptor, Kafka listener entry) and clear it on exit.
- **Consistent field names.** `trace_id` and `traceId` in different services force painful queries. Pick a convention (snake_case is common in log aggregators) and enforce it via a shared logging config module.
- **Log levels mean something:**
  - `ERROR`: an operator needs to act, or a user-impacting failure occurred. Pages or alerts can fire from these.
  - `WARN`: unexpected but handled — retry succeeded, circuit breaker opened briefly. Worth looking at in aggregate; not worth waking someone up.
  - `INFO`: significant business events — order placed, user logged in, job completed. **Not** per-line trace output.
  - `DEBUG`/`TRACE`: developer detail, disabled in prod by default, enabled per-logger on demand.
- **Never log secrets, tokens, passwords, card numbers, full PII.** Mask at the source (e.g., log `card.last4`, never the full PAN). Prefer structured fields + an allow-list in a shared logging utility over ad-hoc `.toString()` calls on domain objects — a new field on an aggregate should not silently start leaking via logs.
- **Don't log inside tight loops.** A log line per iteration at high QPS is a self-inflicted incident. Aggregate and log a summary, or use sampling.
- **Exception logging:** log the full stack trace once, at the boundary that handles the exception. Re-logging the same exception at every layer produces noise and makes correlation harder.

## Correlation — the glue

A single request must be reachable from any one pillar to the others:

- **Logs → traces:** every log line carries `trace_id` (and `span_id`) via MDC. Clicking a log line in Kibana/Loki jumps to the trace in Tempo/Jaeger/Datadog.
- **Metrics → traces:** histogram exemplars attach trace IDs to bucket samples. Clicking a p99 spike jumps to a slow trace.
- **Traces → logs:** the trace ID is the query key in the log backend. A trace view shows the span's logs alongside it.

If any of these three links is missing, close the gap. It is the single highest-leverage observability investment after having the pillars exist at all.

**Propagate correlation across async boundaries.** `CompletableFuture`, virtual threads, `@Async`, `TaskExecutor`, Kafka publish/consume — all of these can drop MDC and trace context if you don't wire them. Use OTel's context propagation helpers (`Context.taskWrapping(...)`) and an MDC-propagating task decorator on executors. Verify with an end-to-end test that a trace ID survives the async hop.

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

## Technical logs vs business audit logs

In any regulated context — banking, healthcare, anywhere with compliance obligations — separate two log streams:

| Aspect | Technical logs | Business audit logs |
|---|---|---|
| Purpose | Debugging, performance, operational signal | Who did what, when, to what, under what authorization |
| Volume | High, bursty | Low, steady |
| Retention | Short (days to weeks) | Long (years, per regulation) |
| Mutability | Rotated, overwritten, sampled | Append-only, tamper-evident, immutable |
| Storage | Log aggregator (Loki, ELK, Datadog) | Dedicated audit store (often a regulated DB or WORM storage) |
| Owner | Engineering / SRE | Compliance / Legal / Security |

**Do not merge them.** An audit log in the same index as technical logs will be rotated out the first time retention is reconsidered. Emit audit events through a dedicated channel — a domain event, a write to an `audit_log` table, or an outbound message to a compliance topic. The write must be in the same transaction as the action being audited (see the Transactional Outbox pattern in the reliability skill).

Even outside regulated contexts, consider separating audit events for any **money movement, permission change, or data export**. These are the events future-you will wish existed when something goes wrong.

## Health checks and readiness

- **Liveness** answers "is the process alive?" — keep it cheap and dependency-free. A failing liveness probe should mean "kill and restart me." Do not fail liveness on a dependency outage; that produces crash loops.
- **Readiness** answers "should traffic route to me?" — it may check critical dependencies (DB, broker) but avoid deep chains. A readiness probe that fans out to five downstreams will flap.
- Spring Boot Actuator ships `/actuator/health` with liveness/readiness groups — use them; don't roll your own.
- **Never expose `management.endpoint.health.show-details=always` on an internet-facing listener.** Detailed health responses leak component status (DB vendor/version, broker reachability, disk paths) — useful for internal scrapes, reconnaissance gold for anything public. Bind the management port to an internal interface, or keep `show-details=when-authorized`.

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
