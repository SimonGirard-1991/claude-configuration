---
name: hexagonal-ddd-java
description: Use when scaffolding a new bounded context, adding ports/adapters, defining aggregates/value objects/domain events, or enforcing layer boundaries in a Java backend with real business invariants. Also for multi-BC topology (context map, ACL, Spring Modulith). Skip for CRUD over reference data, health checks, admin tooling, scripts, glue code, or any component where the "domain" is just moving data between layers — a flat `controller → repository` is the correct answer there. For scaffolding templates (code-ready aggregate, use case, adapter examples), see the `hexagonal-module-bootstrap` skill.
---

# Hexagonal Architecture & DDD in Java

This skill encodes the rules for building Java backends using hexagonal architecture (ports & adapters) combined with tactical DDD, scaling from a single bounded context to a multi-BC modular monolith. It is opinionated but framework-agnostic: examples default to Spring Boot + Spring Modulith, with notes for Quarkus, Micronaut, and plain Java.

This skill covers **the rules**. For code-ready scaffolding templates, see the `hexagonal-module-bootstrap` skill. For testing strategy by layer, see `java-testing-strategy`.

## First decide: do you need hexagonal at all?

**This gate is about layering only.** It decides whether a component gets the
hexagon. It does **not** apply to boundary questions — whether two things are one
bounded context or two, and whether a module should become its own service. Those
are answered in `references/multi-bounded-context.md` regardless of how the
component is layered, and the fault-isolation driver in particular exists precisely
to justify extracting a CRUD-shaped module. If that is the question, skip this gate
and open that reference.

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

## Reference map

Open a reference when you need the detailed layer contract or the multi-context
topology. Boundary decisions — is this one bounded context or two, should this
module become its own service — are answered in
`references/multi-bounded-context.md`, not from this file.

| I need to… | Open | Contains |
|---|---|---|
| Know exactly what belongs in `domain/`, `application/`, `infrastructure/` | `references/layer-rules.md` | Per-layer contents and prohibitions, port placement, framework-specific notes (Spring/Quarkus/Micronaut) |
| Identify or split bounded contexts; design integration between them; decide whether to extract a module into its own service | `references/multi-bounded-context.md` | BC identification heuristics, module topology, Context Map patterns, inter-BC communication rules, domain vs integration events, service-extraction drivers including fault isolation |

For code-ready templates (aggregate, use case, adapter, tests), load the
`hexagonal-module-bootstrap` skill instead — this skill explains, that one executes.

## Validation responsibilities

- Adapters validate transport shape: required fields, JSON format, HTTP constraints.
- Application validates use-case preconditions and authorization-relevant checks.
- Domain enforces business invariants.

## Transactions and reads

### Transaction boundaries

A use case normally defines one transaction boundary. Do not keep a database transaction open across remote HTTP calls, broker calls, or slow external I/O. Use a transactional outbox, saga/process manager, or compensating workflow when needed.

### Queries and read models

Queries that do not enforce invariants may use read models or projections directly through application ports. Do not load aggregates only to render list/detail/search screens. Aggregates are for protecting consistency, not for generic data retrieval.

## Testing

Full testing strategy by layer lives in the `java-testing-strategy` skill. The non-negotiable minimum for hexagonal:

- `domain/` tests run without any Spring context and without mocks — pure JUnit + AssertJ, inject `Clock.fixed()` for determinism.
- Architecture boundaries are enforced by automated tests (Spring Modulith `ApplicationModules.verify()` or ArchUnit), not by documentation.

If a domain test needs a mock, the test is probably at the wrong layer.

## Review checklist

Before approving a change, verify:

**Layering**
- [ ] No framework annotation or infra import in `domain/`.
- [ ] No ambient time or randomness in `domain/` — `System.currentTimeMillis()`, `LocalDate.now()`, `new Random()` and static singletons are out; inject a `Clock` (or the value) so invariants stay testable with `Clock.fixed()`.
- [ ] No logging framework in `domain/` — domain code does not log. Emit a domain event or let the application layer log the outcome.
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

## Anti-patterns to refuse — multi-BC

These are refusals, not preferences.

- **"Extract Customer to shared"** when each BC has a different view of Customer → create `billing.domain.Customer` and `shipping.domain.Customer`, distinct, with only the identifier in common (possibly in `shared`).
- **Cyclic dependencies between BCs** → the boundary is wrong, not the rule. Redraw the map (often by extracting a third BC, or by flipping a direction via events).
- **Consuming an external/legacy system without an ACL** → the foreign model will bleed into your domain within weeks.
- **One database schema for all BCs** → eventually someone joins across BCs "just this once" and the boundary is gone.
- **"Let's just put it in shared for now"** → `shared` has no brakes. Every addition needs explicit justification, or the modular monolith degrades into a big ball of mud with extra annotations.

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
