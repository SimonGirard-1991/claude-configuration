# Database Integration Tests

Testcontainers + real PostgreSQL. **Not H2 pretending to be Postgres** — vendor-specific SQL (jOOQ generates plenty) will silently diverge.

Tests run Flyway migrations, exercise the real jOOQ DSL, and verify the mapping between domain and records.

---

## Base test class

```java
// AbstractContainerTest.java
package com.company.ecom.test;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

@Testcontainers
@SpringBootTest
public abstract class AbstractContainerTest {

  @Container
  static final PostgreSQLContainer<?> POSTGRES =
      new PostgreSQLContainer<>("postgres:16-alpine")
          .withDatabaseName("test")
          .withUsername("test")
          .withPassword("test")
          // Rule: reuse is a LOCAL development optimization only.
          // Enable via system property; default off so CI and new devs get a clean run.
          .withReuse(Boolean.getBoolean("testcontainers.reuse"));

  @DynamicPropertySource
  static void dataSourceProps(DynamicPropertyRegistry registry) {
    registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
    registry.add("spring.datasource.username", POSTGRES::getUsername);
    registry.add("spring.datasource.password", POSTGRES::getPassword);
  }
}
```

Container reuse is **opt-in**, not default. Locally, enable it by:
1. Running tests with `-Dtestcontainers.reuse=true` (or add it to your IDE run config).
2. Setting `testcontainers.reuse.enable=true` in `~/.testcontainers.properties`.

Do **not** enable reuse on CI or for new developers by default — residual state between sessions can mask cleanup bugs and cause local/CI divergence.

## Repository test

```java
// OrderRepositoryJooqTest.java
class OrderRepositoryJooqTest extends AbstractContainerTest {

  @Autowired OrderRepositoryJooq repo;
  @Autowired DSLContext dsl;

  @BeforeEach
  void cleanup() {
    dsl.deleteFrom(ORDER_LINES).execute();
    dsl.deleteFrom(ORDERS).execute();
  }

  @Test
  void save_then_findById_returns_equivalent_aggregate() {
    var order = Order.place(UUID.randomUUID(), List.of(
        new OrderLine(UUID.randomUUID(), "SKU-1", 2, Money.of("10.00", "EUR"))),
        Clock.fixed(Instant.parse("2026-01-15T10:00:00Z"), ZoneOffset.UTC)).order();

    repo.save(order);

    var loaded = repo.findById(order.id()).orElseThrow();
    assertThat(loaded.id()).isEqualTo(order.id());
    assertThat(loaded.customerId()).isEqualTo(order.customerId());
    assertThat(loaded.lines()).hasSize(1);
    assertThat(loaded.total()).isEqualTo(Money.of("20.00", "EUR"));
    assertThat(loaded.status()).isEqualTo(OrderStatus.PLACED);
  }

  @Test
  void second_save_updates_existing_row_and_bumps_version() {
    // First save: INSERT at version 0.
    // Second save: UPDATE via optimistic-lock path, version bumps to 1.
    // Exactly one row remains either way — the test name intentionally avoids
    // calling this "idempotent" because the aggregate's version changes.
    var order = placedOrder();
    repo.save(order);
    repo.save(order);

    var count = dsl.selectCount().from(ORDERS).where(ORDERS.ID.eq(order.id().value())).fetchOne(0, Integer.class);
    assertThat(count).isEqualTo(1);
    assertThat(order.version()).isEqualTo(1);
  }

  @Test
  void findById_returns_empty_for_unknown_id() {
    assertThat(repo.findById(new OrderId(UUID.randomUUID()))).isEmpty();
  }
}
```

## Optimistic-lock test

```java
@Test
void save_with_stale_version_throws_ConcurrentAggregateModificationException() {
  var initial = Order.place(UUID.randomUUID(), List.of(
      new OrderLine(UUID.randomUUID(), "SKU-1", 1, Money.of("10.00", "EUR"))),
      Clock.fixed(Instant.parse("2026-01-15T10:00:00Z"), ZoneOffset.UTC)).order();
  repo.save(initial);

  var loadedA = repo.findById(initial.id()).orElseThrow();
  var loadedB = repo.findById(initial.id()).orElseThrow();

  loadedA.markPaid(Clock.systemUTC());
  repo.save(loadedA);      // succeeds, DB version -> 1, loadedA.version() -> 1

  loadedB.cancel(Clock.systemUTC());
  assertThatThrownBy(() -> repo.save(loadedB))  // still holds version 0
      .isInstanceOf(ConcurrentAggregateModificationException.class);
}
```

## What to test here

- **Round-trip fidelity**: `save` then `findById` yields an equivalent aggregate.
- **Insert vs update paths**: first save is an INSERT; subsequent saves are UPDATEs with version check.
- **Optimistic locking**: concurrent writers — one succeeds, the other gets `ConcurrentAggregateModificationException`. See the template above.
- **Non-trivial queries**: projections, joins, pagination — test the SQL, not the jOOQ DSL itself.

## What NOT to test here

- Business invariants — those belong in domain tests.
- Transaction rollback at the application level — put those tests with the application service, using `@Transactional` and `TestTransaction.flagForRollback()` if needed.
- Vendor-specific performance — write a benchmark (JMH / Gatling), not a Testcontainers test.

## save + outbox atomicity

The critical guarantee of the two-bean split in `use-case.md` — that `repository.save(order)` and `outbox.record(event)` commit or roll back together — is **not** covered by repository tests (no outbox) nor by application unit tests (no real transaction). Write a dedicated integration test around `PlaceOrderCommitter` with the real `OrderRepositoryJooq` and real `JdbcOrderEventOutbox` against Testcontainers. Force the outbox to fail mid-commit (throw from `record(...)`) and assert that the order row is not persisted either. Without this test, the outbox pattern is unverified theatre.

## Notes

- **Flyway runs automatically** on Spring context startup. Your test DB schema stays in sync with production.
- **Clean between tests** using a `@BeforeEach` rather than `@Transactional + rollback` — the latter hides real bugs with sequence gaps and triggers.
- **Don't use `@DataJpaTest`** — it's JPA-specific and opinionated in ways that don't match jOOQ.

## Variants

- **Quarkus**: `@QuarkusTest` with Testcontainers devservices (native support).
- **Micronaut**: `@MicronautTest` with Testcontainers directly.
- **Plain Java**: start the container in a `@BeforeAll`, wire repositories manually.
