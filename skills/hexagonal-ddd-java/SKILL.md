---
name: hexagonal-ddd-java
description: Use when scaffolding a new bounded context, adding ports/adapters, defining aggregates/value objects/domain events, or enforcing layer boundaries in a Java backend with real business invariants. Also for multi-BC topology (context map, ACL, Spring Modulith). Skip for CRUD over reference data, health checks, admin tooling, scripts, glue code, or any component where the "domain" is just moving data between layers — a flat `controller → repository` is the correct answer there. For scaffolding templates (code-ready aggregate, use case, adapter examples), see the `hexagonal-module-bootstrap` skill.
---

# Hexagonal Architecture & DDD in Java

This skill encodes the rules for building Java backends using hexagonal architecture (ports & adapters) combined with tactical DDD, scaling from a single bounded context to a multi-BC modular monolith. It is opinionated but framework-agnostic: examples default to Spring Boot + Spring Modulith, with notes for Quarkus, Micronaut, and plain Java.

This skill covers **the rules**. For code-ready scaffolding templates, see the `hexagonal-module-bootstrap` skill. For testing strategy by layer, see `java-testing-strategy`.

## First decide: do you need hexagonal at all?

Before applying anything else in this skill, check:

- Does this component enforce business invariants that must survive framework/DB changes? → **yes**: use hexagonal.
- Is it CRUD over reference data, a health check, admin tooling, or a static lookup? → **no**: use flat `controller → repository`. Close this skill.
- Is the "domain" really just moving data between layers with no rules to protect? → **no**: flat design. Empty aggregates and single-implementation ports are worse than no hexagon at all.

If you scaffold a `GetCountriesUseCase` with a `CountriesPort` for a static reference table, you have misapplied this skill. Stop and write a flat controller instead.

The goal of hexagonal architecture is to **protect a domain**. When there is no domain to protect, the ceremony is pure cost.

## When to use

- Designing a new module, bounded context, or backend service with non-trivial business rules.
- Adding a new port (interface) or adapter (implementation) in an existing hexagonal codebase.
- Defining a new aggregate, value object, domain event, or domain service.
- Introducing a second bounded context, or extracting one from an existing monolith.
- Reviewing imports, package layout, or dependency direction.
- Writing architecture tests that enforce module/BC boundaries.

## When NOT to use

- Pure CRUD with no invariants — hexagonal adds cost without payoff.
- Scripts, one-shot jobs, glue code.
- Technical libraries (SDK clients, shared utilities) — they have no domain.
- Prototypes where the model is still being discovered through throwaway code.

If unsure, ask: *does this code enforce business rules that should survive framework or database changes?* If no, skip hexagonal.

## Core principle: dependency direction

Dependencies point inward: `infrastructure → application → domain`. **The domain depends on nothing.** Never the reverse. This is non-negotiable — if you feel pressure to break it, the model is wrong.

- `infrastructure/` imports from `application/` and `domain/`.
- `application/` imports from `domain/` only.
- `domain/` imports no application, infrastructure, framework, persistence, messaging, or transport code. It may use the JDK and carefully selected framework-free libraries.

## Single bounded context — layer rules

### `domain/` — pure business

Contains:
- **Aggregates** — consistency boundary, one root per transaction. Aggregates enforce invariants that belong to their consistency boundary. Cross-aggregate policies are coordinated by application services or domain services through ports. Do not put aggregate-local invariants in application services.
- **Value Objects** — immutable, equality by value (`Money`, `Email`, `AccountId`). Prefer `record` in modern Java.
- **Entities** — identity-based, mutable inside their aggregate.
- **Domain Events** — past-tense facts (`FundsCredited`, `OrderShipped`). Sealed interface + records is idiomatic.
- **Domain Services** — stateless operations that don't naturally belong to an aggregate (e.g., a pricing calculation spanning multiple aggregates). Do not overuse — most logic belongs in the aggregate.
- **Exceptions** — invariant violations (`InsufficientFunds`, `OrderAlreadyShipped`).

