# gRPC Adapter

Driving adapter for gRPC. Same layering rules as REST: map proto ↔ domain/application, never leak generated types past the adapter.

Package layout:
```
order/infrastructure/grpc/
├── OrderGrpcService.java       (extends generated OrderServiceImplBase)
└── mapper/
    ├── PlaceOrderGrpcMapper.java
    └── OrderGrpcResponseMapper.java

src/main/proto/order/v1/order.proto
```

---

## Proto definition

```proto
// src/main/proto/order/v1/order.proto
syntax = "proto3";

package ecom.order.v1;

option java_multiple_files = true;
option java_package = "com.company.ecom.order.grpc.v1";

import "google/protobuf/timestamp.proto";

service OrderService {
  rpc PlaceOrder (PlaceOrderRequest) returns (PlaceOrderResponse);
  rpc GetOrder   (GetOrderRequest)   returns (OrderMessage);
}

message PlaceOrderRequest {
  string customer_id = 1;
  repeated OrderLineMessage lines = 2;
}

message PlaceOrderResponse { string order_id = 1; }

message GetOrderRequest { string order_id = 1; }

message OrderLineMessage {
  string sku = 1;
  int32 quantity = 2;
  string unit_price = 3;  // decimal string, avoids float drift
  string currency = 4;
}

message OrderMessage {
  string id = 1;
  string customer_id = 2;
  repeated OrderLineMessage lines = 3;
  string total = 4;
  string currency = 5;
  string status = 6;
}
```

## Service implementation

```java
// order/infrastructure/grpc/OrderGrpcService.java
package com.company.ecom.order.infrastructure.grpc;

import com.company.ecom.order.application.PlaceOrderService;
import com.company.ecom.order.application.OrderReadService;
import com.company.ecom.order.application.exception.ConcurrentAggregateModificationException;
import com.company.ecom.order.domain.exception.*;
import com.company.ecom.order.domain.model.OrderId;
import com.company.ecom.order.grpc.v1.*;

import io.grpc.Status;
import io.grpc.stub.StreamObserver;
import net.devh.boot.grpc.server.service.GrpcService;

import java.util.UUID;

@GrpcService
public class OrderGrpcService extends OrderServiceGrpc.OrderServiceImplBase {

  private final PlaceOrderService placeOrderService;
  private final OrderReadService orderReadService;
  private final PlaceOrderGrpcMapper placeMapper;
  private final OrderGrpcResponseMapper responseMapper;

  public OrderGrpcService(PlaceOrderService placeOrderService,
                          OrderReadService orderReadService,
                          PlaceOrderGrpcMapper placeMapper,
                          OrderGrpcResponseMapper responseMapper) {
    this.placeOrderService = placeOrderService;
    this.orderReadService = orderReadService;
    this.placeMapper = placeMapper;
    this.responseMapper = responseMapper;
  }

  @Override
  public void placeOrder(PlaceOrderRequest req, StreamObserver<PlaceOrderResponse> out) {
    try {
      var id = placeOrderService.handle(placeMapper.toCommand(req));
      out.onNext(PlaceOrderResponse.newBuilder().setOrderId(id.value().toString()).build());
      out.onCompleted();
    } catch (EmptyOrderException e) {
      out.onError(Status.INVALID_ARGUMENT.withDescription(e.getMessage()).asRuntimeException());
    } catch (InvalidOrderStateException | OrderAlreadyShippedException e) {
      out.onError(Status.FAILED_PRECONDITION.withDescription(e.getMessage()).asRuntimeException());
    } catch (ConcurrentAggregateModificationException e) {
      // ABORTED is the canonical gRPC status for "operation aborted, typically due to a
      // concurrency issue such as a sequencer check failure" — exactly optimistic-lock.
      // Clients should re-fetch and retry; unlike FAILED_PRECONDITION, this encodes "retry
      // is meaningful after refreshing state".
      out.onError(Status.ABORTED.withDescription(e.getMessage()).asRuntimeException());
    } catch (IllegalArgumentException e) {
      // Covers parsing-level failures surfaced as IAE: UUID.fromString(...),
      // new BigDecimal(...), Currency.getInstance(...), Money scale check, etc.
      // Without this, they bubble up as gRPC Status.UNKNOWN — misleading to callers.
      out.onError(Status.INVALID_ARGUMENT.withDescription(e.getMessage()).asRuntimeException());
    }
  }

  @Override
  public void getOrder(GetOrderRequest req, StreamObserver<OrderMessage> out) {
    try {
      var order = orderReadService.findById(new OrderId(UUID.fromString(req.getOrderId())));
      out.onNext(responseMapper.toMessage(order));
      out.onCompleted();
    } catch (IllegalArgumentException e) {
      out.onError(Status.INVALID_ARGUMENT.withDescription(e.getMessage()).asRuntimeException());
    }
  }
}
```

## Mappers

```java
// order/infrastructure/grpc/mapper/PlaceOrderGrpcMapper.java
@Component
public class PlaceOrderGrpcMapper {
  public PlaceOrder toCommand(PlaceOrderRequest req) {
    // Rule: adapter carries wire shape only — no domain types, no ID generation.
    var lines = req.getLinesList().stream()
        .map(l -> new PlaceOrder.Line(
            l.getSku(), l.getQuantity(),
            new java.math.BigDecimal(l.getUnitPrice()), l.getCurrency()))
        .toList();
    return new PlaceOrder(UUID.fromString(req.getCustomerId()), lines);
  }
}
```

```java
// order/infrastructure/grpc/mapper/OrderGrpcResponseMapper.java
@Component
public class OrderGrpcResponseMapper {
  public OrderMessage toMessage(Order order) {
    var builder = OrderMessage.newBuilder()
        .setId(order.id().value().toString())
        .setCustomerId(order.customerId().toString())
        .setTotal(order.total().amount().toPlainString())
        .setCurrency(order.total().currency().getCurrencyCode())
        .setStatus(order.status().name());
    order.lines().forEach(l -> builder.addLines(
        OrderLineMessage.newBuilder()
            .setSku(l.sku())
            .setQuantity(l.quantity())
            .setUnitPrice(l.unitPrice().amount().toPlainString())
            .setCurrency(l.unitPrice().currency().getCurrencyCode())
            .build()));
    return builder.build();
  }
}
```

## Notes

- **Generated proto types stay in `infrastructure/grpc/`**. Never import them from `application/` or `domain/`.
- **Use `string` for decimals** (money) in proto — avoid `double`/`float` for financial values.
- **Error mapping**: domain exceptions → gRPC `Status` codes at the adapter, same pattern as REST → HTTP status.
- **Versioning**: put services in `ecom.order.v1` package. A breaking change means `v2`, not editing `v1`.

## Variants

- **Spring Boot**: `net.devh:grpc-server-spring-boot-starter` provides `@GrpcService`.
- **Quarkus**: `quarkus-grpc` generates stubs; annotate with `@GrpcService`.
- **Plain Java**: use `io.grpc.ServerBuilder` in a composition-root bootstrap.
