---
name: Micrometer failure injection — override newTimer, not the public timer(...) overloads
description: When injecting MeterRegistry failures for tests, the only reliable extension point is the protected newTimer(Meter.Id, ...) hook — public timer(...) overloads route independently through a package-private core.
type: feedback
---

When unit-testing Micrometer-instrumented code by injecting a `MeterRegistry` that fails on timer creation (or any meter creation), override the **protected** hook, not the public factories.

**Why:** in Micrometer 1.16+ (verified by inspecting the bytecode):
- `MeterRegistry` exposes multiple public timer factories: `timer(String, String...)`, `timer(String, Iterable<Tag>)`, `timer(String, Tags)`.
- Each independently routes to a **package-private** `timer(Meter.Id, DistributionStatisticConfig, PauseDetector)`, which calls the **protected abstract** `newTimer(Meter.Id, DistributionStatisticConfig, PauseDetector)`.
- The public overloads do NOT delegate to one another. Overriding `timer(String, Iterable<Tag>)` to throw will be silently bypassed by callers that use `timer(String, String...)` or `Timer.Builder.register(MeterRegistry)`.
- The same applies to counters, gauges, distribution summaries: each has a public-overload family routing to a protected `newCounter` / `newGauge` / `newDistributionSummary` hook.

If the override is on a method that isn't on the call path, resilience tests pass tautologically — they only verify the wrapping aspect/decorator returns normally, never that the catch handler ever fires.

**How to apply:**
```java
class FailingMeterRegistry extends SimpleMeterRegistry {
  final AtomicInteger newTimerCalls = new AtomicInteger();

  @Override
  protected Timer newTimer(
      Meter.Id id,
      DistributionStatisticConfig distributionStatisticConfig,
      PauseDetector pauseDetector) {
    newTimerCalls.incrementAndGet();
    throw new RuntimeException("simulated meter failure");
  }
}
```

Then write a tiny sanity-check test that calls `registry.timer(name, "k", "v")` directly and asserts it throws — that pins the call path. Without that sanity check, a future Micrometer upgrade or a refactor of the production code can silently break the test scaffolding without failing the suite.

Track invocation count and assert it's `> 0` in resilience tests so passing tests prove the catch was exercised, not that the failure path was unreachable.

Imports needed:
- `io.micrometer.core.instrument.Meter`
- `io.micrometer.core.instrument.distribution.DistributionStatisticConfig`
- `io.micrometer.core.instrument.distribution.pause.PauseDetector`

**Broader principle:** when a code reviewer suggests a specific fix, verify the call path actually behaves as the suggested fix assumes. The reviewer here suggested using `meterRegistry.timer(name, "k","v")` to route through the overridden public method — it doesn't, because the public overloads are independent paths. The reviewer's *finding* (tautological tests) was correct; their *fix* wasn't. Both reviewer and reviewee can be wrong about the same code.
