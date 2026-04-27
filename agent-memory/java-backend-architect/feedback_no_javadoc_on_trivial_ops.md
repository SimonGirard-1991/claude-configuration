---
name: No javadoc on trivial operations
description: Skip javadoc on self-describing methods (getById, findByX, simple CRUD repo methods) — method name + exception type already tell the story
type: feedback
---

Don't write javadoc (or block comments) on trivial operations where the method name and signature already carry the meaning. Examples: `getById(id)` on a repository that throws a self-describing exception, `findByX` returning Optional, single-statement CRUD methods.

**Why:** User finds javadoc on trivial ops to be noise — it reads as padding rather than explanation, dilutes the comments that *do* carry real information (non-obvious invariants, trade-off rationale, pointers to incidents). Explicitly called out after I added multi-line javadoc to a newly-introduced `getById` method.

**How to apply:**
- **Skip javadoc when:** method name + parameter names + return type + thrown exception name already describe what happens. `User getById(String id) throws UserAccountMissingException` needs nothing more.
- **Keep javadoc when:** there's a non-obvious invariant, a deliberate deviation from an expected pattern (e.g. "upsert by X using ON CONFLICT so concurrent first-inserts don't race"), a rationale for a design choice that would otherwise look wrong, or a cross-reference another developer needs to find.
- **Rule of thumb:** if the comment only restates what the signature says in English, delete it. If removing it would cause a reviewer to ask "why?", keep it.
- Applies to inline `//` comments too — prefer expressive code over commentary that narrates the obvious.
