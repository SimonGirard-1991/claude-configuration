# Domain and application/use-case tests

Reference for the `java-testing-strategy` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Domain tests — pure unit, no mocks at all

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

## Application / use case tests — fakes preferred, mocks acceptable at port boundaries

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
