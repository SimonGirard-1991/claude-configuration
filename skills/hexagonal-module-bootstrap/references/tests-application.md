# Application Service Tests

Test the orchestration. Domain logic is already covered by domain tests — don't re-test it here. Focus on: does the service load the aggregate, call the right domain method, persist, record the outbox event, and handle expected failures?

**Prefer fakes to mocks** for ports. A `FakeOrderRepository` (an in-memory `Map`) is often more readable and more robust than Mockito's `when(...).thenReturn(...)` chains.

---

## Placement

```
src/test/java/com/company/ecom/order/application/
├── PlaceOrderServiceTest.java
└── fake/
    ├── FakeOrderRepository.java
    ├── FakePaymentGateway.java
    └── FakeOrderEventOutbox.java
```

## Fakes

```java
// order/application/fake/FakeOrderRepository.java
public class FakeOrderRepository implements OrderRepository {
  private final Map<OrderId, Order> store = new HashMap<>();
  @Override public void save(Order o) { store.put(o.id(), o); }
  @Override public Optional<Order> findById(OrderId id) { return Optional.ofNullable(store.get(id)); }
  public int size() { return store.size(); }
}
```

```java
// order/application/fake/FakePaymentGateway.java
public class FakePaymentGateway implements PaymentGateway {
  private boolean authorize = true;
  public void alwaysAuthorize()  { authorize = true; }
  public void alwaysDecline()    { authorize = false; }

  @Override public PaymentResult authorize(OrderId orderId, Money amount) {
    return new PaymentResult(authorize, "ref-" + orderId.value());
  }
}
```

```java
// order/application/fake/FakeOrderEventOutbox.java
public class FakeOrderEventOutbox implements OrderEventOutbox {
  private final List<OrderEvent> recorded = new ArrayList<>();
  @Override public void record(OrderEvent event) { recorded.add(event); }
  public List<OrderEvent> recorded() { return List.copyOf(recorded); }
}
```

## Service test

```java
// PlaceOrderServiceTest.java
class PlaceOrderServiceTest {

  private static final Clock CLOCK =
      Clock.fixed(Instant.parse("2026-01-15T10:00:00Z"), ZoneOffset.UTC);

  private FakeOrderRepository repo;
  private FakePaymentGateway gateway;
  private FakeOrderEventOutbox outbox;
  private PlaceOrderService service;

  @BeforeEach
  void setUp() {
    repo = new FakeOrderRepository();
    gateway = new FakePaymentGateway();
    outbox = new FakeOrderEventOutbox();
    // Two-bean split (see use-case.md). In unit tests we instantiate the real committer
    // directly — no Spring proxy is involved, so @Transactional is a no-op here.
    // That is intentional: unit tests cover orchestration & invariants. Transactional
    // rollback semantics (especially save + outbox atomicity) require a committer
    // integration test with the real repository and real outbox store against
    // Testcontainers — see the "save + outbox atomicity" section in tests-db.md.
    // Neither fakes here nor repository-only tests there cover the join.
    var committer = new PlaceOrderCommitter(repo, outbox);
    service = new PlaceOrderService(gateway, committer, CLOCK);
  }

  @Test
  void handle_persists_order_and_records_OrderPlaced_when_payment_authorized() {
    gateway.alwaysAuthorize();

    var id = service.handle(new PlaceOrder(UUID.randomUUID(),
        List.of(new PlaceOrder.Line("SKU-1", 1, new BigDecimal("10.00"), "EUR"))));

    assertThat(repo.findById(id)).isPresent();
    assertThat(outbox.recorded()).hasSize(1)
        .first().isInstanceOf(OrderPlaced.class);
  }

  @Test
  void handle_throws_PaymentDeclined_when_gateway_declines() {
    gateway.alwaysDecline();

    assertThatThrownBy(() -> service.handle(new PlaceOrder(UUID.randomUUID(),
        List.of(new PlaceOrder.Line("SKU-1", 1, new BigDecimal("10.00"), "EUR")))))
        .isInstanceOf(PaymentDeclinedException.class);

    assertThat(repo.size()).isZero();
    assertThat(outbox.recorded()).isEmpty();
  }
}
```

## When to use Mockito

Mocks over fakes when:
- The port has many methods and you only care about one in this test.
- You need to verify *interaction patterns* (call count, argument matchers) rather than state.
- The port is truly external and has no useful in-memory implementation (e.g., a clock-like stream abstraction).

For repositories and event publishers, a fake is almost always the better choice.

## Transactional behavior

Transactions cross the application/adapter boundary. In unit tests, that boundary doesn't exist. To verify transactional rollback behavior (e.g., event publication only happens *after* a successful commit), write an integration test — see `tests-db.md`.

## Conventions

- **One behavior per test**. If a test title has "and" in it, it's two tests.
- **Arrange–Act–Assert** spacing is fine. Don't over-engineer with Given/When/Then BDD labels unless your team uses them everywhere.
- **No Spring context** in application tests. If you need one, you're writing an integration test — put it somewhere else.
