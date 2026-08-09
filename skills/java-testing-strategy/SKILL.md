---
name: java-testing-strategy
description: Use when writing or reviewing tests for a Spring Boot Java backend (Quarkus/Micronaut noted where they differ) — choosing what to test where, which tools to use at which layer, where mocks are acceptable, and which anti-patterns to refuse (H2, full-context Spring tests, mocked domain). Covers TDD discipline, per-layer strategy (domain, application, repository, messaging, controller, contract, architecture), and the libraries that go with each. For code-ready test templates, see the `hexagonal-module-bootstrap` skill's own `references/tests-*.md` files — this skill explains *what and why*, that one *executes*. Skip for trivial scripts, throwaway spikes, or non-Java code.
---

# Java Testing Strategy

This skill encodes the rules for testing Java backends at staff-engineer quality. It is opinionated about *what to test where* and *which tools belong at each layer*. **Defaults assume Spring Boot + JUnit 5 + AssertJ + Testcontainers; Quarkus and Micronaut equivalents are called out at the controller layer.** The strategic principles (test pyramid, mocks-at-ports, fakes preferred, Testcontainers over H2, fakes-must-share-contract-tests, slice-over-full-context, flake quarantine) carry across frameworks; the specific annotations do not.

This skill covers **the strategy**. For copy-pasteable per-layer test scaffolding (domain tests, fakes, Testcontainers wiring, `@WebMvcTest` examples), see the `hexagonal-module-bootstrap` skill and the `references/tests-*.md` files in *that* skill's directory.

## When to use

- Writing tests for a new feature, bug fix, or refactor.
- Reviewing a PR's testing approach.
- Setting up the test stack for a new module or service.
- Deciding whether to use TDD on a given piece of code.
- Pushing back on bad tests (mocked DB, full `@SpringBootTest` for one controller, mocked domain objects).

## When NOT to use

- Throwaway spikes that will be deleted.
- Pure scripts or one-shot ops jobs.
- Code that is not Java/JVM.

## Core principles

1. **Tests are first-class production code.** Same review bar, same naming discipline, same refactor hygiene. A test you cannot read in 30 seconds is a bug report waiting to happen.
2. **One behavior per test.** If the test name needs "and", it is two tests.
3. **Tests fail for one reason.** Diffuse setup that touches ten beans means a failure could be any of them.
4. **Speed compounds.** A 10× slower suite is a 10× slower feedback loop. Push every test to the cheapest layer that genuinely covers its risk.
5. **Determinism is non-negotiable.** Inject `Clock`, seed randomness, control concurrency. A flaky test is worse than no test — it teaches the team to ignore red.
6. **Tests document intent.** The name describes the behavior in the language of the domain, not the implementation.
7. **Naming convention: `snake_case_behavior`.** `rejects_transfer_when_account_frozen`, `emits_OrderPlaced_when_payment_authorized`. Not `testTransfer2`, not `shouldRejectTransfer`. Pick this and stop the bikeshed — readability of `_when_` reads better in failure output than camelCase. If your team has already standardized on `should_X_when_Y`, use that everywhere consistently. The rule is consistency, not the specific casing.

## TDD — where it pays off, where it doesn't

TDD (Red → Green → Refactor) is a discipline, not a ritual. Apply it where it actually pays back:

| Apply TDD | Skip TDD |
|---|---|
| Domain logic — aggregates, value objects, invariants | Spring/Quarkus configuration & wiring |
| Use cases — orchestration with branching paths | Flyway/Liquibase migrations (verify with integration test instead) |
| Pure algorithms, parsers, calculators | Kafka topology / consumer container setup |
| Bug fixes — write the failing test first, every time | Library glue with no branching |
| Anything where the test forces design clarity | Throwaway spikes |

**Rule of thumb:** if writing the test first sharpens the API design, do it. If the "test" is just asserting that a framework wired something correctly, skip TDD and write an integration test that proves the wiring works end-to-end.

For bug fixes, TDD is **non-negotiable**. The first commit on a bug fix branch should be the failing test that reproduces the bug. Without it, you cannot prove the fix works or that it stays fixed.

