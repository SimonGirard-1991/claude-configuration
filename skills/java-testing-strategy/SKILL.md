---
name: java-testing-strategy
description: Use when writing or reviewing tests for a Spring Boot Java backend (Quarkus/Micronaut noted where they differ) — choosing what to test where, which tools to use at which layer, where mocks are acceptable, and which anti-patterns to refuse (H2, full-context Spring tests, mocked domain). Covers TDD discipline, per-layer strategy (domain, application, repository, messaging, controller, contract, architecture), and the libraries that go with each. For code-ready test templates, see `hexagonal-module-bootstrap` (`references/tests-*.md`) — this skill explains *what and why*, that one *executes*. Skip for trivial scripts, throwaway spikes, or non-Java code.
---

# Java Testing Strategy

This skill encodes the rules for testing Java backends at staff-engineer quality. It is opinionated about *what to test where* and *which tools belong at each layer*. **Defaults assume Spring Boot + JUnit 5 + AssertJ + Testcontainers; Quarkus and Micronaut equivalents are called out at the controller layer.** The strategic principles (test pyramid, mocks-at-ports, fakes preferred, Testcontainers over H2, fakes-must-share-contract-tests, slice-over-full-context, flake quarantine) carry across frameworks; the specific annotations do not.

This skill covers **the strategy**. For copy-pasteable per-layer test scaffolding (domain tests, fakes, Testcontainers wiring, `@WebMvcTest` examples), see `hexagonal-module-bootstrap` (`references/tests-*.md`).

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

## Strategy by layer

### Domain tests — pure unit, no mocks at all

> **Templates:** `hexagonal-module-bootstrap/references/tests-domain.md`. This section owns the *strategy* (what to assert, what to refuse). The reference owns the *code* (`Clock.fixed`, AssertJ chaining patterns, package layout).

**What lives here:** aggregates, value objects, entities, domain events, domain services, invariant exceptions.

**Tools:** JUnit 5, AssertJ. Nothing else for example-based tests. **Add jqwik for property-based tests on value objects, parsers, and any domain operation with a clear invariant over an input space** (e.g., `Money.add` is associative; `IBAN.parse(iban.toString()) == iban` for any valid IBAN). Property-based tests catch the edge cases examples miss — they belong in the domain layer specifically because the domain is pure.

**Rules:**
- **No mocks. None.** Build real domain objects. If you need to mock something to test a domain class, the domain is leaking infrastructure — fix the design, not the test.
- **No Spring context, no Quarkus context, no annotations from any framework.** Plain `class FooTest { @Test ... }`.
- **Inject `Clock.fixed(...)` for any time-dependent behavior.** Never use `Instant.now()` inside the domain.
- **Test invariants, not getters.** `Order.cancel()` on a shipped order throws — that is a test. `order.getId()` returns the id — that is not.
- **Test through aggregate root methods, not field-by-field state inspection.** If you need package-private accessors solely for tests, the test is asking the wrong question.
- **One assertion focus per test.** Multiple AssertJ chained assertions on the same object are fine; asserting on three unrelated things is two or three tests.

**Speed target:** the entire domain test suite for a module runs in under 1 second. If it doesn't, something heavy snuck in.

### Application / use case tests — fakes preferred, mocks acceptable at port boundaries

> **Templates:** `hexagonal-module-bootstrap/references/tests-application.md`. This section owns the *strategy* (when fakes vs. mocks, what failure modes to cover). The reference owns the *code* (`FakeOrderRepository` shape, two-bean committer wiring).

**What lives here:** application services / use cases. Tests verify orchestration: load aggregate → invoke domain method → persist → publish event → handle expected failures.

**Tools:** JUnit 5, AssertJ, **fakes** for ports, Mockito **only when fakes don't fit**.

**Rules:**
- **Prefer fakes over mocks for ports.** A `FakeOrderRepository` (in-memory `Map`) is more readable, more reusable across tests, and survives port refactors better than a wall of `when(...).thenReturn(...)` chains.
- **Mocks are acceptable when:** the port has many methods and only one matters in this test; you need to verify *interaction patterns* (call count, argument matchers); the port has no useful in-memory implementation (e.g., a streaming abstraction).
- **Never mock domain objects.** If you find yourself mocking an aggregate or value object, you are testing the test framework, not the code.
- **No Spring/Quarkus context.** If you think you need one, you are writing an integration test — put it elsewhere.
- **Test the failure modes.** The happy path is table stakes; the value is in `payment_declined`, `aggregate_not_found`, `concurrent_modification`, `idempotency_key_replayed`.
- **Don't re-test domain rules here.** That is the domain test's job. Application tests verify *orchestration*, not invariants.
- **Transactional behavior is NOT covered here.** `@Transactional` is a no-op in unit tests because no Spring proxy exists. Cover save+outbox atomicity, rollback semantics, and isolation in integration tests against Testcontainers.

