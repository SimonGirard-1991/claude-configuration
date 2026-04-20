# REST Adapter (Contract-First)

Driving adapter in `infrastructure/web/`. Translates HTTP ↔ application commands/queries. Owns no business rules.

**The OpenAPI YAML is the source of truth.** Handlers implement interfaces generated from the contract. You never write `@RestController` + `@PostMapping` + request DTOs by hand — the generator does that from the spec. A handler that diverges from the contract fails the build, not staging, not production.

This is the same pattern `grpc-adapter.md` uses (proto as contract) and the same pattern `kafka-adapter.md` uses for integration events (Avro/Protobuf + Schema Registry). REST is not the exception.

Package layout:

```
order/
└── infrastructure/web/
    ├── generated/v1/                   generated — DO NOT EDIT, DO NOT COMMIT
    │   ├── OrderApi.java               generated interface (the contract)
    │   ├── PlaceOrderV1Request.java    generated DTO
    │   └── OrderV1Response.java        generated DTO
    ├── OrderController.java            implements OrderApi
    ├── mapper/
    │   ├── PlaceOrderRequestMapper.java
    │   └── OrderResponseMapper.java
    └── OrderExceptionHandler.java
```

**Rule**: generated types live *inside* the web adapter package (`order/infrastructure/web/generated/v1/`) and **stop at the web package**. They are web-adapter types, not bounded-context public API. Do not confuse this with the `api/` package used by `module-declaration.md` — that one is the Spring Modulith `::api` named interface for cross-BC imports (commands, events, facades). The REST transport contract and the BC public API are different things; keep them in different packages so they can't be mixed up. Never import generated REST types from `application/` or `domain/`. Same rule as proto classes in `grpc-adapter.md`. An ArchUnit rule in `tests-architecture.md` enforces this.

---

## OpenAPI contract

```yaml
# src/main/resources/openapi/order-v1.yaml
# OpenAPI 3.0.3 is the safe default: the Java/Spring generators have years of mileage
# against it. 3.1.0 has cleaner JSON Schema semantics (true draft-2020-12 alignment,
# no more `nullable`), but generator support is still uneven across versions. If your
# team has explicitly validated 3.1.0 against the generator version pinned below, bump it.
openapi: 3.0.3
info:
  title: Order API
  version: 1.0.0
servers:
  - url: /v1

tags:
  - name: orders

paths:
  /orders:
    post:
      tags: [orders]
      operationId: placeOrder
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/PlaceOrderV1Request' }
      responses:
        '201':
          description: Order created
          headers:
            Location:
              schema: { type: string }
          content:
            application/json:
              schema: { $ref: '#/components/schemas/PlaceOrderV1Response' }
        '400': { $ref: '#/components/responses/Problem' }
        '402': { $ref: '#/components/responses/Problem' }
        '409': { $ref: '#/components/responses/Problem' }

  /orders/{id}:
    get:
      tags: [orders]
      operationId: getOrder
      parameters:
        - { name: id, in: path, required: true, schema: { type: string, format: uuid } }
      responses:
        '200':
          description: Order
          content:
            application/json:
              schema: { $ref: '#/components/schemas/OrderV1Response' }
        '404': { $ref: '#/components/responses/Problem' }

components:
  schemas:
    PlaceOrderV1Request:
      type: object
      required: [customerId, lines]
      properties:
        customerId: { type: string, format: uuid }
        lines:
          type: array
          minItems: 1
          items: { $ref: '#/components/schemas/OrderLineV1Request' }

    OrderLineV1Request:
      type: object
      required: [sku, quantity, unitPrice, currency]
      properties:
        sku:       { type: string, minLength: 1 }
        quantity:  { type: integer, minimum: 1 }
        unitPrice: { type: string, pattern: '^\d+(\.\d+)?$' }
        currency:  { type: string, minLength: 3, maxLength: 3 }

    PlaceOrderV1Response:
      type: object
      required: [orderId]
      properties:
        orderId: { type: string, format: uuid }

    OrderV1Response:
      type: object
      required: [id, customerId, lines, total, currency, status]
      properties:
        id:         { type: string, format: uuid }
        customerId: { type: string, format: uuid }
        lines:
          type: array
          items: { $ref: '#/components/schemas/OrderLineV1Response' }
        total:    { type: string, pattern: '^\d+(\.\d+)?$' }
        currency: { type: string }
        status:   { type: string, enum: [PLACED, PAID, SHIPPED, CANCELLED] }

    OrderLineV1Response:
      type: object
      required: [id, sku, quantity, unitPrice, currency]
      properties:
        id:        { type: string, format: uuid }
        sku:       { type: string }
        quantity:  { type: integer }
        unitPrice: { type: string }
        currency:  { type: string }

    Problem:
      # RFC 7807 — let your generator map this to Spring's ProblemDetail if supported,
      # otherwise a plain POJO is fine. ProblemDetail mapping is orthogonal to contract-first.
      type: object
      properties:
        type:   { type: string, format: uri }
        title:  { type: string }
        status: { type: integer }
        detail: { type: string }

  responses:
    Problem:
      description: Problem
      content:
        application/problem+json:
          schema: { $ref: '#/components/schemas/Problem' }
```