Forbidden in `domain/`:
- `@Service`, `@Component`, `@Autowired`, `@Entity`, `@Transactional`, or any framework annotation.
- `jakarta.persistence.*`, `org.springframework.*`, JDBC, Jackson, HTTP types.
- Static singletons, global state, `System.currentTimeMillis()` (inject a `Clock`).
- Logging frameworks — domain code doesn't log, it returns results.

Rule of thumb: the `domain/` package must compile with only the JDK + a handful of pure Java libs (e.g., a validation lib, a money lib). If you need to add a framework dep to make it compile, you've leaked infrastructure into the model.

### `application/` — use cases, ports, and commands

Contains:
- **Application Services / Use Cases** — one class per use case, or grouped by aggregate. Orchestrates: load aggregate → invoke domain method → persist → publish. This layer owns the *transaction*.
- **Commands** — intent records (`OpenAccount`, `ShipOrder`) arriving from the outside. Live in `application/`, not `domain/`. Rationale: a command represents intent from an external caller (a controller, a message listener), which is an application-layer concern. Keeping them out of `domain/` preserves the domain as the pure invariant-enforcement layer.
- **Ports** — interfaces the application needs from the outside world. Names are domain-oriented, not technology-oriented: `AccountRepository`, not `AccountJpaRepository`; `PaymentGateway`, not `StripeClient`.
- **DTOs for use case input/output** — optional. Some teams expose commands directly; others wrap them. Either works, but pick one convention per codebase.

Ports come in two shapes:
- **Driving ports** (inbound) — what the application offers to the outside (`AccountApplicationService` is itself a driving port, or you extract an interface for it).
- **Driven ports** (outbound) — `AccountRepository`, `EmailSender`, `PaymentGateway`. Use `java.time.Clock` directly when time is needed; do not wrap it in a custom port unless there is a concrete reason.

### `infrastructure/` — adapters

Contains:
- **Driving adapters** — REST controllers, message listeners, CLI handlers, GraphQL resolvers. They translate external requests into commands and call the application layer.
- **Driven adapters** — repositories (JPA, jOOQ, Mongo), HTTP clients to external APIs, message producers, email senders. Each implements a port defined in `application/`.
- **Mappers** — explicit classes for DTO↔domain conversion. One class per direction is the clearest convention (`AccountRequestMapper`, `AccountResponseMapper`). Avoid bidirectional mappers — they hide coupling.
- **Config** — Spring `@Configuration`, Quarkus producers, Micronaut factories live here, not in the domain.

Rule: an adapter can import from `application/` (to see the port it implements) and `domain/` (to construct/consume domain types). It must never be imported *from* `application/` or `domain/`.

### Framework-specific notes

- **Spring Boot**: `@Service` on application services, `@Repository` on infra adapters, `@RestController` on web adapters, `@ConfigurationProperties` for config. Use constructor injection only.
- **Quarkus**: `@ApplicationScoped` for services and adapters. Avoid `@Inject` field injection.
- **Micronaut**: `@Singleton` on application services and adapters.
- **Plain Java**: wire dependencies manually in a `main()` or composition root. The `domain/` and `application/` packages stay identical — only `infrastructure/` changes shape.

The layering rules are the same across frameworks. Only the annotations differ.

## Validation responsibilities

- Adapters validate transport shape: required fields, JSON format, HTTP constraints.
- Application validates use-case preconditions and authorization-relevant checks.
- Domain enforces business invariants.

## Transactions and reads

### Transaction boundaries

A use case normally defines one transaction boundary. Do not keep a database transaction open across remote HTTP calls, broker calls, or slow external I/O. Use a transactional outbox, saga/process manager, or compensating workflow when needed.

### Queries and read models

Queries that do not enforce invariants may use read models or projections directly through application ports. Do not load aggregates only to render list/detail/search screens. Aggregates are for protecting consistency, not for generic data retrieval.

## Multi bounded context

Single-BC rules scale up to multi-BC by treating each BC as a self-contained hexagon with its own `domain`/`application`/`infrastructure`, plus explicit rules for *how BCs talk to each other*.

### Identifying a bounded context