**Keep your fakes honest with shared port-contract tests.** A fake that drifts from the real adapter is the same failure mode as a mocked DB: application tests pass, integration breaks. Mitigate by writing one **abstract port-contract test** per port (e.g., `abstract class OrderRepositoryContract`) and running it against both the fake and the real adapter:

```java
abstract class OrderRepositoryContract {
  protected abstract OrderRepository repository();

  @Test void findById_returns_empty_when_unknown() { ... }
  @Test void save_then_findById_round_trips() { ... }
  @Test void save_is_idempotent_on_same_id() { ... }
}

class FakeOrderRepositoryTest extends OrderRepositoryContract {
  @Override protected OrderRepository repository() { return new FakeOrderRepository(); }
}

class JooqOrderRepositoryIT extends OrderRepositoryContract {
  // Testcontainers wiring; @Override repository() returns the real impl
}
```

Cheap to write, prevents the silent-divergence failure mode, and makes the fake a first-class citizen. If you skip this, fakes erode the moment a port grows a method.

### Repository / database tests — Testcontainers exclusively

> **Templates:** `hexagonal-module-bootstrap/references/tests-db.md`. This section owns the *strategy* (Testcontainers vs. H2, what to assert, container lifecycle trade-offs). The reference owns the *code* (Postgres container wiring, jOOQ DSL setup, per-test cleanup).

**What lives here:** repository implementations (jOOQ, JPA, JDBC), Flyway/Liquibase migrations, schema constraints, DB-level concurrency behavior, optimistic-lock conflicts, save+outbox atomicity.

**Tools:** Testcontainers (PostgreSQL, MySQL, whatever you run in prod), JUnit 5, AssertJ. Minimal Spring context (`@DataJpaTest`, `@JooqTest`, or hand-wired `DSLContext`).

**Rules:**
- **Testcontainers, not H2.** Non-negotiable. H2 has different SQL dialect, different constraint behavior, different transaction semantics, different JSON support, different `INSERT ... ON CONFLICT` behavior. Tests that pass on H2 and fail on Postgres are a known team-killing pattern.
- **No in-memory substitutes either** (no `hsqldb`, no `derby`, no Spring Boot test slices that swap to H2 by default — disable that explicitly).
- **One container per test class is fine; one container reused across the test suite is faster.** Use Testcontainers' singleton pattern for shared containers, with proper schema cleanup between tests. Trade-off: parallelism is harder with shared containers — choose based on suite size.
- **Test the actual SQL.** For jOOQ: assert the records persist and re-load correctly, and that constraints fire. For JPA: also test that `@Version`-based optimistic locking actually throws on conflict.
- **Test migrations forward AND backward (where applicable).** If a migration adds a NOT NULL column with a backfill, run the migration against a test DB seeded with the *previous* schema's data and verify the backfill works.
- **Save + outbox atomicity is tested here, not in application tests.** This is the only place rollback semantics are real.
- **Optimistic-lock and concurrency tests live here.** For any aggregate with a `@Version` column or equivalent, write a test that loads the same aggregate from two threads/transactions, mutates both, commits both, and asserts the second commit throws `OptimisticLockingFailureException` (or jOOQ equivalent). Then assert the application-level retry path actually succeeds on retry. This is the only place the conflict path is real — unit tests can't reproduce it.
- **Idempotency-key replay tests live here too.** Insert a row with a given idempotency key, attempt to insert again, assert the second attempt is rejected by the unique constraint (not silently swallowed). Then assert the application-level handler maps the violation to a no-op result, not an error.
- **Minimal Spring context.** `@DataJpaTest`, `@JooqTest`, or `@SpringBootTest(classes = {DslConfig.class, OrderRepositoryImpl.class})`. Never `@SpringBootTest` with no `classes` argument for a repository test — it loads the world.

### Messaging / Kafka tests — Testcontainers Kafka, minimal context