Notes on the contract:
- **Money as string with a numeric pattern**, never `number`. JSON `number` is double-precision float — unusable for financial values. Same decision as `grpc-adapter.md` proto.
- **The pattern `^\d+(\.\d+)?$` only guarantees "non-negative decimal with arbitrary scale"**. It does *not* enforce per-currency scale (e.g., JPY has 0 fraction digits, BHD has 3). That check lives in the domain: `Money`'s constructor rejects `amount.scale() > fractionDigits(currency)`. This is deliberate — scale is a function of currency, so transport validation cannot know it without duplicating the currency table. Negative amounts are also rejected by the pattern, which is correct for line prices and order totals but wouldn't be for a generic `Money` VO (refunds, credits). If you reuse this schema elsewhere, revisit.
- **Status enum is explicit** in the spec. Consumers generate their own enum from it. Never return free-form strings from domain enums without guaranteeing the mapping is stable.
- **Versioning is in the URL** (`/v1/orders`) AND in schema names (`PlaceOrderV1Request`). Both matter: URL for runtime routing, names for coexistence when you introduce `V2` schemas in the same spec before retiring `V1`.
- **A breaking change means a new operation and new schemas, not edits in place.** The generator and consumers both rely on stable schema names.

## Build plugin

Maven example — Gradle equivalent is trivial.

```xml
<!-- pom.xml -->
<plugin>
  <groupId>org.openapitools</groupId>
  <artifactId>openapi-generator-maven-plugin</artifactId>
  <version>${openapi-generator.version}</version>
  <executions>
    <execution>
      <id>order-api-v1</id>
      <goals><goal>generate</goal></goals>
      <configuration>
        <inputSpec>${project.basedir}/src/main/resources/openapi/order-v1.yaml</inputSpec>
        <generatorName>spring</generatorName>
        <apiPackage>com.company.ecom.order.infrastructure.web.generated.v1</apiPackage>
        <modelPackage>com.company.ecom.order.infrastructure.web.generated.v1</modelPackage>
        <output>${project.build.directory}/generated-sources/openapi</output>
        <configOptions>
          <!-- Non-negotiable options. Deviating from these is how contract-first rots. -->
          <interfaceOnly>true</interfaceOnly>
          <skipDefaultInterface>true</skipDefaultInterface>
          <useSpringBoot3>true</useSpringBoot3>
          <useJakartaEe>true</useJakartaEe>
          <useTags>true</useTags>
          <openApiNullable>false</openApiNullable>
          <dateLibrary>java8</dateLibrary>
          <performBeanValidation>true</performBeanValidation>
        </configOptions>
      </configuration>
    </execution>
  </executions>
</plugin>
```

**Why these options matter**:
- `interfaceOnly=true` — you do NOT want a generated `@RestController`. You want an interface with the route/validation annotations, which your controller implements. A generated controller ties you to the generator's DI assumptions and removes your exception-handling seam.
- `skipDefaultInterface=true` — forces you to implement every operation. If the YAML grows a new operation, the build fails until you add a handler. This is the point.
- `useTags=true` — one interface per tag (`orders` → `OrderApi`). Scales better than a single mega-interface when the spec grows.

