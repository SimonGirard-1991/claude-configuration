---
name: java-security-baseline
description: >-
  Use when designing, implementing, or reviewing security-sensitive code paths in a
  Java backend — input validation at boundaries, parameterized queries, authN/authZ at
  the edges, secrets management, dependency scanning, audit logging for sensitive
  operations, and OWASP Top 10 review discipline. The headline rule is defense in
  depth: assume any single layer can fail, and bake security in from day one rather
  than bolt it on. Pairs naturally with `/security-review`. Skip for throwaway
  scripts, spikes, or non-Java code.
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

## Reference map

Open a reference when you need the implementation detail for a specific control.

| I need to… | Open | Contains |
|---|---|---|
| Validate input at a boundary, or encode output safely | `references/input-and-output.md` | Bean Validation on DTOs, domain invariants, rejecting unsafe content, parameterized SQL, HTML/JSON encoding, log injection, security headers |
| Add or review authN/authZ, or scope permissions | `references/authn-authz.md` | AuthN at the edges, authZ placement (controller vs use case), IDOR and tenant-scoping bugs, least privilege for DB users / IAM / K8s RBAC |
| Handle secrets, or write an audit trail | `references/secrets-and-audit.md` | Vault and short-lived credentials, rotation, log hygiene, audit-event schema and retention for regulated contexts |
| Vet dependencies, or handle deserialization | `references/dependencies-and-deserialization.md` | Dependency-Check/Snyk in CI, pinning, SBOM, signed artifacts; Java serialization, Jackson default typing, XXE |

## OWASP Top 10 — the review lens

Know them. Recognize them in code. The list is periodically refreshed — check the current edition before quoting specific entries; the categories shift. The ones that have been durable across editions:

- **Broken access control** — missing or incomplete authorization checks. Most common root cause of real breaches.
- **Cryptographic failures** — weak algorithms, unauthenticated encryption, predictable IVs, homegrown crypto, secrets in plaintext.
- **Injection** — SQL, NoSQL, OS command, LDAP, JNDI, template injection. Parameterize; never concatenate.
- **Insecure design** — architectural gaps (no rate limiting, no threat modeling, no secure defaults) that code-level fixes cannot patch.
- **Security misconfiguration** — default credentials, overly verbose errors, missing security headers, open S3 buckets, debug endpoints in prod.
- **Vulnerable and outdated components** — transitive dependencies with CVEs. Controls and the known-bad list are in `references/dependencies-and-deserialization.md`.
- **Identification and authentication failures** — credential stuffing, session fixation, missing MFA, weak password rules.
- **Software and data integrity failures** — unsigned artifacts, CI pipelines without build provenance, unsafe deserialization.
- **Security logging and monitoring failures** — no audit log, no alerting on anomalies, no way to detect the breach you already have.
- **Server-side request forgery (SSRF)** — URL-from-input passed to an HTTP client. Allowlist destinations; block RFC1918, link-local, and metadata IPs.

**In review, for any security-relevant PR**: walk the list. Not all apply; the ones that do must have an answer.

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
