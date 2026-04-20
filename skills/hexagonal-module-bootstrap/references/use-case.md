# Application Service (Use Case) + Command + Ports

Templates for `application/`. Orchestrates the domain and owns transaction demarcation.

**Dependency note**: in the default Spring variant below, application services use `@Service` and `@Transactional`. That makes them Spring-aware, not framework-free. For stricter hexagonal isolation, move DI/transaction concerns into a decorator or composition root (see *Variants* at the bottom). Most pragmatic Spring projects accept this coupling; be explicit about the choice.

Package layout:
```
order/application/
├── command/                   PlaceOrder, ShipOrder, CancelOrder
├── exception/                 ConcurrentAggregateModificationException, PaymentDeclinedException
├── port/                      OrderRepository, PaymentGateway, OrderEventOutbox
├── PlaceOrderService.java     orchestrates, runs external I/O OUTSIDE the transaction
└── PlaceOrderCommitter.java   short @Transactional: save aggregate + record outbox
```

---

## Command

```java
// order/application/command/PlaceOrder.java
package com.company.ecom.order.application.command;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;

public record PlaceOrder(UUID customerId, List<Line> lines) {
  public PlaceOrder {
    if (customerId == null) throw new IllegalArgumentException("customerId required");
    if (lines == null || lines.isEmpty()) throw new IllegalArgumentException("lines required");
    lines = List.copyOf(lines);
  }

  // Lightweight DTO used by the command only.
  // Rule: identity generation (OrderLine.id) is NOT the adapter's concern.
  // Lines arrive ID-less; the domain or application assigns IDs.
  public record Line(String sku, int quantity, BigDecimal unitPrice, String currency) {}
}
```

Commands are records. They represent *intent from the outside*. Validate shape here; validate *business invariants* in the domain. Keep domain types (`OrderLine`, `Money`) out of commands — those conversions happen inside the service, which is also the right place to assign domain identities.

## Outbound ports

```java
// order/application/port/OrderRepository.java
package com.company.ecom.order.application.port;

import com.company.ecom.order.domain.model.Order;
import com.company.ecom.order.domain.model.OrderId;
import java.util.Optional;

public interface OrderRepository {
  void save(Order order);
  Optional<Order> findById(OrderId id);
}
```

```java
// order/application/port/PaymentGateway.java
package com.company.ecom.order.application.port;

import com.company.ecom.order.domain.model.Money;
import com.company.ecom.order.domain.model.OrderId;

public interface PaymentGateway {
  PaymentResult authorize(OrderId orderId, Money amount);

  record PaymentResult(boolean authorized, String providerRef) {}
}
```

```java
// order/application/port/OrderEventOutbox.java
package com.company.ecom.order.application.port;

import com.company.ecom.order.domain.event.OrderEvent;

// Rule: events committed atomically with aggregate state.
// The port is named "outbox" (not "publisher") to prevent the naive
// "publish to Kafka inside the transaction" implementation from looking correct.
// A concrete outbox implementation persists to a table in the same transaction;
// a separate relay process reads that table and publishes to the broker.
// A direct Kafka publisher is acceptable only if losing an event on broker failure
// is tolerable for your domain — rarely the case.
public interface OrderEventOutbox {
  void record(OrderEvent event);
}
```

Port naming rules:
- **Domain-oriented, not technology-oriented**: `OrderRepository`, not `OrderJooqRepository`; `PaymentGateway`, not `StripeClient`.
- If you rename a port to match its implementation, it's a sign the port is leaking tech.

## Application exceptions

```java
// order/application/exception/ConcurrentAggregateModificationException.java
package com.company.ecom.order.application.exception;

import com.company.ecom.order.domain.model.OrderId;

// Thrown by OrderRepository.save(...) when an optimistic-lock conflict is detected
// (the row was modified by another transaction since this aggregate was loaded).
// Lives in application/, not domain/ — optimistic locking is a port/infrastructure
// contract, not a business invariant.
public class ConcurrentAggregateModificationException extends RuntimeException {
  public ConcurrentAggregateModificationException(OrderId id, long expectedVersion) {
    super("order %s was modified concurrently (expected version %d)".formatted(id, expectedVersion));
  }
}
```

## Application service

Two beans, not one. External I/O lives on the orchestrator; the transaction lives on a dedicated committer. This split is **required**, not cosmetic: Spring's proxy-based AOP does **not** apply `@Transactional` to self-invocations (`this.persistCommitted(...)`). A single-class version with `@Transactional` on a private helper silently runs without a transaction.

