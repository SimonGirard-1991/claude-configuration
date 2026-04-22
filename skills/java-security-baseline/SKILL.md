---
name: java-security-baseline
description: Use when designing, implementing, or reviewing security-sensitive code paths in a Java backend — input validation at boundaries, parameterized queries, authN/authZ at the edges, secrets management, dependency scanning, audit logging for sensitive operations, and OWASP Top 10 review discipline. The headline rule is defense in depth: assume any single layer can fail, and bake security in from day one rather than bolt it on. Pairs naturally with `/security-review`. Skip for throwaway scripts, spikes, or non-Java code.
---

# Java Security Baseline

This skill encodes the non-negotiable security bar for a Java backend. The defining failure mode it prevents: a team ships a service that "works," passes functional tests, and then discovers in a pen-test, a production incident, or a regulator's audit that authorization was assumed rather than enforced, secrets were in env vars committed to Git, a vulnerable transitive dependency was left unscanned, or an injection sink was reachable from an unauthenticated endpoint. Every rule in this skill is the kind of thing where "we'll get to it later" is how breaches happen.

Defaults assume Spring Boot + Spring Security + jOOQ + Bean Validation + a current LTS JVM. Quarkus and Micronaut ship equivalent primitives; the principles are framework-agnostic, exact wiring differs.

## When to use

- Designing a new service, module, or bounded context that will run in production — especially in regulated contexts (banking, fintech, health, anything holding PII).
- Adding a new inbound entry point (HTTP controller, Kafka consumer, GraphQL resolver, scheduled job with external triggers).
- Adding any code path that touches money movement, permission changes, data export, or PII.
- Reviewing a PR for security gaps (missing `@Valid`, leaked secrets, broad authorization, unsanitized HTML output, unsafe deserialization, unscoped SQL).
- Pairing with `/security-review` on a branch or PR — this skill is the baseline checklist; the slash command is the execution.
- Post-incident: any breach, near-miss, or auditor finding. Map the finding back to the rule that would have caught it.

## When NOT to use

- Throwaway spikes, prototypes, or one-shot scripts that never touch production data.
- Non-Java code (principles transfer; tools do not).
- Pure infrastructure tasks (WAF config, network ACLs, K8s policies) — those belong in a platform/security-engineering domain, not this skill.

## Core principles

1. **Defense in depth.** Assume any single layer can fail. Validation at the edge does not excuse parameterized queries in the repository. AuthN at the gateway does not excuse authZ checks in the service. A compromised dependency does not excuse lax secrets hygiene. Controls stack; redundancy is the point.
2. **Security is a feature, not a follow-up.** Baked in from day one costs a fraction of what retrofitted costs, and retrofitted controls miss edge cases that were never designed for. "We'll add auth later" is how services ship without auth.
3. **Never trust input. Never.** This includes input from other internal services in a zero-trust model. The threat model is not "malicious external attacker" alone — it is also "compromised peer service," "confused deputy," and "malformed event from a schema-drift regression."
4. **Least privilege, everywhere.** DB users, service accounts, IAM roles, feature flags, admin endpoints — every identity gets the minimum permissions to do its job, and no more. The blast radius of a compromise is bounded by the permissions held by the compromised identity.
5. **Fail closed, not open.** When an authorization check cannot be performed (e.g., policy service down), deny the request. When a validation rule cannot run, reject the input. Open-failure modes are how "availability" becomes "bypass."
6. **Auditability is a security control.** If you cannot prove who did what, when, from where, and whether it succeeded, you cannot investigate a breach and you cannot satisfy regulators. Audit logging is separate from technical logging — see the `java-observability` skill for the split.
7. **OWASP Top 10 is the floor, not the ceiling.** Every developer reviewing security-relevant code should be able to name the current OWASP Top 10 categories and recognize each one in code. It is the common vocabulary; memorize it.

## Input validation

**Validate at every boundary. Reject early.** The boundary is any point where data enters the application from a source outside its trust zone — HTTP controllers, message consumers, webhook handlers, file uploads, admin CLIs, scheduled-job parameters.

