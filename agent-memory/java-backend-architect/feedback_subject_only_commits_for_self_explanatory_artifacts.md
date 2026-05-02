---
name: Subject-only commits for self-explanatory artifacts
description: When the artifact in the diff explains itself (ADR, runbook, README, well-named refactor), commit with subject only — no body. Don't duplicate what the diff already says.
type: feedback
---

For commits where the artifact in the diff *is* the explanation, write a subject-only commit message — no body. Adding a body that recapitulates what the artifact already says produces:

- Duplication that drifts independently of the artifact (commit body says X, ADR later changes to Y, body becomes wrong).
- Reading-cost noise for anyone walking `git log`.
- A misleading impression that the body is load-bearing when it isn't.

**Why:** User rejected a long, well-structured commit body for ADR-008 on Wealthpay. They wrote: "No body in this commit, just the name. body is too much and not interesting. the adr already explains." The ADR was 265 lines documenting threshold methodology, calibration log, decisions, and rationale; the commit body summarized those same points. The diff *was* the explanation.

**How to apply:**

Default to subject-only when the diff carries its own explanation. Examples:

- ADRs, runbooks, design docs, READMEs — the document itself explains the decision.
- Generated artifacts (OpenAPI specs, jOOQ regens) — the generator command in the title is enough.
- Trivial refactors with self-evident intent ("rename FooBar to FooBaz", "extract toDiscordEmbed").
- Mechanical changes (formatting, dependency bumps).

Add a body only when it carries information *not* derivable from the diff:

- Non-obvious "why this fix" rationale where the code shows "what changed" but not "why".
- Cross-cutting context (referenced incident, follow-up commits, deferred work).
- Verification evidence that lives nowhere else (e.g. fire-drill output, calibration numbers that don't make it into a doc).
- Behavioral nuance the reader needs to know but the diff doesn't show (e.g. "this requires a manual data migration").

The honest test: "Does the body add something a reader couldn't get from `git show`?" If no → drop it.

When in doubt with a doc commit, default to subject-only. The user prefers terse to redundant.