## The test pyramid (with realistic shapes)

From bottom (most, fastest) to top (fewest, slowest):

- **Unit** — domain logic and application use cases. Fast, deterministic. The vast majority by count.
- **Integration / slice** — `@WebMvcTest`, repository tests against Testcontainers, Kafka tests against Testcontainers Kafka. Meaningful slices, not the whole app.
- **Contract** — Pact / Spring Cloud Contract at team-or-service boundaries. Few, focused, run on every producer build.
- **E2E** — full system. Smallest count, slowest, run on a separate pipeline.
- **Architecture** — ArchUnit / Modulith. Fast, runs on every build. Lives outside the pyramid; gates structure, not behavior.

**Anti-shape: the ice cream cone.** Lots of slow E2E tests, few unit tests. Symptom: CI takes 40 minutes, flakes constantly, nobody trusts it. If you see this, the fix is not "more E2E" — it is pushing coverage *down* the pyramid.

**Anti-shape: the hourglass.** Many unit tests, many E2E tests, no integration tests. Symptom: unit tests pass, prod breaks at the integration seams (DB constraints, message serialization, transactional boundaries). Fix: add Testcontainers-based tests at the seams.

## Reference map

Open a reference when you are writing **or reviewing** tests at a given layer.
The per-layer definitions that make "is this test at the right layer?"
decidable live in the references, so a layer-specific question means opening the
matching file rather than answering from memory.

| I need to… | Open | Contains |
|---|---|---|
| Test domain logic or a use case | `references/layers-domain-application.md` | Pure JUnit domain tests with no mocks, `Clock.fixed()`, fakes-over-mocks at port boundaries, when a mock is acceptable |
| Test a repository or a Kafka consumer/producer | `references/layers-db-messaging.md` | Testcontainers Postgres (never H2), Testcontainers Kafka with a minimal context, awaiting async without `Thread.sleep` |
| Test a controller, a cross-team contract, or architecture | `references/layers-web-contract-architecture.md` | `@WebMvcTest` slices, Pact / Spring Cloud Contract at boundaries, ArchUnit and Spring Modulith `verify()` |
| Pick libraries, build test data, wire CI, or decide what to do with a flaky test | `references/tooling-and-ci.md` | JUnit 5 / AssertJ / Testcontainers / Mockito defaults, test data builders, CI staging and parallelism, the flake-quarantine policy (quarantine with a deadline, then delete — never retry-on-flake) |

For code-ready test templates, load the `hexagonal-module-bootstrap` skill and read
its own `references/tests-*.md` files — those templates live in that skill's
directory, not in this one.

## Anti-patterns to refuse

| Anti-pattern | Why it's wrong | What to do instead |
|---|---|---|
| **H2 in repository tests** | Different SQL dialect, different constraint behavior. Tests pass; prod migration breaks. | Testcontainers with the actual DB engine. |
| **`@SpringBootTest` for a controller test** | Loads the whole app. Suite slows by 5–10×. | `@WebMvcTest(YourController.class)`. |
| **Mocking the database** | Mocked tests pass, integration breaks. Classic team-killer. | Real DB via Testcontainers. |
| **Mocking domain objects** | Tests the test framework, not the code. Domain leaks infrastructure if you can't construct it. | Build real aggregates; if construction is hard, use a test data builder. |
| **`Thread.sleep` in async tests** | Flake, slow, or both. | Awaitility with a bounded timeout. |
| **Tests with "and" in the name** | Two behaviors hidden in one test. Failure message can't tell you which broke. | Split into separate `@Test` methods. |
| **Asserting on toString output** | Couples the test to a debugging concern. | Assert on the actual fields. |
| **Reflection to access private fields** | Tests the implementation, not the behavior. Refactor breaks the test. | Test through the public API; if you can't, the API is wrong. |
| **`@Disabled` without an issue link** | Permanent rot. Disabled tests are deleted tests. | Either fix it now, link an issue, or delete it. |
| **`@Sql` to seed data via raw SQL in repository tests** | Diverges from how the app actually creates data. | Use the repository under test (or a test data builder) to seed. |
| **One giant `BaseIntegrationTest` parent** | Hidden setup, slow startup, test isolation gone. | Per-test minimal context with explicit `classes = {...}`. |
| **Ignoring flaky tests with retries** | Flake-as-feature. Trust in the suite collapses. | Find the root cause: time, ordering, shared state, async race. Fix it. |
| **Tests in `src/main`** | Ships test code to prod. | Test code lives in `src/test/java`. Always. |

