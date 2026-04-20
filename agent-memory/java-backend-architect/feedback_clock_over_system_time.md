---
name: Prefer injected Clock over System.currentTimeMillis()
description: Always use injected java.time.Clock instead of System.currentTimeMillis() or Instant.now() for testability and consistency
type: feedback
---

Always use an injected `java.time.Clock` instead of `System.currentTimeMillis()` or static `Instant.now()` calls.

**Why:** The codebase already establishes this pattern consistently (via `TimeConfig` bean). Using `System.currentTimeMillis()` breaks that convention, makes time-dependent assertions flaky, and prevents deterministic testing with fixed clocks. Caught in code review as an inconsistency.

**How to apply:** Whenever generating code that needs the current time, inject `Clock` and use `clock.instant()`. This applies to infrastructure code (schedulers, repositories) and domain/application code alike.
