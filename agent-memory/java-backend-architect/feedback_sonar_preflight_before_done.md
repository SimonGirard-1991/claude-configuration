---
name: Sonar pre-flight before declaring a feature done
description: Before handing back a feature, scan new diff for the four Sonar issues most commonly missed (S1192, S5778, S5128, S5328) — user has been burned by features shipping with multiple of these.
type: feedback
---

Before declaring a Java feature complete, scan the new diff for the
common static-analysis issues that ship sloppily and surface in the next
Sonar pass:

- **S1192** — string literal repeated 3+ times: extract a `private
  static final String` constant. Typical offenders: outcome / status /
  enum-like tag values used across `Counter`/`Timer` tags or log
  fields.
- **S5778** / "lambda multi-invocation" — a single `() -> ...` body
  containing more than one expression that could throw. AssertJ's
  `assertThatExceptionOfType(...).isThrownBy(lambda)` is the usual
  trigger when the lambda allocates its argument inline (`new
  XException("…")` and the call). Extract the construction to a local
  so only the *acting* call is inside the lambda.
- **S5128** — missing `@Valid` on a bean-typed parameter. **Caveat for
  this codebase**: see `feedback_sonar_s5128_openapi_override.md` —
  controllers that override an OpenAPI-generated interface method
  cannot redeclare `@Valid` (Hibernate Validator's HV000151), so the
  fix there is `@SuppressWarnings("java:S5128")`, not `@Valid`.
- **S5328** / unused imports / dead annotations — Spotless often
  catches these but won't catch e.g. `@Valid` on a non-`@Validated`
  bean (does nothing at runtime).

**Why:** user expressed frustration that the recent observability
features (`CommandMetricAspect` + tests, `AdapterMetricAspect` + tests)
shipped with 14+ Sonar warnings spanning all four categories above —
specifically asked to "pay more attention in the feature." These are
not subtle issues; a quick deliberate pass would have caught them
before the user had to point them out.

**How to apply:** at the end of any feature implementation in a
Spring Boot / Java backend, explicitly read your own diff for
duplicated literals, lambda hygiene, missing-or-dead `@Valid`, and
unused imports before invoking the code-reviewer subagent. This is
five minutes of self-review that prevents a "fix the Sonar warnings"
follow-up. Do not skip it because the feature builds and tests pass —
those gates are necessary, not sufficient.