Generated sources are **not committed**. Codegen runs at `generate-sources`. IDEs pick up the target directory via the Maven build-helper plugin or Gradle's source set auto-detection.

Note the asymmetry with jOOQ, which *does* commit generated classes (see `db-adapter-jooq.md`). The reason: jOOQ codegen requires a live DB with the migrations applied, so committing the output lets teammates build without a database running. OpenAPI codegen is self-contained — YAML in, Java out — and deterministic, so regenerating on every build is cheap. Commit the contract (`order-v1.yaml`), not the derivative.

## Controller (implements the generated interface)

```java
// order/infrastructure/web/OrderController.java
package com.company.ecom.order.infrastructure.web;

import com.company.ecom.order.infrastructure.web.generated.v1.OrderApi;
import com.company.ecom.order.infrastructure.web.generated.v1.OrderV1Response;
import com.company.ecom.order.infrastructure.web.generated.v1.PlaceOrderV1Request;
import com.company.ecom.order.infrastructure.web.generated.v1.PlaceOrderV1Response;
import com.company.ecom.order.application.PlaceOrderService;
import com.company.ecom.order.application.OrderReadService;
import com.company.ecom.order.domain.model.OrderId;
import com.company.ecom.order.infrastructure.web.mapper.*;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.util.UUID;

@RestController
public class OrderController implements OrderApi {

  private final PlaceOrderService placeOrderService;
  private final OrderReadService orderReadService;
  private final PlaceOrderRequestMapper requestMapper;
  private final OrderResponseMapper responseMapper;

  public OrderController(
      PlaceOrderService placeOrderService,
      OrderReadService orderReadService,
      PlaceOrderRequestMapper requestMapper,
      OrderResponseMapper responseMapper) {
    this.placeOrderService = placeOrderService;
    this.orderReadService = orderReadService;
    this.requestMapper = requestMapper;
    this.responseMapper = responseMapper;
  }

  @Override
  public ResponseEntity<PlaceOrderV1Response> placeOrder(PlaceOrderV1Request req) {
    var id = placeOrderService.handle(requestMapper.toCommand(req));
    var body = new PlaceOrderV1Response().orderId(id.value());
    return ResponseEntity.created(URI.create("/v1/orders/" + id.value())).body(body);
  }

  @Override
  public ResponseEntity<OrderV1Response> getOrder(UUID id) {
    var order = orderReadService.findById(new OrderId(id));
    return ResponseEntity.ok(responseMapper.toResponse(order));
  }
}
```

What's worth noticing:
- **No `@RequestMapping`, no `@PostMapping`, no `@Valid` on parameters** — all of that comes from the generated interface, driven by the YAML. The controller looks almost empty, which is the good sign.
- **The controller owns the `Location` header and HTTP status code conventions**. The YAML says `201 Created`; the controller produces the matching `ResponseEntity`. Neither can drift without the contract tests catching it.
- **Bean Validation annotations are on the generated DTOs** (`@NotNull`, `@Size`, `@Pattern` from `performBeanValidation=true`). `@Valid` on the parameter is generated into the interface. You don't repeat validation rules in the YAML *and* in handcrafted DTOs.

## Mappers

One class per direction. Input mapper returns an application command, never a domain type. Output mapper takes a domain `Order` and returns a generated response DTO.

```java
// order/infrastructure/web/mapper/PlaceOrderRequestMapper.java
package com.company.ecom.order.infrastructure.web.mapper;

import com.company.ecom.order.infrastructure.web.generated.v1.PlaceOrderV1Request;
import com.company.ecom.order.application.command.PlaceOrder;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;

@Component
public class PlaceOrderRequestMapper {

  // Rule: generated DTO stops here. No domain types in, application command out.
  // ID generation is the service's job; lines arrive without IDs.
  public PlaceOrder toCommand(PlaceOrderV1Request req) {
    var lines = req.getLines().stream()
        .map(l -> new PlaceOrder.Line(
            l.getSku(),
            l.getQuantity(),
            new BigDecimal(l.getUnitPrice()),
            l.getCurrency()))
        .toList();
    return new PlaceOrder(req.getCustomerId(), lines);
  }
}
```

