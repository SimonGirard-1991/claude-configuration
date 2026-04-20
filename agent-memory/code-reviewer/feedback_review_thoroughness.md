---
name: Review thoroughness — symmetric analysis and cold-start checks
description: User called out two missed issues in review — TOCTOU race on create side (only flagged drop side) and alert false-positive on fresh deploy (had the facts but didn't follow through)
type: feedback
---

When flagging a concurrency issue on one code path, always check the symmetric/adjacent code paths for the same class of bug. Don't stop at the first instance.

When reviewing alerting expressions that reference gauge metrics, always ask: "what is the initial value, and does the alert expression handle cold-start / fresh deploy correctly?"

**Why:** User pointed out that an external tool ("codex") caught both a TOCTOU race on partition creation (symmetric to the DROP race I did flag) and a false-positive alert on fresh deploy (gauge starts at 0, making `time() - 0` huge). I had the facts for both but didn't follow through.

**How to apply:** After finding any concurrency or state-initialization issue, do a second pass on all related code for the same pattern class. For alerts, always evaluate the expression with initial/zero/absent values.