> **Templates:** `hexagonal-module-bootstrap/references/kafka-adapter.md` (production code + test patterns alongside). This section owns the *strategy* (Testcontainers vs. EmbeddedKafka, what scenarios to cover). The reference owns the *code* (consumer wiring, Awaitility patterns).

**What lives here:** consumer logic, idempotency handling, DLQ routing, serialization/deserialization, integration-event publication, retry behavior.

**Tools:** Testcontainers Kafka (preferred) or `EmbeddedKafkaBroker` for very fast feedback. JUnit 5, AssertJ, Awaitility for async assertions.

**Rules:**
- **Testcontainers Kafka for trustworthy tests; `EmbeddedKafkaBroker` for fast inner-loop feedback.** Embedded Kafka is in-process and fast, but diverges from real Kafka in subtle ways (rebalance behavior, transaction semantics). At least one CI test per consumer should use Testcontainers.
- **Test the consumer end-to-end:** publish a real message → wait for the consumer's side effect → assert. Use Awaitility, not `Thread.sleep`.
- **Test idempotency explicitly.** Replay the same message twice; assert the side effect happens once. This is the most commonly missed test in messaging code.
- **Test DLQ routing.** Publish a poison message; assert it lands in the DLQ with full context (original payload, error, headers).
- **Test serialization both directions.** Producer-side: confirm the published bytes deserialize against the schema. Consumer-side: confirm the consumed bytes deserialize correctly with both forward- and backward-compatible schema changes.
- **Minimal Spring context.** `@SpringBootTest(classes = {KafkaConfig.class, OrderConsumer.class, ...})`, never load the full app.
- **Awaitility timeouts must be generous but bounded.** 5–10 seconds for local; never `Awaitility.await().forever()`.

### Controller / web slice tests — `@WebMvcTest`, never full context

> **Templates:** `hexagonal-module-bootstrap/references/tests-web.md`. This section owns the *strategy* (slice over full context, what status codes to cover). The reference owns the *code* (MockMvc setup, mapper test patterns).

**What lives here:** HTTP semantics — status codes, content types, request/response payload shape, validation behavior, error response format, security configuration at the edge.

**Tools:** `@WebMvcTest` (Spring MVC) or `@WebFluxTest` (WebFlux). MockMvc / WebTestClient. Mockito for the application service layer.

**Rules:**
- **`@WebMvcTest(YourController.class)` only — never `@SpringBootTest` for a controller test.** Loading the full context for a controller test is the single most common cause of slow Spring test suites.
- **Mock the application service.** This is one of the few places mocking is unambiguously correct: the controller's job is HTTP↔command translation, and the application service is its only outbound dependency.
- **Test status codes for every documented response.** 200, 201, 400 (validation), 404, 409 (conflict), 422 (business rule violation), 500 (unexpected). If your controller can return it, test it.
- **Test validation behavior.** Bean Validation errors should produce a structured error response — assert on the shape, not just the status.
- **Test the security configuration here, not in unit tests.** `@WithMockUser`, `@WithAnonymousUser` — verify that protected endpoints reject unauthenticated requests.
- **Don't test the application service's logic here.** That is what use-case tests are for. The controller test asserts that valid input produces a call to the use case and that the use case's result becomes the right HTTP response.
- **Quarkus/Micronaut equivalents:** `@QuarkusTest` with `RestAssured`, or Micronaut's `@MicronautTest` with `HttpClient`. Same principle: load only what you need.

### Contract tests — Pact or Spring Cloud Contract at boundaries

**What lives here:** verification that producer and consumer agree on the wire format, used at any service boundary that crosses a team or release cycle.

**Tools:** Pact (consumer-driven) or Spring Cloud Contract (producer-driven).

**Rules:**
- **Mandatory at any inter-team service boundary.** Skip it within a single team that releases together; mandate it the moment a contract crosses a team line.
- **Consumer-driven by default.** Pact's model — consumer writes the contract, publishes to a broker, producer verifies — is the right shape for most cases.
- **Producer-driven (SCC) for "open host" services** with many consumers and a stable, versioned contract.
- **Run producer-side verification in CI.** A contract that isn't verified on every producer build is decoration.
- **Cover both REST and async.** Pact supports message contracts; use it for Kafka topics that cross team boundaries.
- **Don't replace contract tests with E2E tests.** E2E tests are slow, fragile, and don't isolate which side broke. Contract tests pinpoint the diff between producer and consumer.

### Architecture tests — non-negotiable on any non-trivial project

