# Secrets management and audit logging

Reference for the `java-security-baseline` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

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