```java
// order/application/PlaceOrderService.java
package com.company.ecom.order.application;

import com.company.ecom.order.application.command.PlaceOrder;
import com.company.ecom.order.application.port.*;
import com.company.ecom.order.domain.model.*;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.util.Currency;
import java.util.UUID;

@Service
public class PlaceOrderService {

  private final PaymentGateway paymentGateway;
  private final PlaceOrderCommitter committer;
  private final Clock clock;

  public PlaceOrderService(PaymentGateway paymentGateway, PlaceOrderCommitter committer, Clock clock) {
    this.paymentGateway = paymentGateway;
    this.committer = committer;
    this.clock = clock;
  }

  // Rule: external I/O runs OUTSIDE the DB transaction.
  // Keeps the transaction short, avoids holding locks across remote calls.
  public OrderId handle(PlaceOrder cmd) {
    var lines = cmd.lines().stream()
        .map(l -> new OrderLine(
            UUID.randomUUID(),            // Rule: identity generated here, not in the adapter.
            l.sku(),
            l.quantity(),
            new Money(l.unitPrice(), Currency.getInstance(l.currency()))))
        .toList();
    var result = Order.place(cmd.customerId(), lines, clock);
    var order = result.order();

    var auth = paymentGateway.authorize(order.id(), order.total());
    if (!auth.authorized()) throw new PaymentDeclinedException(order.id());

    committer.commit(order, result.event());
    return order.id();
  }
}
```

```java
// order/application/PlaceOrderCommitter.java
package com.company.ecom.order.application;

import com.company.ecom.order.application.port.*;
import com.company.ecom.order.domain.event.OrderEvent;
import com.company.ecom.order.domain.model.Order;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PlaceOrderCommitter {

  private final OrderRepository orderRepository;
  private final OrderEventOutbox outbox;

  public PlaceOrderCommitter(OrderRepository orderRepository, OrderEventOutbox outbox) {
    this.orderRepository = orderRepository;
    this.outbox = outbox;
  }

  // Rule: short transaction, persistence + outbox only, no external I/O.
  // Called from another bean → proxy is traversed → @Transactional is actually applied.
  @Transactional
  public void commit(Order order, OrderEvent event) {
    orderRepository.save(order);
    outbox.record(event);
  }
}
```

## Notes

- **Two beans, one transaction**: splitting `PlaceOrderService` and `PlaceOrderCommitter` also expresses a clean separation — orchestration (with external I/O, retries, saga hooks) on one bean, the atomic state change (`save` + `record`) on another. It sidesteps Spring's proxy self-invocation limitation as a side effect, but even without that constraint the boundary is the one you'd want to draw. Alternatives: `AopContext.currentProxy()` (fragile), `TransactionTemplate` (more verbose, explicit), or AspectJ weaving (heavier build).
- **External call outside the transaction**: `paymentGateway.authorize(...)` runs before `commit(...)`. Holding a DB transaction across an HTTP call is a common anti-pattern — long locks, ambiguous retries, timeout cascades.
- **Authorized-but-not-persisted is a real hazard**: if `committer.commit(...)` fails after authorization succeeds, the provider still holds an authorization. Mitigations, in order of preference:
  1. Model the workflow as a saga with explicit `AUTHORIZED → PAID` states and a compensating `voidAuthorization` step on persistence failure.
  2. Rely on the provider's authorization expiry (hours-to-days for most card networks) and reconcile via a scheduled job.
  3. Use an idempotency key on the gateway so a retry of the whole use case reuses the same authorization instead of creating a duplicate charge.
  Do **not** pretend the problem doesn't exist — name the chosen mitigation in your code.
- **Idempotency key must be stable across client retries**: `orderId` is *not* a good idempotency key on its own — each call to `handle()` generates a new `OrderId`, so a client retry produces a second order with a second authorization. Either (a) accept a `clientRequestId`/`Idempotency-Key` header through the command and persist a "pending order" row before calling the gateway, or (b) key the gateway off something stable the client owns (cart id, checkout session id). The `orderId.toString()` seen in the ACL template is fine for *provider-side* deduplication within a single `handle()` call but does nothing for the retry-from-the-browser case.
- **Event delivery via outbox**: `outbox.record(event)` writes to a table in the *same* transaction as `orderRepository.save(order)`. A relay process publishes from that table to Kafka *after commit*. Never call `kafkaTemplate.send(...)` directly from the service — if the broker succeeds and the transaction rolls back (or vice versa), you get divergent state. Outbox implementation itself is out of scope for this skill.
- **One public method per use case**. Name it `handle`, `execute`, or after the command (`placeOrder`). Pick one convention per codebase.
- **Identity generation** (`UUID.randomUUID()` for order lines) lives in the service, not in adapters. Alternatives: inject an `IdGenerator` port, or have the domain assign IDs inside `Order.place(...)`.

## Variants

- **Quarkus**: replace `@Service` with `@ApplicationScoped`, `@Transactional` is `jakarta.transaction.Transactional`.
- **Micronaut**: `@Singleton` + `io.micronaut.transaction.annotation.Transactional`.
- **Plain Java / stricter hexagonal**: the application service is a plain class; wiring and transaction boundaries live in a composition root or a `Transactional` decorator implemented in `infrastructure/`. The service stays framework-free, at the cost of one extra indirection.