> **Templates:** `hexagonal-module-bootstrap/references/tests-architecture.md`. This section owns the *strategy* (what rules to enforce, ArchUnit vs. Modulith). The reference owns the *code* (concrete `noClasses().that()...` rules, `Modules.verify()` setup).

**What lives here:** structural rules — layering boundaries, package dependencies, naming conventions, framework-annotation placement.

**Tools:** ArchUnit (any Java project), or Spring Modulith's `ApplicationModules.verify()` (Spring Boot only).

**Rules:**
- **At least one architecture test must exist** on any project past the prototype stage. Otherwise hexagonal/DDD/modular boundaries silently rot.
- **Enforce dependency direction:** `domain → ∅`, `application → domain`, `infrastructure → application + domain`. Never the reverse.
- **Enforce framework-annotation placement:** no `@Service`/`@Entity`/`@Autowired`/`@Transactional` in `domain/`.
- **Enforce inter-BC rules** (multi-BC only): no BC imports another BC's `domain/` or `infrastructure/` — only its `api/`.
- **Run on every build.** These tests are fast; there is no excuse to skip them.
- **Modulith over ArchUnit when on Spring Boot;** ArchUnit elsewhere. Modulith's defaults align with the BC-as-module convention.

For code templates: `hexagonal-module-bootstrap/references/tests-architecture.md`.

## Tooling standards

| Concern | Default | Notes |
|---|---|---|
| Test framework | JUnit 5 | JUnit 4 is end-of-life — migrate. |
| Assertions | AssertJ | Fluent, readable, far better failure messages than Hamcrest or vanilla JUnit. |
| Mocks | Mockito | At ports only. Don't mock domain. Final-class mocking is usually a smell — fix the design instead. Static mocking (`mockStatic`, requires `mockito-inline`) is a last resort when you genuinely cannot inject (e.g., third-party code calling `LocalDateTime.now()`); for your own code, inject a `Clock` and never reach for it. |
| DB integration | Testcontainers | Real engine. No H2. |
| Kafka integration | Testcontainers Kafka | `EmbeddedKafkaBroker` acceptable for fast inner loop. |
| Async assertions | Awaitility | Bounded timeouts; never `forever()`. |
| HTTP slice | `@WebMvcTest` / `@WebFluxTest` | Never `@SpringBootTest` for a controller. |
| Contracts | Pact | SCC for producer-driven open-host services. |
| Architecture | ArchUnit / Spring Modulith | One of these is mandatory. |
| Property-based | jqwik | Good for value objects, parsers, anything with a clear invariant over an input domain. |
| Mutation testing | Pitest | High-leverage on critical domain modules; too slow for the whole suite. Run nightly or per-module. |

## Test data builders

For aggregates with non-trivial construction, write a **test data builder** with sensible defaults and `with*` methods for overrides. Place it in `src/test/java` alongside the aggregate. This beats the alternative — repeated 15-line construction in every test, which obscures what the test is actually about.

```java
class OrderTestBuilder {
  private OrderId id = new OrderId(UUID.randomUUID());
  private List<OrderLine> lines = List.of(new OrderLine("SKU-1", 1, money("10.00")));
  // ...
  OrderTestBuilder withLines(OrderLine... lines) { this.lines = List.of(lines); return this; }
  Order build() { return Order.place(id, lines, CLOCK); }
}
```

Don't over-engineer. If a domain object has 2 fields, just construct it inline.

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

## CI and test execution

- **Unit + architecture tests on every commit.** Sub-minute feedback target.
- **Integration tests (Testcontainers DB, Kafka) on every PR.** A few minutes is acceptable.
- **Contract tests on every producer build, with results published to a broker** (Pact Broker or equivalent). Consumer builds verify against the broker.
- **E2E tests on a separate pipeline** (post-merge, scheduled). Don't gate every PR on a 30-minute E2E suite.
- **Parallel execution:** safe for unit tests; safe for integration tests if Testcontainers containers are per-class or properly isolated. JUnit 5's `junit.jupiter.execution.parallel.enabled=true` is your friend.
- **Flake quarantine, not flake retry.** A flaky test goes into a quarantine list with a deadline; if it isn't fixed by the deadline, it is deleted.

## Review checklist

When reviewing tests in a PR, verify:

**Strategy**
- [ ] Each test is at the right layer (domain logic in domain tests, not in `@SpringBootTest`).
- [ ] Bug fixes have a regression test that fails without the fix.
- [ ] No new H2, no new full-context Spring tests, no new mocked domain objects.

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
