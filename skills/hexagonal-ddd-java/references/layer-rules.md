# Single bounded context — layer-by-layer rules

Reference for the `hexagonal-ddd-java` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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
