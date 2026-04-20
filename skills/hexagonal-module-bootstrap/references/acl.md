# Anti-Corruption Layer (ACL)

An ACL keeps a foreign model (external API, legacy system, another BC's events) out of your domain. It lives in `infrastructure/acl/` of the consuming BC.

**When to use an ACL**:
- You consume an external API or legacy system whose model would pollute your domain.
- You consume integration events from another BC.
- You call a SaaS (Stripe, Shopify, SAP, etc.) and want one well-defined seam.

**When NOT to use an ACL**:
- You call your own internal library under your team's control and the model already fits — over-layering is a real cost.
- The external API is already shaped exactly like your domain (rare; verify twice).

---

## Package layout

```
order/infrastructure/acl/payment/
├── PaymentGatewayAcl.java        (implements PaymentGateway port)
├── client/
│   └── StripeClient.java         (thin HTTP wrapper — foreign types only)
└── translator/
    └── PaymentTranslator.java    (foreign → domain)
```

---

## Port (defined in `application/`)

Already shown in `use-case.md`:

```java
// order/application/port/PaymentGateway.java
public interface PaymentGateway {
  PaymentResult authorize(OrderId orderId, Money amount);
  record PaymentResult(boolean authorized, String providerRef) {}
}
```

## ACL implementation

```java
// order/infrastructure/acl/payment/PaymentGatewayAcl.java
package com.company.ecom.order.infrastructure.acl.payment;

import com.company.ecom.order.application.port.PaymentGateway;
import com.company.ecom.order.domain.model.Money;
import com.company.ecom.order.domain.model.OrderId;

import org.springframework.stereotype.Component;

@Component
public class PaymentGatewayAcl implements PaymentGateway {

  private final StripeClient client;
  private final PaymentTranslator translator;

  public PaymentGatewayAcl(StripeClient client, PaymentTranslator translator) {
    this.client = client;
    this.translator = translator;
  }

  @Override
  public PaymentResult authorize(OrderId orderId, Money amount) {
    // Rule (hexagonal-ddd-java): foreign types stop here. Domain never sees StripeChargeResponse.
    var foreign = client.charge(translator.toStripeCharge(orderId, amount));
    return translator.toDomainResult(foreign);
  }
}
```

## Foreign client

```java
// order/infrastructure/acl/payment/client/StripeClient.java
package com.company.ecom.order.infrastructure.acl.payment.client;

import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class StripeClient {

  private final RestClient rest;

  public StripeClient(RestClient.Builder builder,
                      @Value("${stripe.base-url}") String baseUrl,
                      @Value("${stripe.api-key}") String apiKey) {
    this.rest = builder.baseUrl(baseUrl)
        .defaultHeader("Authorization", "Bearer " + apiKey)
        .build();
  }

  public StripeChargeResponse charge(StripeChargeRequest req) {
    return rest.post().uri("/v1/charges")
        .body(req)
        .retrieve()
        .body(StripeChargeResponse.class);
  }

  // Foreign wire types live here — never imported from domain/application.
  public record StripeChargeRequest(long amountCents, String currency, String idempotencyKey, String description) {}
  public record StripeChargeResponse(String id, String status, String failureCode) {}
}
```

## Translator

```java
// order/infrastructure/acl/payment/translator/PaymentTranslator.java
package com.company.ecom.order.infrastructure.acl.payment.translator;

import com.company.ecom.order.application.port.PaymentGateway.PaymentResult;
import com.company.ecom.order.domain.model.Money;
import com.company.ecom.order.domain.model.OrderId;
import com.company.ecom.order.infrastructure.acl.payment.client.StripeClient.*;

import org.springframework.stereotype.Component;

@Component
public class PaymentTranslator {

  public StripeChargeRequest toStripeCharge(OrderId orderId, Money amount) {
    long cents = amount.amount()
        .movePointRight(amount.currency().getDefaultFractionDigits())
        .longValueExact();
    return new StripeChargeRequest(
        cents,
        amount.currency().getCurrencyCode().toLowerCase(),
        orderId.value().toString(),       // use orderId as idempotency key
        "Order " + orderId.value());
  }

  public PaymentResult toDomainResult(StripeChargeResponse response) {
    boolean ok = "succeeded".equals(response.status());
    return new PaymentResult(ok, response.id());
  }
}
```

## Notes

- **The ACL is a bidirectional seam**: translator has two methods, one per direction. No domain type appears in foreign shapes; no foreign type appears in domain shapes.
- **Idempotency**: pass a stable key (aggregate id) to the external system whenever possible. Retries are real.
- **Error handling**: foreign exceptions (`RestClientException`, timeouts) are caught here and either mapped to a domain-meaningful result (`PaymentResult` with `authorized=false`) or wrapped in a specific application exception. Never let `org.springframework.web.client.*` leak out.
- **Observability**: put tracing/logging here; adapters are the right place.

## Resilience (production checklist)

These templates omit resilience for clarity. Before shipping any ACL, add:

- **Timeouts** — both connect and read. Never use the framework default (often infinite).
- **Retries** — only for idempotent operations, with jitter + exponential backoff. Use Resilience4j, Spring Retry, or a framework equivalent.
- **Circuit breaker** — around the outbound call; fail fast when the provider is down rather than exhausting threads.
- **Bulkhead / rate limiting** — isolate calls to this provider from the rest of the app's thread pool.
- **Fallback** — explicit "payment temporarily unavailable" result type rather than propagating infrastructure exceptions.

These are cross-cutting concerns; wire them via Spring Boot actuator + Resilience4j annotations, not by hand-rolling retry loops inside the translator.

For async (Kafka-consumer) ACLs, the resilience toolkit is different — dead-letter topics, consumer retries, poison-pill handling. See `kafka-adapter.md` → idempotency and consumer patterns.

## ACL for inbound integration events

Same pattern inverted: a Kafka consumer (driving adapter) uses a translator to map foreign integration events into local commands. See `kafka-adapter.md`'s `PaymentEventTranslator` for the shape.

## Variants

- **Quarkus**: use `quarkus-rest-client-reactive` for the client; everything else is unchanged.
- **Micronaut**: `@Client` interface for the HTTP client.
- **Plain Java**: `java.net.http.HttpClient` in `StripeClient`.
