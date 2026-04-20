# Aggregate, Value Objects, Domain Events

Templates for `domain/` — the invariant-enforcement core. Zero framework imports.

Package layout:
```
order/domain/
├── model/        Order (aggregate root), OrderLine (entity), OrderId, Money, OrderStatus
├── event/        OrderEvent (sealed) + records
└── exception/    domain-specific exceptions
```

---

## Value objects

```java
// order/domain/model/OrderId.java
package com.company.ecom.order.domain.model;

import java.util.UUID;

public record OrderId(UUID value) {
  public OrderId {
    if (value == null) throw new IllegalArgumentException("OrderId must not be null");
  }
  public static OrderId newId() { return new OrderId(UUID.randomUUID()); }
  public static OrderId of(String s) { return new OrderId(UUID.fromString(s)); }
}
```

This `Money` is a **minimal pedagogical example**, not a complete monetary library. It does **not** support ISO pseudo-currencies (`XAU`, `XXX`, etc.) — `Money.zero()` will throw on a negative default-fraction-digits value. Before shipping, consider:

- `Currency.getDefaultFractionDigits()` can return `-1` for some ISO pseudo-currencies (e.g., `XAU`, `XXX`) — decide whether to reject or normalize. This template rejects them explicitly via `fractionDigits(...)`, which throws `IllegalArgumentException("unsupported currency without minor unit: ...")`. Swap that for a lookup table if your domain genuinely trades gold.
- `BigDecimal("10.0")` and `BigDecimal("10.00")` have different `scale()` — add explicit rounding/normalization if your inputs vary.
- `add` / `multiply` can produce unexpected scales; decide on a rounding mode and apply it consistently.
- No check here on negative amounts — valid for refunds/credits, invalid for prices. Enforce per use case.
- For anything beyond exploratory code, evaluate a dedicated library (Joda-Money, JavaMoney / JSR 354).

```java
// order/domain/model/Money.java  (or import from shared kernel if available)
package com.company.ecom.order.domain.model;

import java.math.BigDecimal;
import java.util.Currency;
import java.util.Objects;

public record Money(BigDecimal amount, Currency currency) {
  public Money {
    Objects.requireNonNull(amount, "amount");
    Objects.requireNonNull(currency, "currency");
    if (amount.scale() > fractionDigits(currency)) {
      throw new IllegalArgumentException("amount has more decimals than currency allows");
    }
  }

  public static Money of(String amount, String currencyCode) {
    return new Money(new BigDecimal(amount), Currency.getInstance(currencyCode));
  }

  public static Money zero(Currency currency) {
    return new Money(BigDecimal.ZERO.setScale(fractionDigits(currency)), currency);
  }

  public Money add(Money other) {
    assertSameCurrency(other);
    return new Money(amount.add(other.amount), currency);
  }

  public Money multiply(int factor) {
    return new Money(amount.multiply(BigDecimal.valueOf(factor)), currency);
  }

  // Explicit rejection of ISO pseudo-currencies (XAU, XXX, …) whose getDefaultFractionDigits()
  // returns -1. Fails loudly at the boundary instead of leaking a BigDecimal scale of -1 through
  // the arithmetic. Replace this with a lookup table if your domain genuinely trades gold.
  private static int fractionDigits(Currency currency) {
    int digits = currency.getDefaultFractionDigits();
    if (digits < 0) {
      throw new IllegalArgumentException("unsupported currency without minor unit: " + currency);
    }
    return digits;
  }

  private void assertSameCurrency(Money other) {
    if (!currency.equals(other.currency)) {
      throw new IllegalArgumentException("currency mismatch: " + currency + " vs " + other.currency);
    }
  }
}
```

```java
// order/domain/model/OrderStatus.java
package com.company.ecom.order.domain.model;

public enum OrderStatus { PLACED, PAID, SHIPPED, CANCELLED }
```

## Entity inside the aggregate

```java
// order/domain/model/OrderLine.java
package com.company.ecom.order.domain.model;

import java.util.Objects;
import java.util.UUID;

public final class OrderLine {
  private final UUID id;
  private final String sku;
  private final int quantity;
  private final Money unitPrice;

  public OrderLine(UUID id, String sku, int quantity, Money unitPrice) {
    if (quantity <= 0) throw new IllegalArgumentException("quantity must be positive");
    this.id = Objects.requireNonNull(id);
    this.sku = Objects.requireNonNull(sku);
    this.quantity = quantity;
    this.unitPrice = Objects.requireNonNull(unitPrice);
  }

  public Money subtotal() { return unitPrice.multiply(quantity); }

  public UUID id() { return id; }
  public String sku() { return sku; }
  public int quantity() { return quantity; }
  public Money unitPrice() { return unitPrice; }
}
```

## Domain exceptions

```java
// order/domain/exception/OrderAlreadyShippedException.java
package com.company.ecom.order.domain.exception;

public class OrderAlreadyShippedException extends RuntimeException {
  public OrderAlreadyShippedException() { super("order is already shipped"); }
}

// order/domain/exception/EmptyOrderException.java
public class EmptyOrderException extends RuntimeException {
  public EmptyOrderException() { super("order must have at least one line"); }
}

// order/domain/exception/InvalidOrderStateException.java
public class InvalidOrderStateException extends RuntimeException {
  public InvalidOrderStateException(String message) { super(message); }
}
```

**Optimistic-lock failure is not a domain exception.** `ConcurrentAggregateModificationException` belongs in `application/exception/` — it signals a persistence/port contract failure, not a business invariant. See `use-case.md` for the class and `db-adapter-jooq.md` for where it's thrown.

## Domain events (sealed hierarchy)

