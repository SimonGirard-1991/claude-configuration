---
name: Flyway repair only updates checksums — never re-executes migrations
description: Critical reminder that modifying an already-applied Flyway migration and running repair does NOT re-execute it — must act on DB directly
type: feedback
---

Never modify an already-applied Flyway migration assuming `flyway repair` will re-execute it. Repair only updates the checksum in `flyway_schema_history` — the SQL does **not** run again.

**Why:** This caused cascading failures in a CDC pipeline debugging session. A migration was modified and repaired, but the old (destructive) version had already executed. The new version never ran, leaving the database in an inconsistent state. Multiple band-aid migrations were created to compensate, compounding the mess. The user explicitly warned about this before I made the mistake.

**How to apply:** When a migration has already been applied and its effect needs to change:
1. Create a **new** migration with the corrective SQL, OR
2. Run the corrective SQL **directly on the database** and then repair the checksum, OR
3. Delete the flyway_schema_history row and the stale DB objects, then let the corrected migration re-run fresh.
Never assume repair = re-execution. Always ask: "has this migration already run on the target database?"