A BC is delimited by a *coherent ubiquitous language*. You are probably crossing a BC boundary when:
- The same word means different things (`Customer` in Billing is a payment profile; in Shipping it's an address + preferences).
- The invariants change (an Order in Sales cares about pricing; in Fulfillment it cares about pickability).
- The stakeholders change (Billing talks to Finance; Catalog talks to Merchandising).
- Different release cadences, different teams, or different compliance scopes.

If two "things" share a name but diverge on any of the above, they are *different concepts* in different BCs, not one shared concept.

### Module topology

One BC = one top-level package = one module. In Spring Modulith:

```
com.company.app
├── billing/                 @ApplicationModule(type = CLOSED, allowedDependencies = {"shared"})
│   ├── domain/
│   ├── application/
│   ├── infrastructure/
│   └── api/                 explicitly public — the only package other BCs may import
├── shipping/                @ApplicationModule(type = CLOSED, allowedDependencies = {"shared", "billing::api"})
│   └── ... (full hexagon)
├── catalog/                 @ApplicationModule(type = CLOSED)
│   └── ... (full hexagon)
└── shared/                  @ApplicationModule(type = OPEN)
    └── (minimal: Clock, Json config, Ids, cross-cutting tech only — NEVER domain concepts)
```

Without Spring Modulith, enforce the same rules with ArchUnit:
```java
noClasses().that().resideInAPackage("..billing.domain..")
    .should().dependOnClassesThat().resideInAnyPackage("..shipping..", "..catalog..");
```

### Context Map — which pattern, when

| Pattern | Use when | Concrete Java shape |
|---|---|---|
| **Shared Kernel** | Concept is *truly* universal and changes rarely (`Money`, `Clock`, tenant `UserId`) | A `shared` module, deliberately minimal. Defend its minimalism — every addition is contagion. |
| **Customer / Supplier** | Downstream BC depends on a cooperative upstream | Upstream exposes an `api/` package; downstream imports only that |
| **Conformist** | Downstream consumes an upstream it cannot influence | Same as above, downstream accepts upstream's model as-is |
| **Anti-Corruption Layer (ACL)** | Upstream's model would pollute downstream | `infrastructure/acl/` package: client + translator → local domain types |
| **Open Host Service + Published Language** | Multiple consumers, stable contract needed | Versioned API (OpenAPI for sync, Avro/JSON Schema for async events) |
| **Separate Ways** | Two BCs have no real reason to integrate | No dependency. This is a *valid* choice — resist the urge to integrate. |

### Inter-BC communication rules

**Synchronous**:
- Call the upstream BC *only* through its `api/` package (or equivalent public facade).
- Never import from another BC's `domain/` or `infrastructure/`.
- The API package exposes DTOs or command/query types, never aggregates.

**Asynchronous**:
- The source BC raises domain events internally and maps publishable facts to integration events.
- Other BCs consume integration events, not the source BC's internal domain events.
- The target BC translates external events into its own commands through an ACL. The target never treats the source's event as a native domain event.
- Event schemas are a *published language* — version them, evolve them additively.
- Use a transactional outbox when event publication must be consistent with state changes.
- Message handlers must be idempotent. Store processed message IDs or use natural idempotency keys when handling integration events.

**Database**:
- Each BC owns its tables. At minimum, separate Postgres schemas per BC; ideally separate databases.
- Never share entities, never join across BCs at the database level. If you need data from another BC, go through its API or consume its events into your own read model.

**Shared code**:
- `shared` module is for *technical* cross-cutting only: `Clock`, JSON config, ID generation strategy, exception base classes.
- It is *never* for domain concepts. If two BCs both have `Customer`, they are two different `Customer` classes in two different packages. This feels wasteful; it is not.

### Domain events vs integration events

- Domain events are internal facts raised inside one bounded context.
- Integration events are versioned contracts published to other bounded contexts or external systems.
- Map domain events to integration events in application/infrastructure.
- Do not expose aggregate classes or internal domain events as public inter-BC contracts.

### Anti-patterns to refuse

- **"Extract Customer to shared"** when each BC has a different view of Customer → create `billing.domain.Customer` and `shipping.domain.Customer`, distinct, with only the identifier in common (possibly in `shared`).
- **Cyclic dependencies between BCs** → the boundary is wrong, not the rule. Redraw the map (often by extracting a third BC, or by flipping a direction via events).
- **Consuming an external/legacy system without an ACL** → the foreign model will bleed into your domain within weeks.
- **One database schema for all BCs** → eventually someone joins across BCs "just this once" and the boundary is gone.
- **"Let's just put it in shared for now"** → `shared` has no brakes. Every addition needs explicit justification, or the modular monolith degrades into a big ball of mud with extra annotations.

## Testing

Full testing strategy by layer lives in the `java-testing-strategy` skill. The non-negotiable minimum for hexagonal:

- `domain/` tests run without any Spring context and without mocks — pure JUnit + AssertJ, inject `Clock.fixed()` for determinism.
- Architecture boundaries are enforced by automated tests (Spring Modulith `ApplicationModules.verify()` or ArchUnit), not by documentation.

If a domain test needs a mock, the test is probably at the wrong layer.

## Review checklist

Before approving a change, verify:

**Layering**
- [ ] No framework annotation or infra import in `domain/`.
- [ ] Every port is an interface in `application/`, implemented in `infrastructure/`.
- [ ] Mappers DTO↔domain are explicit and one-directional.
- [ ] No `@Transactional` in `domain/`; transactions live in `application/`.
- [ ] Commands live in `application/`, not `domain/`.

**Domain modeling**
- [ ] Aggregate-local invariants are enforced by aggregate methods, not only by application services.
- [ ] Cross-aggregate policies are explicit in application/domain services and backed by ports or consistency mechanisms.
- [ ] Value objects are immutable and validate in their constructor.
- [ ] Domain events are past tense and carry enough data to be understood in isolation.

**Multi-BC** (if applicable)
- [ ] Each BC has a `package-info.java` (or equivalent) with explicit allowed dependencies.
- [ ] No import from another BC's `domain/` or `infrastructure/`.
- [ ] Shared concepts in `shared` are justified as truly universal, not just homonymous.
- [ ] External systems are fronted by an ACL.
- [ ] Architecture test (`Modules.verify()` / ArchUnit) passes.

**Tests**
- [ ] Domain tests run without Spring.
- [ ] Architecture rules are enforced by an automated test.

## Common mistakes and how to push back

| Request | Response |
|---|---|
| "Add `@Entity` to the aggregate, it's faster" | No — map between JPA entities (in `infrastructure/db`) and the aggregate (in `domain/`). The speed gain is illusory; the coupling is permanent. |
| "Expose the aggregate in the REST response" | No — map to a response DTO. Exposing the aggregate locks your API to your model. |
| "Inject the repository into the aggregate" | No — the aggregate is loaded by the application service and passed to its methods, or its methods return events the service persists. |
| "Put the command in `domain/`, it's about the domain" | No — commands represent external intent. They live in `application/`. `domain/` stays pure invariant enforcement. |
| "Put this cross-BC helper in `shared`" | Only if it's technical (Clock, Ids). If it's domain, it belongs in a BC or in neither. |
| "Two BCs both need `Customer`, let's share it" | Not automatically. Ask: do they have the same invariants, lifecycle, and language? Usually no — keep them separate. |
| "Let me just call the other BC's repository directly" | No — call its public API or consume its events. Direct repository access across BCs erases the boundary. |
| "We don't need hexagonal for this, it's just CRUD" | Probably right — check the criteria at the top of this skill. If it's truly CRUD with no invariants, use flat `controller → repository` instead. |

## Minimal package skeleton

```
com.company.app.<bc>
├── domain
│   ├── model          aggregates, value objects, entities
│   ├── event          domain events (sealed interface + records)
│   └── exception      invariant violations
├── application
│   ├── <UseCase>Service.java
│   ├── command        command records (intent from outside)
│   └── port           outbound port interfaces (or spread across package)
├── infrastructure
│   ├── web            REST / GraphQL / etc.
│   ├── db             repository implementations + mappers
│   ├── messaging      producers / consumers
│   └── acl            anti-corruption layers for external systems
├── api                (multi-BC only) public types for other BCs
└── package-info.java  module declaration + allowed dependencies
```

Keep it boring. The value is in the *rules*, not in novel package names.