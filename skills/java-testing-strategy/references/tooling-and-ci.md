# Tooling standards, test data builders, CI execution

Reference for the `java-testing-strategy` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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

## CI and test execution

- **Unit + architecture tests on every commit.** Sub-minute feedback target.
- **Integration tests (Testcontainers DB, Kafka) on every PR.** A few minutes is acceptable.
- **Contract tests on every producer build, with results published to a broker** (Pact Broker or equivalent). Consumer builds verify against the broker.
- **E2E tests on a separate pipeline** (post-merge, scheduled). Don't gate every PR on a 30-minute E2E suite.
- **Parallel execution:** safe for unit tests; safe for integration tests if Testcontainers containers are per-class or properly isolated. JUnit 5's `junit.jupiter.execution.parallel.enabled=true` is your friend.
- **Flake quarantine, not flake retry.** A flaky test goes into a quarantine list with a deadline; if it isn't fixed by the deadline, it is deleted.
