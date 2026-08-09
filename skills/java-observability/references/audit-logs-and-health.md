# Technical vs audit logs, health and readiness

Reference for the `java-observability` skill. `SKILL.md` holds that skill's rules and
the reference map that routes here; this file holds the detail for one part
of it.

---

## Technical logs vs business audit logs

In any regulated context — banking, healthcare, anywhere with compliance obligations — separate two log streams:

| Aspect | Technical logs | Business audit logs |
|---|---|---|
| Purpose | Debugging, performance, operational signal | Who did what, when, to what, under what authorization |
| Volume | High, bursty | Low, steady |
| Retention | Short (days to weeks) | Long (years, per regulation) |
| Mutability | Rotated, overwritten, sampled | Append-only, tamper-evident, immutable |
| Storage | Log aggregator (Loki, ELK, Datadog) | Dedicated audit store (often a regulated DB or WORM storage) |
| Owner | Engineering / SRE | Compliance / Legal / Security |

**Do not merge them.** An audit log in the same index as technical logs will be rotated out the first time retention is reconsidered. Emit audit events through a dedicated channel — a domain event, a write to an `audit_log` table, or an outbound message to a compliance topic. The write must be in the same transaction as the action being audited (see the Transactional Outbox pattern in the reliability skill).

Even outside regulated contexts, consider separating audit events for any **money movement, permission change, or data export**. These are the events future-you will wish existed when something goes wrong.

## Health checks and readiness

- **Liveness** answers "is the process alive?" — keep it cheap and dependency-free. A failing liveness probe should mean "kill and restart me." Do not fail liveness on a dependency outage; that produces crash loops.
- **Readiness** answers "should traffic route to me?" — it may check critical dependencies (DB, broker) but avoid deep chains. A readiness probe that fans out to five downstreams will flap.
- Spring Boot Actuator ships `/actuator/health` with liveness/readiness groups — use them; don't roll your own.
- **Never expose `management.endpoint.health.show-details=always` on an internet-facing listener.** Detailed health responses leak component status (DB vendor/version, broker reachability, disk paths) — useful for internal scrapes, reconnaissance gold for anything public. Bind the management port to a separate, internal-only interface. `java-security-baseline` refuses actuator on the business API port outright, so port separation is the binding requirement and `show-details=when-authorized` is a second layer on top of it — **not** an alternative you can trade against it.