## Coverage — measure, don't worship

- Coverage is a **diagnostic**, not a target. 80% line coverage with shallow tests is worse than 60% with focused tests on the hard paths.
- **Mutation coverage (Pitest) is more honest than line coverage.** It tells you whether your tests would catch a bug, not just whether they executed the line.
- **No coverage gate on the whole repo.** Per-module gates on critical domain modules (e.g., 90% line + 80% mutation on `payment.domain`) are reasonable.
- **Never write a test purely to satisfy a coverage gate.** That test will be deleted in six months and the gate will be lowered. Be honest.

## Review checklist

When reviewing tests in a PR, verify:

**Strategy**
- [ ] Each test is at the right layer (domain logic in domain tests, not in `@SpringBootTest`).
- [ ] Bug fixes have a regression test that fails without the fix.
- [ ] No new H2, no new full-context Spring tests, no new mocked domain objects.
- [ ] Every fake adapter shares an abstract port-contract test with the real adapter, so the two cannot silently diverge. A fake with no contract test is a second implementation nobody verifies.

**Quality**
- [ ] Each test has a clear name that describes a behavior in domain language.
- [ ] One behavior per test (no "and" in the name).
- [ ] No `Thread.sleep`, no unbounded `Awaitility`, no `@Disabled` without an issue link.
- [ ] Time-dependent code uses an injected `Clock`.

**Coverage of failure modes**
- [ ] Use case tests cover the obvious failure modes, not just the happy path.
- [ ] Kafka consumer tests cover idempotency and DLQ routing.
- [ ] Controller tests cover all documented status codes and validation responses.
- [ ] Repository tests cover constraint violations, not just successful inserts.

**Hygiene**
- [ ] No test code in `src/main`.
- [ ] No reflection-based access to private fields.
- [ ] Test data builders used where construction is non-trivial.
- [ ] Architecture test passes.

## Common pushback

| Request | Response |
|---|---|
| "Let's just use H2, it's faster" | No — different dialect, different constraints. The speed gain is wiped out the first time a prod migration breaks because H2 didn't catch it. |
| "Mock the repository in the application test" | Use a fake (in-memory `Map`). Mocks work but fakes survive port refactors and read better. |
| "We need full `@SpringBootTest` to test this controller" | No — `@WebMvcTest(TheController.class)`. If it genuinely needs more, name the specific classes via `classes = {...}`. |
| "Just `Thread.sleep(1000)` to wait for the consumer" | No — Awaitility with a bounded timeout. The sleep will be too short on CI and too long locally. |
| "Coverage dropped below 80%, add a test" | Only if the uncovered code is a real risk. Don't write throwaway tests to satisfy a gate. |
| "This test is flaky, let's add `@RetryingTest(3)`" | No — find the root cause. Retry-on-flake is how a suite stops being trustworthy. |
| "TDD is overkill for this Kafka consumer config" | Agreed — write an integration test against Testcontainers Kafka instead. TDD is for branching logic, not framework wiring. |
| "Let's mock the aggregate to simplify the test" | No — if you can't construct the aggregate cleanly, the aggregate's API is wrong. Fix the design or use a test data builder. |
| "We don't need an architecture test, the team knows the rules" | The team will change. The architecture test is the only memory that survives turnover. |

## Relationship to other skills

- **`hexagonal-ddd-java`** — owns the *what goes where* rules for production code. This skill takes those layers as a given and prescribes the matching test approach.
- **`hexagonal-module-bootstrap`** — owns the *code-ready templates* for tests at every layer. When this skill says "write a Testcontainers-based jOOQ repository test", that skill has the template. Strategy here, code there.