### Bean Validation (`jakarta.validation`) on DTOs

Controllers and consumer payloads should be DTOs with Bean Validation annotations, validated with `@Valid`. This is the first line of defense and the cheapest.

```java
public record CreateAccountRequest(
    @NotBlank @Size(max = 120) String ownerName,
    @Email @Size(max = 255) String email,
    @NotNull @Positive @DecimalMax("1000000.00") BigDecimal openingBalance,
    @NotNull Currency currency
) {}

@PostMapping("/accounts")
public AccountResponse create(@Valid @RequestBody CreateAccountRequest req) { ... }
```

**Non-negotiables**:

- **Every string has a max length.** Unbounded strings are a DoS vector (memory, DB column overflow, log flooding) and an injection-payload amplifier. `@Size(max = N)` on every `String` field.
- **Every number has bounds.** `@Min`, `@Max`, `@Positive`, `@DecimalMax`. An integer overflow in a balance field is a real bug.
- **Every collection has a max size.** `@Size(max = N)` on lists. "Submit 10 million items in one request" is someone's DoS.
- **Nested objects get validated too.** `@Valid` on nested fields, or validation stops at the outer shell.
- **`@Validated` on service methods** for parameters that bypass the controller (internal calls, Kafka consumers calling use cases directly).

### Domain-level invariants are not optional

Bean Validation is a filter, not a replacement for domain invariants. A `Money` value object that rejects negative amounts in its constructor is what actually protects the system. A DTO validator that is removed in a refactor is the weakest link — the domain invariant survives.

**Where each validation lives**:

- **Syntactic shape** (length, regex, numeric bounds, required fields) → Bean Validation on DTOs.
- **Business invariants** (balance ≥ 0, account is active, transfer amount ≤ daily limit) → domain model / aggregate, enforced in the constructor or the behavior method.
- **Cross-entity consistency** (source and target accounts belong to the same customer) → use case / application service, with the domain enforcing its own half.

See `hexagonal-ddd-java` for the full layering rules.

### Rejecting unsafe content

- **HTML / Markdown / rich text**: run through an allowlist sanitizer (OWASP Java HTML Sanitizer) before storage. Never store raw HTML from an untrusted source.
- **File uploads**: validate content type by sniffing magic bytes, not by trusting `Content-Type` or filename extension. Enforce max file size at the framework level (`spring.servlet.multipart.max-file-size`) *and* at the reverse proxy.
- **XML**: disable external entity resolution (XXE). `XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES = false`, `SUPPORT_DTD = false`. Prefer JSON where you have the choice.
- **YAML**: use SnakeYAML's `SafeConstructor` or a `LoaderOptions` with `setAllowDuplicateKeys(false)` — unsafe YAML has historically been an RCE vector.
- **Regex from untrusted input**: catastrophic backtracking (ReDoS) is a real DoS vector. Use a timeout-bounded matcher or reject patterns before compiling.

## Output encoding and parameterized queries

### SQL — parameterize, always

- **jOOQ**: parameterization is the default. `dsl.selectFrom(USERS).where(USERS.EMAIL.eq(email))` binds the parameter. **Never** use `DSL.inline(userInput)` on untrusted data — that is string concatenation with a nicer name.
- **Plain JDBC**: `PreparedStatement` with `?` placeholders. Never `Statement.executeQuery("SELECT ... WHERE id = " + id)`. Ever.
- **Spring Data JPA / Spring JDBC**: `@Query` with named parameters. Never use SpEL to interpolate user input into a JPQL/SQL string.
- **Dynamic queries**: build them with the query builder (jOOQ DSL, Criteria API), not with string concatenation. If you must concatenate (e.g., dynamic `ORDER BY` column name), validate against an allowlist of known column names first.

**Review red flag**: any `+` operator between SQL text and a variable. Any `String.format` building SQL. Any `"WHERE " + column + " = ?"` where `column` came from input without an allowlist check.