```java
// order/infrastructure/web/mapper/OrderResponseMapper.java
package com.company.ecom.order.infrastructure.web.mapper;

import com.company.ecom.order.infrastructure.web.generated.v1.OrderLineV1Response;
import com.company.ecom.order.infrastructure.web.generated.v1.OrderV1Response;
import com.company.ecom.order.domain.model.Order;
import org.springframework.stereotype.Component;

@Component
public class OrderResponseMapper {

  public OrderV1Response toResponse(Order order) {
    var lines = order.lines().stream()
        .map(l -> new OrderLineV1Response()
            .id(l.id())
            .sku(l.sku())
            .quantity(l.quantity())
            .unitPrice(l.unitPrice().amount().toPlainString())
            .currency(l.unitPrice().currency().getCurrencyCode()))
        .toList();
    return new OrderV1Response()
        .id(order.id().value())
        .customerId(order.customerId())
        .lines(lines)
        .total(order.total().amount().toPlainString())
        .currency(order.total().currency().getCurrencyCode())
        .status(OrderV1Response.StatusEnum.valueOf(order.status().name()));
  }
}
```

The `StatusEnum.valueOf(order.status().name())` relies on the spec's enum values matching the domain enum names. This is a deliberate coupling documented in the YAML — if the domain adds a status that isn't in the spec, the `valueOf` throws and CI catches it on the first contract test.

## Exception handling

RFC 7807 `ProblemDetail`, same as before. The YAML reserves the status codes; the handler produces the payloads.

```java
// order/infrastructure/web/OrderExceptionHandler.java
package com.company.ecom.order.infrastructure.web;

import com.company.ecom.order.application.exception.ConcurrentAggregateModificationException;
import com.company.ecom.order.application.exception.PaymentDeclinedException;
import com.company.ecom.order.domain.exception.*;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestControllerAdvice(basePackageClasses = OrderController.class)
public class OrderExceptionHandler {

  @ExceptionHandler(EmptyOrderException.class)
  public ProblemDetail onEmpty(EmptyOrderException e) {
    return problem(HttpStatus.BAD_REQUEST, "Invalid order", e.getMessage());
  }

  @ExceptionHandler({OrderAlreadyShippedException.class, InvalidOrderStateException.class})
  public ProblemDetail onConflict(RuntimeException e) {
    return problem(HttpStatus.CONFLICT, "Invalid order state", e.getMessage());
  }

  @ExceptionHandler(PaymentDeclinedException.class)
  public ProblemDetail onDeclined(PaymentDeclinedException e) {
    return problem(HttpStatus.PAYMENT_REQUIRED, "Payment declined", e.getMessage());
  }

  // Optimistic-lock: 409 CONFLICT — state changed under the caller, not malformed.
  @ExceptionHandler(ConcurrentAggregateModificationException.class)
  public ProblemDetail onConcurrentModification(ConcurrentAggregateModificationException e) {
    return problem(HttpStatus.CONFLICT, "Concurrent modification", e.getMessage());
  }

  // Catches invariants surfaced at VO construction (Currency.getInstance, Money scale check,
  // BigDecimal parsing). The spec's Pattern validation catches most of these at the boundary,
  // but not all — e.g. "ZZZ" passes a 3-letter pattern but fails Currency.getInstance.
  @ExceptionHandler(IllegalArgumentException.class)
  public ProblemDetail onIllegalArgument(IllegalArgumentException e) {
    return problem(HttpStatus.BAD_REQUEST, "Invalid request", e.getMessage());
  }

  private static ProblemDetail problem(HttpStatus status, String title, String detail) {
    var p = ProblemDetail.forStatus(status);
    p.setTitle(title);
    p.setDetail(detail);
    return p;
  }
}
```

**Every status code the handler produces must be declared in the YAML** for its operation. A `402 PAYMENT_REQUIRED` that isn't in the spec is a bug: clients can't anticipate it, contract tests don't exercise it, and tooling that generates clients from the spec won't model it. If you add a handler, add the response to the YAML in the same commit.

## Contract conformance testing

Three layers, each catches different things:

