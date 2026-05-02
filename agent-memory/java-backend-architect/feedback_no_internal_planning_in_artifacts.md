---
name: No internal-planning references in operational artifacts
description: Dashboards, alerts, logs, and runtime-facing docs must be self-contained for the operator — never reference development-plan steps, ticket IDs, or sprint context.
type: feedback
---

Operational artifacts (Grafana dashboard descriptions, alert annotations, log messages, exception messages, runtime-facing javadoc) must read as if the original author has rotated out and an unrelated oncall is reading them at 03:00. They must NOT contain references to internal project planning — phrases like "Step 7 alerts on this", "TICKET-1234 covers this", "see the migration plan", "as agreed in the Q3 design review".

**Why:** the audience for these artifacts is the operator under stress, not the developer who built the feature. Internal-planning references are noise to that audience and reduce the trust the operator places in the artifact ("if this is full of jargon I don't understand, what else is wrong with it?"). User feedback was direct: a reference to "Step 7" in a Grafana panel description is weird because Step 7 is meaningful only to the project manager and developer during feature development — not later, and not at runtime.

**How to apply:**
- Dashboard panel descriptions: describe what the metric measures, what a healthy value looks like, what an unhealthy value indicates, and what the operator should do. No build-process context.
- Alert annotations: describe the symptom, the hypothesis, and the next investigation step.
- Log messages and exception messages: include the business context (account ID, transaction ID, current state) — not the JIRA ticket that introduced the line.
- Runtime-facing javadoc (on aspects, controllers, scheduled jobs): describe the contract and operational properties, not how the class came to be.
- Acceptable to reference framework concepts (`@Transactional`, `JoinPointMatch`, `OptimisticLockingFailureException`) — those are stable, audience-known vocabulary.
- It is fine to keep build-process context in commit messages, ADRs, PR descriptions, and code comments that aren't Javadoc — those have a different audience.

If unsure: imagine the artifact is being read three years from now by someone who has never met you. Strip anything that won't make sense to them.