```java
// order/domain/event/OrderEvent.java
package com.company.ecom.order.domain.event;

import com.company.ecom.order.domain.model.OrderId;
import java.time.Instant;

public sealed interface OrderEvent
    permits OrderPlaced, OrderPaid, OrderShipped, OrderCancelled {
  OrderId orderId();
  Instant occurredAt();
}
```

```java
// order/domain/event/OrderPlaced.java
package com.company.ecom.order.domain.event;

import com.company.ecom.order.domain.model.*;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public record OrderPlaced(
    OrderId orderId,
    UUID customerId,
    List<OrderLine> lines,
    Money total,
    Instant occurredAt) implements OrderEvent {
  public OrderPlaced {
    lines = List.copyOf(lines);
  }
}

// Similar records for OrderPaid, OrderShipped, OrderCancelled.
```

## Aggregate root

```java
// order/domain/model/Order.java
package com.company.ecom.order.domain.model;

import com.company.ecom.order.domain.event.*;
import com.company.ecom.order.domain.exception.*;
import java.time.Clock;
import java.util.*;

public final class Order {

  private final OrderId id;
  private final UUID customerId;
  private final List<OrderLine> lines;
  private OrderStatus status;
  private long version;   // optimistic locking version, incremented by the repository on each update

  private Order(OrderId id, UUID customerId, List<OrderLine> lines, OrderStatus status, long version) {
    this.id = id;
    this.customerId = customerId;
    this.lines = new ArrayList<>(lines);
    this.status = status;
    this.version = version;
  }

  // Rule (hexagonal-ddd-java): factory enforces creation invariants.
  public static Result place(UUID customerId, List<OrderLine> lines, Clock clock) {
    if (lines == null || lines.isEmpty()) throw new EmptyOrderException();
    var order = new Order(OrderId.newId(), customerId, lines, OrderStatus.PLACED, 0L);
    var event = new OrderPlaced(order.id, customerId, List.copyOf(lines), order.total(), clock.instant());
    return new Result(order, event);
  }

  // Rehydration from persistence — infra calls this.
  public static Order rehydrate(OrderId id, UUID customerId, List<OrderLine> lines, OrderStatus status, long version) {
    return new Order(id, customerId, lines, status, version);
  }

  // Called by the repository after a successful optimistic update.
  // Named to make the persistence seam explicit — this is NOT a business operation.
  // The guard rejects going backwards, catching the "saved twice with stale state" class of bug.
  public void markPersistedAtVersion(long newVersion) {
    if (newVersion < version) {
      throw new IllegalArgumentException(
          "version cannot go backwards (was %d, got %d)".formatted(version, newVersion));
    }
    this.version = newVersion;
  }

  // Rule: aggregate-local invariants enforced by aggregate methods, not the service.
  public OrderPaid markPaid(Clock clock) {
    if (status != OrderStatus.PLACED) {
      throw new InvalidOrderStateException("must be PLACED to pay, was " + status);
    }
    status = OrderStatus.PAID;
    return new OrderPaid(id, clock.instant());
  }

  public OrderShipped ship(Clock clock) {
    if (status == OrderStatus.SHIPPED) throw new OrderAlreadyShippedException();
    if (status != OrderStatus.PAID) throw new InvalidOrderStateException("must be PAID to ship");
    status = OrderStatus.SHIPPED;
    return new OrderShipped(id, clock.instant());
  }

  public OrderCancelled cancel(Clock clock) {
    if (status == OrderStatus.SHIPPED || status == OrderStatus.CANCELLED) {
      throw new InvalidOrderStateException("cannot cancel in state " + status);
    }
    status = OrderStatus.CANCELLED;
    return new OrderCancelled(id, clock.instant());
  }

  public Money total() {
    Currency currency = lines.get(0).unitPrice().currency();
    return lines.stream()
        .map(OrderLine::subtotal)
        .reduce(Money.zero(currency), Money::add);
  }

  public OrderId id() { return id; }
  public UUID customerId() { return customerId; }
  public List<OrderLine> lines() { return List.copyOf(lines); }
  public OrderStatus status() { return status; }
  public long version() { return version; }

  public record Result(Order order, OrderPlaced event) {}
}
```

## Notes

- **Factory returns `(Order, Event)`** so the application service can persist and publish without re-reading the aggregate.
- **Behavior methods return a single event** representing the state change. Multiple events per call are fine when a real business operation produces several facts.
- **`rehydrate` is the only public constructor path** used by the repository — keep it there to avoid anemic construction from the outside.
- **`Clock` is injected**, never `Instant.now()`. See `hexagonal-ddd-java` for why.
- **`version` is a persistence concurrency token, not a business invariant**. It rides on the aggregate because rehydrated state needs to carry it, and because that is the pragmatic option for a Spring/jOOQ template. For a stricter domain, keep the token out of the aggregate and snapshot it inside the repository — heavier, but the domain stops knowing that storage has versions.
- **Save path**: `place()` creates the aggregate at version 0. The *first* save INSERTs at version 0 (no bump — there's nothing to conflict with yet). *Subsequent* saves UPDATE with `WHERE version = ?`, bump the DB column to `version + 1`, and call `markPersistedAtVersion(newVersion)` on the in-memory aggregate. See `db-adapter-jooq.md` for the SQL and `ConcurrentAggregateModificationException` (in `application/exception/`) for the failure mode.

## Variants

- **Kotlin**: use `data class` for VOs, `sealed interface` for events works the same. Avoid Kotlin's `@Service` in domain.
- **Plain Java 17 (no records)**: replace records with final classes + explicit `equals/hashCode`. Everything else is identical.
