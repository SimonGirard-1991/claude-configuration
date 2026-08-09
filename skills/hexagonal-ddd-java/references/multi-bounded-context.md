# Multi bounded context — topology, context maps, integration

Reference for the `hexagonal-ddd-java` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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

Moved to the **Anti-patterns to refuse — multi-BC** section of this
skill's `SKILL.md`, so the refusal list sits with the rest of the
decision spine. Read it there before approving a boundary change.

## Modular Monolith is the default; microservices are an escalation

Default to a modular monolith (Spring Modulith or ArchUnit-enforced boundaries). Extract a module into a separate service **only** with a concrete driver:

- **Differential scaling** (10–100× divergence from the rest).
- **Fault isolation** (e.g., payments must not be taken down by notifications).
- **Independent team velocity at scale** (multiple teams contending in the same repo).
- **Heterogeneous technical constraints** (genuinely needs Python/Go/Rust).
- **Regulatory isolation** (physical separation required).

"We might need it later" is not a driver. Clean module boundaries keep later extraction cheap. Premature microservices produce distributed monoliths — the worst of both worlds.
