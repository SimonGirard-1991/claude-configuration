---
name: React effects on transition commits — shared-ref staleness
description: When two effects share a dep, the trigger effect's synchronous ref-write makes "previous state" undetectable to the reader effect on the same commit; use a pending-flag ref instead.
type: feedback
---

When two `useEffect`s in the same hook share a dep (typically a prop), and effect A reacts to that dep changing by synchronously updating a ref, effect B reading that same ref later on the *same commit* will see the **post-change** value — losing the "previous state" signal entirely. Within a single commit, statement order inside effect A doesn't help: the ref is written before effect B runs, period. Reordering the effect declarations is fragile (couples correctness to declaration order) and shouldn't be relied on.

The bug pattern: prop flips → effect A updates ref to new value + queues a `setBoard`/`setX` reset + unlatches a guard (`recordedRef`) → effect B sees stale derived state (e.g. `status` computed from a memoized board that hasn't been replaced yet) paired with the *new* prop, computes an inconsistent result (here: inverted W/L outcome), and fires a side effect that should have been blocked.

**The right fix is a one-bit `pendingResetRef`:**
- Trigger effect sets `pendingResetRef.current = true` when the prop change requires a downstream reset.
- Reader effect bails while the flag is set, *and* clears it only when it observes the post-reset state (e.g. `status === 'in_progress'` after the queued setBoard committed).
- Don't try to reuse the dep-tracking ref for both purposes; their lifetimes don't match.

**Why:** Hit this in production-shaped code (TicTacToe `useGame` post-terminal side flip — phantom backend records with inverted W/L). A reviewer-prescribed `humanPlayerRef.current !== humanPlayer` guard *looked* right but couldn't possibly fire because effect A had already updated the ref. Caught only by writing the failing regression test first and watching the prescribed fix not flip it green.

**How to apply:** Whenever I see two effects in the same hook sharing a dep where one drives a state reset and the other reacts to derived state — stop, trace the same-commit ordering explicitly, and assume any "compare ref to prop" guard is suspect. Default to a separate pending-flag ref. And always run the regression test against the *unfixed* code before applying any fix prescribed by a reviewer (or by me) — broken prescriptions are common and the failing-test-first protocol is the cheapest way to catch them.
