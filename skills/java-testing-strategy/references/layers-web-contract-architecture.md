# Web slice, contract and architecture tests

Reference for the `java-testing-strategy` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Controller / web slice tests — `@WebMvcTest`, never full context

> **Templates:** `hexagonal-module-bootstrap/references/tests-web.md`. This section owns the *strategy* (slice over full context, what status codes to cover). The reference owns the *code* (MockMvc setup, mapper test patterns).

**What lives here:** HTTP semantics — status codes, content types, request/response payload shape, validation behavior, error response format, security configuration at the edge.

**Tools:** `@WebMvcTest` (Spring MVC) or `@WebFluxTest` (WebFlux). MockMvc / WebTestClient. Mockito for the application service layer.

**Rules:**
- **`@WebMvcTest(YourController.class)` only — never `@SpringBootTest` for a controller test.** Loading the full context for a controller test is the single most common cause of slow Spring test suites.
- **Mock the application service.** This is one of the few places mocking is unambiguously correct: the controller's job is HTTP↔command translation, and the application service is its only outbound dependency.
- **Test status codes for every documented response.** 200, 201, 400 (validation), 404, 409 (conflict), 422 (business rule violation), 500 (unexpected). If your controller can return it, test it.
- **Test validation behavior.** Bean Validation errors should produce a structured error response — assert on the shape, not just the status.
- **Test the security configuration here, not in unit tests.** `@WithMockUser`, `@WithAnonymousUser` — verify that protected endpoints reject unauthenticated requests.
- **Don't test the application service's logic here.** That is what use-case tests are for. The controller test asserts that valid input produces a call to the use case and that the use case's result becomes the right HTTP response.
- **Quarkus/Micronaut equivalents:** `@QuarkusTest` with `RestAssured`, or Micronaut's `@MicronautTest` with `HttpClient`. Same principle: load only what you need.

## Contract tests — Pact or Spring Cloud Contract at boundaries

**What lives here:** verification that producer and consumer agree on the wire format, used at any service boundary that crosses a team or release cycle.

**Tools:** Pact (consumer-driven) or Spring Cloud Contract (producer-driven).

**Rules:**
- **Mandatory at any inter-team service boundary.** Skip it within a single team that releases together; mandate it the moment a contract crosses a team line.
- **Consumer-driven by default.** Pact's model — consumer writes the contract, publishes to a broker, producer verifies — is the right shape for most cases.
- **Producer-driven (SCC) for "open host" services** with many consumers and a stable, versioned contract.
- **Run producer-side verification in CI.** A contract that isn't verified on every producer build is decoration.
- **Cover both REST and async.** Pact supports message contracts; use it for Kafka topics that cross team boundaries.
- **Don't replace contract tests with E2E tests.** E2E tests are slow, fragile, and don't isolate which side broke. Contract tests pinpoint the diff between producer and consumer.

## Architecture tests — non-negotiable on any non-trivial project

> **Templates:** `hexagonal-module-bootstrap/references/tests-architecture.md`. This section owns the *strategy* (what rules to enforce, ArchUnit vs. Modulith). The reference owns the *code* (concrete `noClasses().that()...` rules, `Modules.verify()` setup).

**What lives here:** structural rules — layering boundaries, package dependencies, naming conventions, framework-annotation placement.

**Tools:** ArchUnit (any Java project), or Spring Modulith's `ApplicationModules.verify()` (Spring Boot only).

**Rules:**
- **At least one architecture test must exist** on any project past the prototype stage. Otherwise hexagonal/DDD/modular boundaries silently rot.
- **Enforce dependency direction:** `domain → ∅`, `application → domain`, `infrastructure → application + domain`. Never the reverse.
- **Enforce framework-annotation placement:** no `@Service`/`@Entity`/`@Autowired`/`@Transactional` in `domain/`.
- **Enforce inter-BC rules** (multi-BC only): no BC imports another BC's `domain/` or `infrastructure/` — only its `api/`.
- **Run on every build.** These tests are fast; there is no excuse to skip them.
- **Modulith over ArchUnit when on Spring Boot;** ArchUnit elsewhere. Modulith's defaults align with the BC-as-module convention.

For code templates: `hexagonal-module-bootstrap/references/tests-architecture.md`.