### HTML / JSON output

- **HTML templates** (Thymeleaf, JTE, Mustache): default to context-aware escaping. Verify your template engine escapes by default in the expression syntax you are using (e.g., Thymeleaf's `th:text` escapes, `th:utext` does not). Flag every `utext` / raw output in review.
- **JSON**: Jackson's default behavior is safe. Do not write JSON with string concatenation. Do not enable `ObjectMapper.enableDefaultTyping()` on data from untrusted sources — it has been an RCE vector repeatedly.
- **Response headers**: set `Content-Type` explicitly. Content sniffing combined with a permissive type has been an XSS vector.

### Logging and error messages

- **Never log raw user input as a format string.** `log.info(userInput)` is a log-forging / format-string bug. Use `log.info("request from {}", userInput)` — parameterized.
- **Error responses** should not leak stack traces, internal paths, SQL, or framework internals to external callers. Spring Boot's default error handler does; override it in production profiles.
- **Never include raw input in error messages** echoed to the caller when the input could contain HTML/JS (reflected XSS) or control characters (log forging downstream).

### Security headers

For any HTTP service, set these at the framework or gateway layer:

- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HTTPS only)
- `Content-Security-Policy` — restrictive, deny by default
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY` (or CSP `frame-ancestors`)
- `Referrer-Policy: strict-origin-when-cross-origin`
- Remove `Server` / `X-Powered-By` disclosures.

Spring Security adds most of these by default; verify they are enabled in the deployed profile.

## Authentication and authorization

### AuthN at the edges

- **Every inbound entry point is authenticated or explicitly anonymous.** There is no middle ground. Spring Security's default is secure — `authorizeHttpRequests(auth -> auth.anyRequest().authenticated())`. Any `permitAll()` is a conscious decision that gets reviewed, not a default.
- **JWT validation**: validate signature (algorithm allowlist — refuse `none`), issuer, audience, expiration, and `nbf`. Use a library with a battle-tested JWT validator (Spring Security, Nimbus JOSE+JWT). Never roll your own.
- **mTLS for service-to-service** in a zero-trust network. TLS termination at the edge does not imply peers are trustworthy inside the mesh.
- **API keys**: hash them at rest (like passwords), rotate on a schedule, bind to a scope and rate limit.

### AuthZ — not an afterthought

Authorization happens **inside** the use case, not only at the controller. A controller-only check is a single point of failure — the next endpoint that forgets the annotation bypasses authorization entirely. Defense in depth:

- **Controller-level coarse gates**: `@PreAuthorize("hasRole('ADMIN')")`, method-security annotations. These are the outer shell.
- **Use-case-level fine-grained checks**: "the caller owns this account," "the caller has scope `accounts:write`," "the caller's tenant matches the resource's tenant." These use the domain model and cannot be skipped by adding a new controller.
- **Resource-level filtering**: list queries filter by tenant/owner at the repository layer. A query that returns all rows and filters in application code is one bug away from IDOR. `WHERE tenant_id = :caller_tenant` is in the SQL.

**Model the authorization decision explicitly**:

- **Role-based (RBAC)** when the set of permissions is small and role assignments are stable.
- **Attribute-based (ABAC)** when decisions depend on resource attributes (owner, tenant, sensitivity label) or environmental factors (time, IP range).
- **Policy-as-code** (OPA, Cedar) when authorization rules are complex enough that embedding them in code makes them unreviewable by non-developers (compliance, legal).

### Common authorization bugs

- **IDOR** (Insecure Direct Object Reference): `/accounts/{id}` with no ownership check. The caller passes any ID; the system returns the row. Test explicitly — "user A cannot read user B's account."
- **Missing authorization on write paths**. Read paths get scrutiny; update/delete endpoints sometimes ship with only authentication.
- **Privilege escalation via mass assignment**. Request DTO has a `role` field; the controller binds it into the entity; user promotes themselves to admin. Separate inbound DTOs from domain entities; whitelist fields explicitly.
- **Confused deputy**: service A calls service B with A's credentials, not the end user's. B checks "is A allowed?" and grants a permission the end user does not have. Propagate the caller identity (JWT, signed headers) and re-check at B.

## Secrets management

- **Never in source code. Never in env vars committed to Git.** `git-secrets`, `gitleaks`, or equivalent pre-commit and CI scanning is mandatory.
- **Secret stores**: Vault, AWS Secrets Manager, GCP Secret Manager, Kubernetes Secrets (with encryption-at-rest enabled and RBAC). The app pulls at startup or on-demand with short-lived credentials.
- **Rotation**: every credential rotates on a schedule. If a credential cannot be rotated without a code change, that is the bug to fix first.
- **Short-lived credentials** beat long-lived ones. IAM role assumption (STS), Vault dynamic secrets, workload identity in K8s — a credential that expires in an hour has a bounded blast radius.
- **Encryption at rest** for sensitive data columns (KMS-backed envelope encryption). The threat model includes "DB backup leaks"; encrypted columns survive the leak.
- **Encryption in transit** for every hop. TLS 1.2+ with a modern cipher suite. No plaintext Kafka, no plaintext JDBC.
- **Log hygiene**: never log secrets, JWTs, full card numbers, full SSNs. Structured logging with PII-masking filters — see the `java-observability` skill for the pattern.

**Review red flags**:

- A string literal that looks like an API key, AWS access key, or private key block in source.
- `System.getenv("DATABASE_PASSWORD")` read from an env var that a `values.yaml` in Git sets.
- A `@Value("${some.secret}")` where the property has a default value in `application.yml`.
- Debug logging that prints a full request including `Authorization` headers.

## Audit logging

Audit logs are **separate from technical logs** and answer a different question: not "what did the system do?" but "who did what, to what, when, from where, and was it allowed?" They are retained longer, subject to tamper-evidence requirements, and often read by auditors and incident responders, not by SREs.

**Emit an audit event for any sensitive operation**:

- Money movement (transfers, payments, refunds, holds).
- Permission changes (role grants, role revocations, API key creation/rotation/revocation).
- Data access at scale (bulk exports, reports over PII).
- Authentication events (login success, login failure, MFA challenge, password reset).
- Admin actions (impersonation, feature-flag flip, config change).

**Required fields per event**:

- `actor_id` (the authenticated principal — not the technical service account if a human is behind it)
- `actor_ip` and `user_agent`
- `action` (enum — `ACCOUNT_CREATED`, `TRANSFER_INITIATED`, ...)
- `resource_type` + `resource_id`
- `outcome` (`SUCCESS` / `DENIED` / `FAILED`) and reason on non-success
- `timestamp` (UTC, ISO-8601 with millisecond precision)
- `correlation_id` / `trace_id` (link to technical logs)
- Before/after state for modifications, where applicable

**Storage**:

- Separate sink from technical logs (dedicated table, dedicated log index, or a managed audit service).
- Append-only. No `UPDATE` or `DELETE`. If it happened, it stays in the log.
- Retention aligned with regulatory requirements (often 7+ years in finance).
- Access-controlled — reading the audit log is itself an audited action.

See `java-observability` for the technical-log-vs-audit-log split and correlation IDs.

## OWASP Top 10 — the review lens

Know them. Recognize them in code. The list is periodically refreshed — check the current edition before quoting specific entries; the categories shift. The ones that have been durable across editions:

- **Broken access control** — missing or incomplete authorization checks. Most common root cause of real breaches.
- **Cryptographic failures** — weak algorithms, unauthenticated encryption, predictable IVs, homegrown crypto, secrets in plaintext.
- **Injection** — SQL, NoSQL, OS command, LDAP, JNDI, template injection. Parameterize; never concatenate.
- **Insecure design** — architectural gaps (no rate limiting, no threat modeling, no secure defaults) that code-level fixes cannot patch.
- **Security misconfiguration** — default credentials, overly verbose errors, missing security headers, open S3 buckets, debug endpoints in prod.
- **Vulnerable and outdated components** — transitive dependencies with CVEs. See dependency hygiene below.
- **Identification and authentication failures** — credential stuffing, session fixation, missing MFA, weak password rules.
- **Software and data integrity failures** — unsigned artifacts, CI pipelines without build provenance, unsafe deserialization.
- **Security logging and monitoring failures** — no audit log, no alerting on anomalies, no way to detect the breach you already have.
- **Server-side request forgery (SSRF)** — URL-from-input passed to an HTTP client. Allowlist destinations; block RFC1918, link-local, and metadata IPs.

**In review, for any security-relevant PR**: walk the list. Not all apply; the ones that do must have an answer.

## Dependency hygiene

- **OWASP Dependency-Check or Snyk in CI.** The build fails on new `CRITICAL` / `HIGH` CVEs in direct or transitive dependencies. A PR that introduces a vulnerable dependency gets blocked; a nightly scan flags newly-disclosed CVEs in existing dependencies.
- **Renovate or Dependabot** for automated dependency PRs. Small frequent updates are safer than rare giant ones.
- **Pin to versions, not ranges.** `implementation("org.example:lib:1.2.3")`, not `1.2.+`. Reproducible builds matter.
- **Lockfile in VCS**: `gradle.lockfile` / `pom.xml` with explicit versions of transitives. A new CVE in a transitive you did not know you had is worse than one in a direct dependency.
- **SBOM** (CycloneDX, SPDX) published per release. When a CVE drops, "which of our services has this?" is answered in minutes, not hours.
- **Signed artifacts**: publish and verify with Sigstore / GPG. Supply-chain attacks are no longer hypothetical.
- **Scope the classpath**: runtime dependencies are not compile-time dependencies. `runtimeOnly`, `testImplementation`, `compileOnly` — the smaller the production classpath, the smaller the attack surface.

**Known-bad patterns to refuse**:

- `log4j-core < 2.17.1` (Log4Shell).
- `jackson-databind` with default typing enabled on untrusted input.
- `commons-collections 3.x` with `InvokerTransformer` reachable on a deserialization path.
- Unmaintained libraries with open CVEs and no fix. Replace, do not patch around.

## Least privilege

- **Database users**: the application connects as a user with `SELECT`/`INSERT`/`UPDATE`/`DELETE` on its own schema only. No `DROP`, no `GRANT`, no cross-schema access. Migrations run as a separate, more-privileged user that the application does not have credentials for at runtime.
- **Read-only connections** for read-heavy paths. If the code path has no business issuing writes, it should be on a read-only connection pool that physically cannot write. Defense in depth against ORM misuse and SQL injection.
- **Service accounts / IAM roles**: each service has its own identity, its own scoped permissions. No shared service accounts. No "god" role used "because it's easier."
- **K8s RBAC**: the service's `ServiceAccount` has only the permissions it needs. No `cluster-admin`. Network policies restrict which services can talk to which.
- **Admin endpoints**: separate port, separate auth, separate network. Actuator exposed on the same port as business APIs is a breach waiting to happen.
- **Feature flags and kill switches**: granular enough that the blast radius of a compromised admin account is bounded.

## Unsafe deserialization

Deserializing untrusted bytes into objects has been an RCE vector for a decade. Rules:

- **Never `ObjectInputStream.readObject` on untrusted input.** Java serialization is unsafe by design.
- **Never enable default typing on a Jackson `ObjectMapper` that processes untrusted JSON.** `enableDefaultTyping()` / `activateDefaultTyping()` are RCE vectors.
- **Never use XMLDecoder, XStream without a typed allowlist, or any deserializer that reconstructs arbitrary types from a type hint in the payload.**
- **Prefer data-only formats**: plain JSON with explicit target types, Protobuf, Avro. These do not reconstruct arbitrary classes.

## Review checklist

When reviewing a PR that touches any of: controllers, consumers, authZ, data access, cryptography, dependencies, secrets, or error handling — check:

- [ ] **Every inbound DTO has `@Valid` on its usage and Bean Validation annotations on its fields** (length, bounds, required).
- [ ] **Domain invariants are enforced in constructors / factory methods**, not only at the edge.
- [ ] **No string concatenation building SQL.** Parameterized queries everywhere. Dynamic column/table names allowlist-checked.
- [ ] **No raw user input in `log.X(userInput)` as format string.** Parameterized logging.
- [ ] **Authentication required by default.** Any `permitAll()` is deliberate and reviewed.
- [ ] **Authorization enforced in the use case**, not only by a controller annotation. Resource ownership / tenant scoping checked in code or pushed into repository filters.
- [ ] **List queries filter by tenant / owner in SQL**, not in application code.
- [ ] **JWT validation uses a library with algorithm allowlisting.** No `none`, no unverified claims.
- [ ] **No secrets in source code, env defaults, or application.yml.** Secret manager or K8s secret reference only.
- [ ] **Audit event emitted for sensitive operations** (money movement, permission changes, admin actions, bulk exports).
- [ ] **Security headers set** on HTTP responses. Error responses do not leak stack traces to external callers.
- [ ] **No Jackson default typing on untrusted input. No Java serialization on untrusted input. No XXE in XML parsers.**
- [ ] **New dependencies checked for known CVEs.** Versions pinned, not ranged.
- [ ] **Least privilege**: new DB users / IAM roles / K8s permissions scoped tightly. No reach for existing god-mode accounts.
- [ ] **Cryptography uses a vetted library**, not a homegrown implementation. Algorithms, key sizes, and modes match current industry guidance (e.g., AES-GCM with 256-bit keys, Argon2id for password hashing).

## Anti-patterns to refuse

- **"Authorization happens at the gateway, we don't need it in the service."** One missed rule in gateway config and the service is open. Enforce in the service too.
- **A controller that takes a domain entity as `@RequestBody`.** Mass-assignment bug waiting to happen. Use an explicit inbound DTO, whitelist fields.
- **`@PreAuthorize("hasRole('USER')")`** as the only authorization check on an endpoint that returns a specific user's data. Any authenticated user can read any user's data — classic IDOR.
- **`String sql = "SELECT * FROM " + tableName;`** with `tableName` from input. Even "validated to be alphanumeric" is a red flag; allowlist against known tables.
- **`ObjectMapper().enableDefaultTyping()`** or equivalent "polymorphic deserialization from payload type hints" on untrusted JSON.
- **Debug / actuator endpoints exposed on the same port as the business API**, or exposed at all without authentication in production.
- **A new library added because "it has a feature we want," without a CVE check** or without considering its transitive dependency graph.
- **A secret value in `application.yml`** with a comment "TODO replace in prod." It will not be replaced in prod.
- **Error responses that include stack traces** or SQL or framework internals. Information disclosure is a precursor to exploitation.
- **"We'll add rate limiting later."** Credential stuffing, brute force, and enumeration attacks arrive before "later" does. Rate limiting is a day-one feature on auth endpoints and write paths.
- **Catch-all `catch (Exception e)` that returns 200 OK.** Hides failures, masks attacks, defeats monitoring.
- **Rolling your own crypto, JWT validator, password hasher, or session manager.** Use vetted libraries. Always.

## Cross-references

- **Layering rules (where validation, authZ, audit logging live in the hexagon)**: `hexagonal-ddd-java`.
- **Technical-log vs business-audit-log split, correlation IDs, PII-masking filters, log retention**: `java-observability`.
- **Testing authorization rules (per-role controller tests, IDOR regression tests, repository tests with tenant filtering)**: `java-testing-strategy`.
- **Idempotency, retries, and DLQs — security-adjacent reliability concerns (replayed events, duplicate actions)**: `java-reliability-messaging`.
- **Scaffolding for a secure controller + use case + repository slice**: `hexagonal-module-bootstrap`.
- **Running a focused security pass on a branch or PR**: the `/security-review` slash command — this skill is its checklist.