1. **Slice tests (`tests-web.md`)** — serialization, validation, and mapping round-trip. Fast, run on every commit.
2. **Spec-vs-implementation validation** — loads the YAML and asserts real handler responses conform to the declared schemas. The compiler already catches missing *operations* because `skipDefaultInterface=true` forces `OrderController` to implement every method on `OrderApi` — drop a `placeOrder` from the interface and the build fails. What the compiler does *not* catch is runtime response drift: an undocumented 4xx status code, a missing required field on a response body, a wrong content type, an enum value not declared in the spec. That's what layer 2 is for. Tools: `swagger-request-validator-mockmvc`, `openapi4j`, or `atlassian/swagger-request-validator`.
3. **Contract conformance in CI** — run Schemathesis or Prism-based fuzzing against a deployed instance. Catches runtime drift that slice-level validation misses, especially around edge cases: fields optional in the spec but required by the handler, unknown enum values returned under specific inputs, undocumented status codes emitted from exception paths.

Example of layer 2:

```java
// OrderApiContractTest.java — part of the web slice
@Test
void real_responses_conform_to_the_spec() {
  var validator = OpenApiInteractionValidator.createForSpecificationUrl(
      "classpath:openapi/order-v1.yaml").build();

  // Hit every operation with a minimal valid body via MockMvc, capture the response,
  // and feed both request and response to the validator. Fails on any schema mismatch.
  // Generator-agnostic — the YAML is the oracle, the handler is the subject.
}
```

Don't skip layer 3 because layer 2 passes. Layer 2 exercises the happy path (and whatever inputs you write); fuzzing explores the input space and surfaces drift you wouldn't have thought to test.

## Evolving the contract

- **Additive changes** (new optional field, new operation, new enum value that consumers can ignore) — bump the YAML, regenerate, implement. No version bump.
- **Breaking changes** (removing a field, tightening a constraint, changing a type) — introduce `v2` schemas and a `/v2/...` path alongside `v1`. Keep `v1` running until consumers are migrated. Schema names (`PlaceOrderV2Request`) prevent accidental cross-version imports.
- **Never edit a shipped schema in place.** Consumers generated clients from it; their build will break silently (new field defaults to null) or loudly (type mismatch). Either way you broke someone else's system.

These rules are the REST counterpart to the Avro/Protobuf `BACKWARD`/`FULL` compatibility checks in `kafka-adapter.md`. The Schema Registry enforces it for Kafka; for REST, your CI enforces it via a spec-diff tool like `openapi-diff` run against the last released YAML.

## Notes

- **Validation is in the YAML** (`minLength`, `minimum`, `pattern`). The generated DTOs carry the matching Bean Validation annotations. Do not re-declare validation on handcrafted classes — there are no handcrafted DTOs.
- **Business validation still lives in the domain.** Transport validation catches shape errors (missing field, wrong type, wrong length). Business validation catches invariant violations (cannot ship a cancelled order). Two different places, two different failure modes.
- **The controller knows nothing about the repository** — only application services.
- **The domain never imports `order.infrastructure.web.generated.v1.*`.** An ArchUnit rule in `tests-architecture.md` makes this non-negotiable.
- **Don't expose the aggregate directly.** Even if `Order` happened to match `OrderV1Response` field-for-field, coupling the wire format to the aggregate means every domain refactor risks a breaking API change. The mapper is cheap insurance.

## Variants

- **Quarkus**: `quarkus-openapi-generator` produces JAX-RS interfaces. Controller becomes `@Path("/orders")` implementing the generated interface. `@RestControllerAdvice` → `@Provider` + `ExceptionMapper`.
- **Micronaut**: `micronaut-openapi` generates either Micronaut HTTP or JAX-RS interfaces. Same implementation pattern.
- **Plain Java / Javalin / other**: the generator options differ, but the layering doesn't. The YAML is still the contract; generated types still stop at the web package.

## A word on code-first

Some teams start code-first with `springdoc-openapi` producing the YAML from `@RestController` annotations. This skill does not endorse that path for external APIs:

- The source of truth becomes annotations scattered across handlers, not a reviewable document.
- Consumers can't generate clients until you deploy.
- Breaking changes aren't detectable without extra tooling (spec-diff against a previous build).

Code-first is acceptable only for internal endpoints (healthchecks, admin, ops) that no external consumer depends on — and even then, `springdoc` as a **safety net** alongside contract-first is better than as a replacement. If your team standard is contract-first, apply it uniformly; mixing makes the boundary fuzzy.