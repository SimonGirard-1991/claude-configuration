# Web Slice Tests

Spring Boot: `@WebMvcTest` spins up the minimum context needed for a controller. Application services are mocked. No database, no security by default, no message broker.

**Scope**: test serialization, validation (as emitted by the generated Bean-Validation annotations from the OpenAPI spec), status codes, and mapping — not business logic.

**Reminder**: there are no handwritten request/response DTOs. The ones used below (`PlaceOrderV1Request`, `OrderLineV1Request`, `OrderV1Response`, …) come from the OpenAPI generator — see `rest-adapter.md`. `unitPrice` is a `String` on the wire because the contract models money as a pattern-validated string, not a JSON number.

---

## Controller test

```java
// OrderControllerTest.java
package com.company.ecom.order.infrastructure.web;

import com.company.ecom.order.application.PlaceOrderService;
import com.company.ecom.order.application.OrderReadService;
import com.company.ecom.order.domain.model.OrderId;
import com.company.ecom.order.infrastructure.web.mapper.*;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(controllers = OrderController.class)
@Import({PlaceOrderRequestMapper.class, OrderResponseMapper.class})
class OrderControllerTest {

  @Autowired MockMvc mvc;

  @MockBean PlaceOrderService placeOrderService;
  @MockBean OrderReadService orderReadService;

  @Test
  void POST_v1_orders_returns_201_with_location() throws Exception {
    var newId = new OrderId(UUID.randomUUID());
    when(placeOrderService.handle(any())).thenReturn(newId);

    mvc.perform(post("/v1/orders")
            .contentType(MediaType.APPLICATION_JSON)
            .content("""
                {
                  "customerId": "11111111-1111-1111-1111-111111111111",
                  "lines": [
                    { "sku": "SKU-1", "quantity": 2, "unitPrice": "10.00", "currency": "EUR" }
                  ]
                }
                """))
        .andExpect(status().isCreated())
        .andExpect(header().string("Location", "/v1/orders/" + newId.value()));
  }

  @Test
  void POST_v1_orders_rejects_empty_lines_with_400() throws Exception {
    mvc.perform(post("/v1/orders")
            .contentType(MediaType.APPLICATION_JSON)
            .content("""
                { "customerId": "11111111-1111-1111-1111-111111111111", "lines": [] }
                """))
        .andExpect(status().isBadRequest());
  }

  @Test
  void POST_v1_orders_rejects_malformed_json_with_400() throws Exception {
    mvc.perform(post("/v1/orders")
            .contentType(MediaType.APPLICATION_JSON)
            .content("{ not valid json"))
        .andExpect(status().isBadRequest());
  }

  @Test
  void POST_v1_orders_rejects_invalid_currency_length_with_400() throws Exception {
    mvc.perform(post("/v1/orders")
            .contentType(MediaType.APPLICATION_JSON)
            .content("""
                {
                  "customerId": "11111111-1111-1111-1111-111111111111",
                  "lines": [
                    { "sku": "SKU-1", "quantity": 1, "unitPrice": "10.00", "currency": "EURO" }
                  ]
                }
                """))
        .andExpect(status().isBadRequest());
  }

  @Test
  void POST_v1_orders_rejects_non_positive_quantity_with_400() throws Exception {
    // The spec declares `minimum: 1` on quantity, so 0 and -1 both fail at the generated
    // @Min validation before the controller method is entered.
    mvc.perform(post("/v1/orders")
            .contentType(MediaType.APPLICATION_JSON)
            .content("""
                {
                  "customerId": "11111111-1111-1111-1111-111111111111",
                  "lines": [
                    { "sku": "SKU-1", "quantity": 0, "unitPrice": "10.00", "currency": "EUR" }
                  ]
                }
                """))
        .andExpect(status().isBadRequest());
  }

  @Test
  void POST_v1_orders_rejects_unitPrice_as_number_with_400() throws Exception {
    // The spec types unitPrice as string with pattern '^\\d+(\\.\\d+)?$'.
    // A JSON number fails Jackson deserialization against a String field.
    mvc.perform(post("/v1/orders")
            .contentType(MediaType.APPLICATION_JSON)
            .content("""
                {
                  "customerId": "11111111-1111-1111-1111-111111111111",
                  "lines": [
                    { "sku": "SKU-1", "quantity": 1, "unitPrice": 10.00, "currency": "EUR" }
                  ]
                }
                """))
        .andExpect(status().isBadRequest());
  }
}
```

## Mapper tests

Mappers are trivial to test and catch silent field-rename bugs when the generator regenerates after a YAML change. Test each direction independently.

```java
// PlaceOrderRequestMapperTest.java
import com.company.ecom.order.infrastructure.web.generated.v1.OrderLineV1Request;
import com.company.ecom.order.infrastructure.web.generated.v1.PlaceOrderV1Request;

class PlaceOrderRequestMapperTest {

  private final PlaceOrderRequestMapper mapper = new PlaceOrderRequestMapper();

  @Test
  void maps_wire_fields_verbatim_without_generating_ids_or_domain_types() {
    var customerId = UUID.randomUUID();
    var req = new PlaceOrderV1Request()
        .customerId(customerId)
        .lines(List.of(new OrderLineV1Request()
            .sku("SKU-1")
            .quantity(2)
            .unitPrice("10.00")
            .currency("EUR")));

    var cmd = mapper.toCommand(req);

    assertThat(cmd.customerId()).isEqualTo(customerId);
    assertThat(cmd.lines()).hasSize(1);
    var line = cmd.lines().get(0);
    // cmd.lines() are PlaceOrder.Line (application command DTOs), not domain OrderLine/Money.
    // The mapper parses unitPrice from string to BigDecimal here; domain Money construction
    // happens later, inside the use case.
    assertThat(line.sku()).isEqualTo("SKU-1");
    assertThat(line.quantity()).isEqualTo(2);
    assertThat(line.unitPrice()).isEqualByComparingTo("10.00");
    assertThat(line.currency()).isEqualTo("EUR");
  }
}
```

## Exception-handler test

```java
// OrderExceptionHandlerTest.java — part of the same @WebMvcTest slice
@Test
void OrderAlreadyShipped_maps_to_409() throws Exception {
  when(placeOrderService.handle(any())).thenThrow(new OrderAlreadyShippedException());

  mvc.perform(post("/v1/orders").contentType(MediaType.APPLICATION_JSON).content(validBody()))
      .andExpect(status().isConflict());
}
```

## Variants

- **Quarkus**: `@QuarkusTest` + REST Assured. No slice-test equivalent — Quarkus tests are faster overall so the granularity loss is acceptable.
- **Micronaut**: `@MicronautTest` + the built-in HTTP client.

## Notes

- **Validation tests belong here**, not in domain tests. `@NotNull` / `@Min` / `@Pattern` on generated DTOs are transport concerns, not invariants.
- **Never call the real service**. The point of a slice test is isolation.
- **Include the mappers in the slice** via `@Import`, otherwise `MockMvc` can't resolve them.
- **Routes carry the `/v1` prefix** because the spec declares `servers: - url: /v1`. Tests assert on the full `/v1/orders` path to match what the generated interface wires up; if you assert on `/orders` the test passes under a bare controller but breaks the day someone reviews the contract.
