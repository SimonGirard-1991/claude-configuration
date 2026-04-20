# Domain Tests

Pure JUnit. No Spring, no mocks, no database, no network. Inject `Clock.fixed()` for determinism.

Domain tests should read like business specifications. If you need a mock here, the test is at the wrong layer.

---

## Placement

```
src/test/java/com/company/ecom/order/domain/model/
├── OrderTest.java
├── MoneyTest.java
└── OrderLineTest.java
```

Mirror the production package structure.

## Aggregate behavior

```java
// OrderTest.java
package com.company.ecom.order.domain.model;

import com.company.ecom.order.domain.event.*;
import com.company.ecom.order.domain.exception.*;
import org.junit.jupiter.api.Test;

import java.time.*;
import java.util.*;

import static org.assertj.core.api.Assertions.*;

class OrderTest {

  private static final Clock CLOCK =
      Clock.fixed(Instant.parse("2026-01-15T10:00:00Z"), ZoneOffset.UTC);

  private static final UUID CUSTOMER = UUID.randomUUID();

  @Test
  void place_with_lines_emits_OrderPlaced() {
    var line = aLine("SKU-1", 2, "10.00");

    var result = Order.place(CUSTOMER, List.of(line), CLOCK);

    assertThat(result.order().status()).isEqualTo(OrderStatus.PLACED);
    assertThat(result.event().lines()).containsExactly(line);
    assertThat(result.event().total()).isEqualTo(Money.of("20.00", "EUR"));
    assertThat(result.event().occurredAt()).isEqualTo(CLOCK.instant());
  }

  @Test
  void place_with_no_lines_rejects() {
    assertThatThrownBy(() -> Order.place(CUSTOMER, List.of(), CLOCK))
        .isInstanceOf(EmptyOrderException.class);
  }

  @Test
  void ship_requires_PAID_state() {
    var order = placedOrder();
    assertThatThrownBy(() -> order.ship(CLOCK))
        .isInstanceOf(InvalidOrderStateException.class);
  }

  @Test
  void ship_a_paid_order_transitions_to_SHIPPED() {
    var order = placedOrder();
    order.markPaid(CLOCK);

    var event = order.ship(CLOCK);

    assertThat(order.status()).isEqualTo(OrderStatus.SHIPPED);
    assertThat(event.orderId()).isEqualTo(order.id());
  }

  @Test
  void cannot_ship_twice() {
    var order = placedOrder();
    order.markPaid(CLOCK);
    order.ship(CLOCK);

    assertThatThrownBy(() -> order.ship(CLOCK))
        .isInstanceOf(OrderAlreadyShippedException.class);
  }

  // helpers

  private Order placedOrder() {
    return Order.place(CUSTOMER, List.of(aLine("SKU-1", 1, "10.00")), CLOCK).order();
  }

  private OrderLine aLine(String sku, int qty, String price) {
    return new OrderLine(UUID.randomUUID(), sku, qty, Money.of(price, "EUR"));
  }
}
```

## Value object tests

```java
// MoneyTest.java
class MoneyTest {

  @Test
  void rejects_amount_with_too_many_decimals_for_currency() {
    assertThatThrownBy(() -> Money.of("10.123", "EUR"))
        .isInstanceOf(IllegalArgumentException.class);
  }

  @Test
  void add_same_currency_sums_amounts() {
    assertThat(Money.of("10.00", "EUR").add(Money.of("5.50", "EUR")))
        .isEqualTo(Money.of("15.50", "EUR"));
  }

  @Test
  void add_different_currency_rejects() {
    assertThatThrownBy(() -> Money.of("10.00", "EUR").add(Money.of("5.00", "USD")))
        .isInstanceOf(IllegalArgumentException.class);
  }
}
```

## Conventions

- **Test names** describe the behavior in the business language (`ship_requires_PAID_state`, not `testShip2`).
- **One fixed clock** at class level. Use `Clock.fixed(...)` — never `Clock.systemUTC()` in tests.
- **AssertJ** for fluent assertions. It reads better than JUnit's `assertEquals`.
- **No `@SpringBootTest`, no `@ExtendWith(MockitoExtension.class)`** — pure Java.
- **Parameterized tests** for invariant tables (valid/invalid states): `@ParameterizedTest` + `@MethodSource`.

## Coverage expectations

Domain tests are the cheapest tests you will ever write. Aim for exhaustive invariant coverage: every branch in aggregate methods, every validation in VOs. Mutation testing (PIT) is worth running on the `domain/` package — the signal-to-noise is excellent there.
