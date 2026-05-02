---
name: Don't clutter business logic with observability code
description: Timer/Counter/MDC/audit instrumentation belongs in adapters, decorators, or AOP aspects — never interleaved with application-service or domain logic, regardless of how few call sites there are.
type: feedback
---

Observability code (Micrometer Timers/Counters, structured-log MDC, audit log writes) **must not** appear inline inside application-service methods or domain logic. The business code reads as instructions for what the system does for the user; observability code is for the operator. Interleaving the two harms readability of both audiences and signals undisciplined separation of concerns.

**Why:** the user gave direct feedback after I added `Timer.Sample` start/stop wrapping a snapshot save inside `AccountApplicationService.saveEvents`, and `meterRegistry.counter(...)` increments at three dedup sites. Phrasing was concise: "putting observability code directly in business logic clutters it." This is the *same principle* I had argued for earlier in the same session when designing the per-command latency timer (built it as an AOP aspect on `@CommandMetric`-annotated methods rather than inline try/finally). I drifted off the principle when the call-site count was small (3 sites for the counter, 1 site for the snapshot timer). "Few sites" does not change the principle — it just makes the eventual cleanup smaller.

**How to apply:**
- **First choice — adapter level.** If the metric measures an infrastructure operation (DB write latency, HTTP call, queue publish), instrument the adapter that performs it. Naturally aligned with hexagonal layering. Example: snapshot save Timer belongs in `AccountSnapshotRepository`, not in the application service that calls it.
- **Second choice — decorator.** When the metric needs application-layer semantics that an adapter can't know (e.g., "this NO_EFFECT return signaled an idempotency hit"), wrap the relevant port with a `Measured*` decorator and bind it as `@Primary` in a `@Configuration`. Original adapter and application service stay clean.
- **Third choice — AOP aspect.** When the metric is uniform across many methods of one class (per-command latency tagged by command + outcome), an aspect on a marker annotation (`@CommandMetric`) keeps every annotated method's body untouched.
- **Last resort — inline.** Only if neither the adapter, a decorator, nor an aspect can capture the necessary semantics. Even then, isolate to a single private helper method (`recordXxxSafely(...)`) so the business path reads as one call, not as setup-action-record.

**Before adding a new metric, ask:** does this metric's emission depend on information *only* the application service has? If yes — decorator. If no — adapter. If the same instrumentation pattern would repeat across many methods — aspect. If you're tempted to inline it because "it's just a couple of lines and only one place," that's the moment to stop and reach for one of the cleaner options.

**Also:** before adding ANY new metric, check whether existing metrics already capture the signal. The dedicated idempotency-hit counter I almost added was fully derivable from an existing per-command latency timer's `outcome=idempotent` tag — a redundant counter at the cost of cluttered business logic is the worst trade-off. Cardinality and complexity should buy genuinely new operational signal.
