---
name: hexagonal-module-bootstrap
description: Use when scaffolding a new module, bounded context, aggregate, use case, port, adapter, or test suite in a Java backend following hexagonal + DDD. Provides code-ready templates (Spring Boot + jOOQ by default, with Quarkus/Micronaut variants). Covers aggregates, use cases, REST/Kafka/gRPC adapters, jOOQ repositories, anti-corruption layers, and per-layer tests. For the *rules* (when/why/where things go), see the hexagonal-ddd-java skill — this skill executes, that one explains. Skip for CRUD over reference data; flat controller+repository is correct there.
---

# Hexagonal Module Bootstrap

Code-ready templates for scaffolding hexagonal + DDD modules in Java. Pair with `hexagonal-ddd-java` for the rules.

**Example domain**: e-commerce `Order`. Replace names when adapting.

**Default stack**: Java 21, Spring Boot 3+, jOOQ, PostgreSQL, Kafka. Variants for Quarkus, Micronaut, and plain Java are called out where they differ.

## How to use this skill

1. Decide what you need to create.
2. Open the matching reference file from the map below.
3. Copy, rename, adapt. Keep the structure; change the names and the specifics.
4. Remove any pedagogical `// Rule:` comments once the layout is clear.

## Reference map

| I want to create… | Open | Contains |
|---|---|---|
| Aggregate + value objects + domain events | `references/aggregate.md` | `Order`, `OrderId`, `Money`, `OrderLine`, events, invariant exceptions |
| Application service / use case | `references/use-case.md` | `PlaceOrderService`, `PlaceOrder` command, outbound ports |
| REST adapter | `references/rest-adapter.md` | Contract-first: OpenAPI YAML + generated interfaces, controller, mappers |
| Kafka adapter (producer + consumer) | `references/kafka-adapter.md` | Integration-event publisher, idempotent consumer skeleton |
| gRPC adapter | `references/grpc-adapter.md` | Service impl mapping proto ↔ domain |
| jOOQ repository (default) | `references/db-adapter-jooq.md` | Repository impl, record ↔ aggregate mapper |
| JPA repository (alternative) | `references/db-adapter-jpa.md` | When JPA's trade-offs are assumed; entity ≠ aggregate |
| Anti-corruption layer | `references/acl.md` | External client + translator, keeps foreign model out of domain |
| Module declaration | `references/module-declaration.md` | `package-info.java` for Spring Modulith, multi-BC variants |
| Domain tests | `references/tests-domain.md` | Pure JUnit, no Spring, `Clock.fixed()` |
| Application tests | `references/tests-application.md` | Fakes over mocks, port contracts |
| Web slice tests | `references/tests-web.md` | `@WebMvcTest` + mapper tests |
| DB integration tests | `references/tests-db.md` | Testcontainers Postgres + jOOQ |
| Architecture tests | `references/tests-architecture.md` | Modulith `verify()` + ArchUnit rules |

## Recommended scaffolding order

Build inward-out. This keeps the domain pure and surfaces port-design questions before framework decisions lock them in.

1. **Domain**: aggregate, value objects, domain events, exceptions. Write domain tests alongside.
2. **Application**: command, outbound ports (interfaces only), application service. Write application tests with fakes.
3. **Infrastructure — driven adapters**: jOOQ repository, ACL for external systems, Kafka producer. Write integration tests with Testcontainers.
4. **Infrastructure — driving adapters**: REST controller, Kafka consumer, gRPC service. Write slice tests.
5. **Module declaration + architecture test**: `package-info.java` with allowed dependencies, Modulith `verify()`.

## Adapting templates — non-negotiables

- **Rename everything**. Don't ship `Order` in your codebase unless your domain actually has orders.
- **Prune aggressively**. A template shows what's possible; your aggregate should only contain what you need. Fewer fields, fewer methods, fewer invariants = better.
- **Pick the right framework variant** for the target project. Default is Spring Boot 3+.
- **jOOQ is the default persistence** in these templates. JPA is a valid alternative when its trade-offs are understood — see `db-adapter-jpa.md` for the criteria.
- **Never copy the `// Rule:` comments into production code**. They are pedagogical anchors pointing to rules in `hexagonal-ddd-java`; delete once you've internalized them.
- **Contract-first for all external APIs**. REST uses OpenAPI YAML; Kafka integration events use Avro/Protobuf + Schema Registry; gRPC uses `.proto` natively. Generated types are infrastructure — never import from `application/` or `domain/`. Code-first REST is not the default.

## Framework detection

Detect the target framework before picking variants:

- `spring-boot-starter-*` in `pom.xml` / `build.gradle` → Spring Boot (default templates).
- `io.quarkus:*` → Quarkus variant in each reference.
- `io.micronaut:*` → Micronaut variant.
- None of the above → plain Java; wire everything in a composition root (`Application.main`).

Layering, naming, and package structure are identical across all four. Only annotations and DI wiring differ.

## These templates are architecture-ready, not production-ready

The snippets in this skill show **structure**, not finished production code. Before shipping anything derived from them, add (at minimum):

- Imports (deliberately abbreviated in examples for readability).
- Observability: logging, metrics, tracing spans at adapter boundaries.
- Security: authn/authz on driving adapters (REST, gRPC, Kafka consumer groups).
- Idempotency keys and processed-message tracking for at-least-once delivery.
- Resilience: timeouts, retries, circuit breakers around external calls.
- Error payloads that match your API standard (`ProblemDetail`, gRPC `Status` details, etc.).
- Transaction semantics appropriate to your platform (see the outbox note in `use-case.md`).

Treat each reference file as a starting diagram with some code attached — not a finished feature.

## Scope boundaries

This skill deliberately does **not** include scaffolding for: event sourcing, CQRS read models, transactional outbox implementations, snapshot stores. Those are separate architectural choices on top of hexagonal + DDD — they belong in their own skill when you need them. Where integration events or outbox-shaped ports appear in these templates, they are **named placeholders** that make room for a real implementation — not the implementation itself.
