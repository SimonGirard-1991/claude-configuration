---
name: Prefer clean migration history over compensating migrations
description: User prefers consolidating migrations and cleaning DB state directly rather than stacking fix-on-fix migrations
type: feedback
---

When a migration is wrong or needs rework, prefer cleaning up to a single correct migration rather than adding compensating migrations on top.

**Why:** A V15 migration was broken, then a V16 was created to fix V15's mess. The user wanted the V16 deleted and V15 to be the single source of truth, with the DB state cleaned up directly (DELETE from flyway_schema_history, drop stale objects). Stacking compensating migrations pollutes the history and makes intent harder to follow.

**How to apply:**
- If a migration hasn't been committed/shared yet, fix it in place + clean the local DB
- If it has been shared, a compensating migration is acceptable — but flag the cleanup option first
- Always present the "clean history" path as the preferred option when the blast radius is limited (local dev, feature branch not yet merged)
