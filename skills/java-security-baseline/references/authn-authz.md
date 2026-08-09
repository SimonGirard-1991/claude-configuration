# Authentication, authorization and least privilege

Reference for the `java-security-baseline` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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

## Least privilege

- **Database users**: the application connects as a user with `SELECT`/`INSERT`/`UPDATE`/`DELETE` on its own schema only. No `DROP`, no `GRANT`, no cross-schema access. Migrations run as a separate, more-privileged user that the application does not have credentials for at runtime.
- **Read-only connections** for read-heavy paths. If the code path has no business issuing writes, it should be on a read-only connection pool that physically cannot write. Defense in depth against ORM misuse and SQL injection.
- **Service accounts / IAM roles**: each service has its own identity, its own scoped permissions. No shared service accounts. No "god" role used "because it's easier."
- **K8s RBAC**: the service's `ServiceAccount` has only the permissions it needs. No `cluster-admin`. Network policies restrict which services can talk to which.
- **Admin endpoints**: separate port, separate auth, separate network. Actuator exposed on the same port as business APIs is a breach waiting to happen.
- **Feature flags and kill switches**: granular enough that the blast radius of a compromised admin account is bounded.
