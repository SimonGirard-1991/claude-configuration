# The three pillars and how to correlate them

Reference for the `java-observability` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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
