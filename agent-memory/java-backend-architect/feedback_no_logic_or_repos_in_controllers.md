---
name: No business logic or repositories in controllers
description: Controllers must never call repositories or hold business logic — even in CRUD apps with anemic domains. Application/use-case layer is the floor, not optional.
type: feedback
---

Controllers must contain only HTTP plumbing: parse request → call one use case / application service → map result to DTO → set status/headers/cookies. They must not:

- Inject or call repositories directly.
- Hold business logic, orchestration, or `@Transactional` boundaries.
- Make authorization decisions beyond what Spring Security annotations cover at the edge.

Business logic belongs in (in order of preference): an **aggregate method** if the domain is rich enough, otherwise a **use case / application service**. Even when the domain is anemic (CRUD-shaped, like a tic-tac-toe scaffold), the application service layer is still mandatory — that's where transactions, idempotency, cross-repo orchestration, and observability hooks live.

**Why:** User explicitly flagged this as a non-negotiable that shouldn't have needed to be in the agent prompt. They consider it foundational layering. In a prior review I labeled controllers-calling-repositories a "mild architectural smell" and got pushed back on hard — that softening is the mistake to avoid.

**Don't conflate two separate questions:**
1. *Does this domain warrant a full hexagon with ports/adapters?* — Often no for CRUD; can be over-engineering.
2. *Should controllers ever touch repositories?* — Always no, regardless of domain richness.

I previously let the "no" to (1) excuse the violation in (2). They are independent.

**How to apply:**
- When reviewing: check controllers first. Any repository injection or `@Transactional` on a controller method = lead the review with this, not bury it under "mild smells."
- When generating/scaffolding: even the thinnest CRUD endpoint gets a `*UseCase` / `*Service` between controller and repository. Controllers stay HTTP-only.
- When the user shows AI-generated code that wires controllers straight to repositories: name it as the primary defect, not a stylistic note.
