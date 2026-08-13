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

Full outbox implementation is out of scope for this skill — it's a discrete architectural concern. The template below shows the **shape** of the outbox-writing side; the relay is described but not scaffolded.

### Outbox writer

```java
// order/infrastructure/messaging/outbox/JdbcOrderEventOutbox.java
package com.company.ecom.order.infrastructure.messaging.outbox;

import com.company.ecom.order.application.port.OrderEventOutbox;
import com.company.ecom.order.domain.event.OrderEvent;
import com.company.ecom.order.infrastructure.messaging.producer.mapper.OrderIntegrationEventMapper;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.jooq.DSLContext;
import org.jooq.JSONB;
import org.springframework.stereotype.Component;

import java.util.UUID;

import static com.company.ecom.generated.jooq.Tables.ORDER_EVENT_OUTBOX;

@Component
public class JdbcOrderEventOutbox implements OrderEventOutbox {

  private final DSLContext dsl;
  private final OrderIntegrationEventMapper mapper;
  private final ObjectMapper objectMapper;

  public JdbcOrderEventOutbox(DSLContext dsl, OrderIntegrationEventMapper mapper, ObjectMapper objectMapper) {
    this.dsl = dsl;
    this.mapper = mapper;
    this.objectMapper = objectMapper;
  }

  @Override
  public void record(OrderEvent event) {
    dsl.insertInto(ORDER_EVENT_OUTBOX)
        .set(ORDER_EVENT_OUTBOX.ID, UUID.randomUUID())
        .set(ORDER_EVENT_OUTBOX.AGGREGATE_ID, event.orderId().value())
        .set(ORDER_EVENT_OUTBOX.PAYLOAD, JSONB.valueOf(toJson(mapper.toIntegration(event))))
        .set(ORDER_EVENT_OUTBOX.OCCURRED_AT, event.occurredAt())
        .execute();
  }

  private String toJson(Object payload) {
    try {
      return objectMapper.writeValueAsString(payload);
    } catch (JsonProcessingException e) {
      throw new IllegalStateException("cannot serialize integration event: " + payload.getClass(), e);
    }
  }
}
```

`record` is called *inside* the application-service transaction, which is the whole point: the outbox row commits atomically with the aggregate save.

### Kafka relay

`OutboxKafkaRelay` (in `order/infrastructure/messaging/outbox/`) reads unpublished outbox rows **after** commit, publishes them to Kafka, and marks the rows published on success. It can be a `@Scheduled` Spring task, a dedicated worker, or replaced entirely by Debezium CDC on the outbox table.

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

  public record OrderPlacedV1(UUID orderId, UUID customerId, BigDecimal total, String currency, Instant occurredAt) {}
  public record OrderPaidV1(UUID orderId, Instant occurredAt) {}
  public record OrderShippedV1(UUID orderId, Instant occurredAt) {}
  public record OrderCancelledV1(UUID orderId, Instant occurredAt) {}
}
```

Notes:
- **The `V1` records nested in the mapper are the published language** — the vocabulary other bounded contexts consume. Keeping them here, beside the translation that produces them, is deliberate.
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

  @KafkaListener(topics = "ecom.billing.events.v1", groupId = "ecom.order.payments-consumer")
  public void onPaymentEvent(PaymentEventTranslator.IncomingPaymentEvent event) {
    translator.translate(event).ifPresent(service::handle);
  }
}
```

Two constraints govern this consumer, and neither is visible in the code:

- **It subscribes to Billing's *integration* events, never its domain events** (`hexagonal-ddd-java`). Domain events are Billing's internal language and are not a contract.
- **Ack after successful handling, and make the handler idempotent.** Duplicate delivery is the norm, not the exception.

```java
// order/infrastructure/messaging/consumer/mapper/PaymentEventTranslator.java
@Component
public class PaymentEventTranslator {

  public record IncomingPaymentEvent(String type, UUID orderId, String status, Instant ts) {}

  public Optional<MarkOrderPaid> translate(IncomingPaymentEvent event) {
    if (!"PaymentCaptured".equals(event.type())) return Optional.empty();
    if (!"SUCCESS".equals(event.status())) return Optional.empty();
    return Optional.of(new MarkOrderPaid(new OrderId(event.orderId())));
  }
}
```

`IncomingPaymentEvent` is a foreign wire type: it belongs to Billing's schema, lives at the adapter boundary, and never travels into `domain/`. Translating it into a `MarkOrderPaid` command here is what stops Billing's model leaking inward.

## Idempotency

Integration event delivery is at-least-once. Make handlers idempotent:

- **Natural idempotency**: `markPaid` on an already-paid order should no-op (enforce in the aggregate: throw only on *conflicting* states, accept replays of the same fact).
- **Processed-message table**: persist `(topic, partition, offset)` or a business key before side effects. Skip on duplicate.

The skill does not scaffold a full processed-message store — that's an optional persistence concern.

## Variants

- **Quarkus**: Reactive Messaging with `@Incoming`/`@Outgoing` channels.
- **Micronaut**: `@KafkaListener` (micronaut-kafka) + `@KafkaClient` for producers.
- **Plain Java**: `KafkaProducer`/`KafkaConsumer` directly; wrap in a composition-root worker thread.
