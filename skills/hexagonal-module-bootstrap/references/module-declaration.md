# Module Declaration

For Spring Modulith projects, each bounded context is declared via `package-info.java` at the BC root.

---

## Single BC (no other modules)

```java
// com/company/ecom/order/package-info.java
@ApplicationModule(
    type = ApplicationModule.Type.CLOSED,
    allowedDependencies = {"shared"})
package com.company.ecom.order;

import org.springframework.modulith.ApplicationModule;
```

## Multi-BC setup

Each BC declares what it depends on. Use `::api` to reference only the public package of another BC.

```java
// com/company/ecom/order/package-info.java
@ApplicationModule(
    type = ApplicationModule.Type.CLOSED,
    allowedDependencies = {"shared", "billing::api", "catalog::api"})
package com.company.ecom.order;
```

```java
// com/company/ecom/billing/package-info.java
@ApplicationModule(
    type = ApplicationModule.Type.CLOSED,
    allowedDependencies = {"shared"})
package com.company.ecom.billing;
```

```java
// com/company/ecom/shared/package-info.java
@ApplicationModule(type = ApplicationModule.Type.OPEN)
package com.company.ecom.shared;
```

### Exposing a public API package

Inside a BC, only `api/` is importable by others:

```
com/company/ecom/billing/
├── domain/         internal — NOT importable by other BCs
├── application/    internal
├── infrastructure/ internal
└── api/            public — command/query DTOs, event schemas
    ├── package-info.java          (marked @NamedInterface("api"))
    └── BillingFacade.java         optional: a coarse-grained entry point
```

```java
// com/company/ecom/billing/api/package-info.java
@NamedInterface("api")
package com.company.ecom.billing.api;

import org.springframework.modulith.NamedInterface;
```

## Enforcement

Architecture tests are non-optional. See `tests-architecture.md`. Without them, `package-info.java` is documentation — it does not enforce anything at runtime or compile time.

## Variants without Spring Modulith

- **Quarkus / Micronaut / plain Java**: no equivalent annotation. Enforce module boundaries with **ArchUnit** (see `tests-architecture.md`) or a multi-module Gradle/Maven build where each BC is a separate module with explicit dependencies.
- **Maven multi-module**: one Maven module per BC. The POM's `<dependencies>` section becomes the enforceable context map. Heavier, but the most unambiguous form.

## Notes

- `shared` is **OPEN** — everyone imports it — but keep it minimal (see `hexagonal-ddd-java`). Every addition is contagion.
- A BC that needs to depend on another BC's internals is a sign the boundary is wrong. Redraw the map, or add to the upstream's `api/`.
- Resist circular dependencies at the module level. Modulith will fail `verify()`. When it does, that's the *correct* outcome — fix the design, not the rule.
