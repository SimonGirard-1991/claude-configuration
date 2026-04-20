# Kafka Adapter (Producer + Consumer)

Infrastructure adapter for async messaging. Producer implements an outbound port; consumer is a driving adapter that translates integration events into commands.

Package layout:
```
order/infrastructure/messaging/
├── outbox/
│   ├── JdbcOrderEventOutbox.java        (implements OrderEventOutbox port)
│   └── OutboxKafkaRelay.java            (publishes outbox rows to Kafka after commit)
├── producer/
│   └── mapper/OrderIntegrationEventMapper.java
└── consumer/
    ├── PaymentEventsConsumer.java        (subscribes to Billing integration events)
    └── mapper/PaymentEventTranslator.java (ACL — foreign event → local command)
```

---

## Outbound event publication — outbox + relay

The application port is `OrderEventOutbox` (see `use-case.md`), not a direct Kafka publisher. The service writes events to an outbox **table** in the same DB transaction as the aggregate. A separate **relay** reads the outbox after commit and publishes to Kafka. This keeps state change and event publication atomic from the caller's perspective, without holding a distributed transaction.

Two pieces live here:

1. `JdbcOrderEventOutbox` — implements `OrderEventOutbox`, writes to an `order_event_outbox` table.
2. `OutboxKafkaRelay` — scheduled process (or CDC consumer via Debezium) that drains the outbox to Kafka and marks rows as published.

Full outbox implementation is out of scope for this skill — it's a discrete architectural concern. The template below shows the **shape** of the outbox-writing side; the relay is a one-line placeholder.

### Outbox writer

```java
// order/infrastructure/messaging/outbox/JdbcOrderEventOutbox.java
package com.company.ecom.order.infrastructure.messaging.outbox;

import com.company.ecom.order.application.port.OrderEventOutbox;
import com.company.ecom.order.domain.event.OrderEvent;
import com.company.ecom.order.infrastructure.messaging.producer.mapper.OrderIntegrationEventMapper;

import org.jooq.DSLContext;
import org.springframework.stereotype.Component;

@Component
public class JdbcOrderEventOutbox implements OrderEventOutbox {

  private final DSLContext dsl;
  private final OrderIntegrationEventMapper mapper;

  public JdbcOrderEventOutbox(DSLContext dsl, OrderIntegrationEventMapper mapper) {
    this.dsl = dsl;
    this.mapper = mapper;
  }

  @Override
  public void record(OrderEvent event) {
    // Rule: called INSIDE the application-service transaction. Atomic with aggregate save.
    var integration = mapper.toIntegration(event);
    // dsl.insertInto(ORDER_EVENT_OUTBOX)... (implementation: serialize `integration` as JSONB + metadata)
  }
}

```

### Kafka relay

```java
// order/infrastructure/messaging/outbox/OutboxKafkaRelay.java
// Reads unpublished outbox rows AFTER commit and publishes to Kafka. Marks rows published on success.
// Can be a @Scheduled Spring task, a dedicated worker, or replaced by Debezium CDC on the outbox table.
```

### Integration event mapper

Maps internal domain events to the versioned wire format shared with other BCs.

```java
// order/infrastructure/messaging/producer/mapper/OrderIntegrationEventMapper.java
@Component
public class OrderIntegrationEventMapper {

  public Object toIntegration(OrderEvent event) {
    return switch (event) {
      case OrderPlaced e    -> new OrderPlacedV1(e.orderId().value(), e.customerId(), e.total().amount(), e.total().currency().getCurrencyCode(), e.occurredAt());
      case OrderPaid e      -> new OrderPaidV1(e.orderId().value(), e.occurredAt());
      case OrderShipped e   -> new OrderShippedV1(e.orderId().value(), e.occurredAt());
      case OrderCancelled e -> new OrderCancelledV1(e.orderId().value(), e.occurredAt());
    };
  }

  // Integration events live here — they are the *published language*.
  public record OrderPlacedV1(UUID orderId, UUID customerId, BigDecimal total, String currency, Instant occurredAt) {}
  public record OrderPaidV1(UUID orderId, Instant occurredAt) {}
  public record OrderShippedV1(UUID orderId, Instant occurredAt) {}
  public record OrderCancelledV1(UUID orderId, Instant occurredAt) {}
}
```

Notes:
- **Integration events are versioned** (`V1`). Evolve additively; never break old consumers.
- **Partition key** is the aggregate id — preserves per-aggregate ordering.
- **The relay** uses the same mapper and publishes `integration` payloads to `ecom.order.events.v1`. It never reads domain events directly from the aggregate table.

## Consumer — driving adapter (ACL in action)

```java
// order/infrastructure/messaging/consumer/PaymentEventsConsumer.java
package com.company.ecom.order.infrastructure.messaging.consumer;

import com.company.ecom.order.application.MarkOrderPaidService;
import com.company.ecom.order.infrastructure.messaging.consumer.mapper.PaymentEventTranslator;

import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class PaymentEventsConsumer {

  private final MarkOrderPaidService service;
  private final PaymentEventTranslator translator;

  public PaymentEventsConsumer(MarkOrderPaidService service, PaymentEventTranslator translator) {
    this.service = service;
    this.translator = translator;
  }

  // Rule (hexagonal-ddd-java): we consume Billing's *integration* events, never its domain events.
  // Rule: ack after successful handling. Duplicate delivery is the norm — handler must be idempotent.
  @KafkaListener(topics = "ecom.billing.events.v1", groupId = "ecom.order.payments-consumer")
  public void onPaymentEvent(PaymentEventTranslator.IncomingPaymentEvent event) {
    translator.translate(event).ifPresent(service::handle);
  }
}
```

```java
// order/infrastructure/messaging/consumer/mapper/PaymentEventTranslator.java
@Component
public class PaymentEventTranslator {

  // Foreign wire type — lives at the adapter boundary, never in domain.
  public record IncomingPaymentEvent(String type, UUID orderId, String status, Instant ts) {}

  public Optional<MarkOrderPaid> translate(IncomingPaymentEvent event) {
    if (!"PaymentCaptured".equals(event.type())) return Optional.empty();
    if (!"SUCCESS".equals(event.status())) return Optional.empty();
    return Optional.of(new MarkOrderPaid(new OrderId(event.orderId())));
  }
}
```

## Idempotency

Integration event delivery is at-least-once. Make handlers idempotent:

- **Natural idempotency**: `markPaid` on an already-paid order should no-op (enforce in the aggregate: throw only on *conflicting* states, accept replays of the same fact).
- **Processed-message table**: persist `(topic, partition, offset)` or a business key before side effects. Skip on duplicate.

The skill does not scaffold a full processed-message store — that's an optional persistence concern.

## Variants

- **Quarkus**: Reactive Messaging with `@Incoming`/`@Outgoing` channels.
- **Micronaut**: `@KafkaListener` (micronaut-kafka) + `@KafkaClient` for producers.
- **Plain Java**: `KafkaProducer`/`KafkaConsumer` directly; wrap in a composition-root worker thread.
