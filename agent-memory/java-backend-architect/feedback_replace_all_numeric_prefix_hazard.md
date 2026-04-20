---
name: replace_all numeric prefix hazard
description: Avoid Edit replace_all on numeric JSON/YAML values that may be a prefix of a larger value elsewhere in the file
type: feedback
---

Never use `Edit` with `replace_all: true` on a numeric token (e.g., `"y": 4`, `port: 80`) when a larger value sharing that prefix may exist elsewhere in the file. `replace_all` is a substring replace, not a token replace — `"y": 4` matches the `"y": 4` inside `"y": 42` and turns it into `"y": 52`.

**Why:** this bit me when shifting Grafana dashboard panel y-coordinates by +1. I ran `replace_all` for `"y": 4` → `"y": 5`, which corrupted every `"y": 42` → `"y": 52`. Recovery required a second pass to fix the collateral damage.

**How to apply:**
- Before any numeric `replace_all`, grep the file for values that share the prefix of your target (`"y": 4` → check for `"y": 4[0-9]`).
- If any exist, switch to contextual `Edit` calls using surrounding lines (e.g., `"h": 4,\n"w": 6,\n"x": 0,\n"y": 0`) as the discriminator.
- For JSON/YAML grids where you are shifting a range of numeric values, do the shifts in descending order (`51 → 52`, `50 → 51`, …, `4 → 5`) so later edits cannot retroactively collide with earlier ones.
- The same hazard applies to anything with numeric tails: `port: 80` vs `port: 8080`, `timeout: 5` vs `timeout: 500`, `id: 1` vs `id: 10`.
