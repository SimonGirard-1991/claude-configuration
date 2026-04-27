---
name: Trace effect-ordering bugs when multiple effects share a dep that just changed
description: When reviewing useEffect code where two effects share a changed dep (e.g. a prop), trace declaration order — an unlatch in one effect can re-enable a guarded action in the next.
type: feedback
---

When reviewing a hook with multiple `useEffect`s whose dep lists share a value that just changed (especially a prop or piece of state that gates something else), trace the effects in **declaration order** before approving.

A common failure mode: effect A "unlatches" a ref guard (e.g. `recordedRef.current = false`) and queues a `setBoard`/`setState`. In the *same commit*, effect B reads the same `status`/state — which has not yet updated because the queued setter only schedules a future render — sees the freshly-unlatched guard, and re-fires the action it was supposed to fire only once.

**Why:** missed this exact bug in a tic-tac-toe `useGame` review (2026-04-25). When `humanPlayer` flipped after a terminal game, the reset effect ran first (unlatched `recordedRef`), the terminal-state effect ran second (still saw the old terminal `status` because `setBoard` hadn't committed yet), inverted the outcome via `toOutcome(status, newHumanPlayer)`, and fired `onGameEnd` again with a flipped W/L. A peer review caught it; I had only checked the mid-game swap path.

**How to apply:**
- Whenever a re-render is triggered by a prop change that both (a) resets some "already-fired" guard and (b) is in another effect's dep list, ask: "in the render where this effect fires, has the state mutation from the reset effect *already committed*, or is it still queued?" The answer is almost always "still queued" — `setState` from an effect schedules; it doesn't update the value the *current* render's other effects observe.
- The defensive fix is usually to gate the action effect on a ref that tracks "the game/session this effect was set up for" rather than relying on declaration order.
- Always ask whether tests cover the *post-terminal* path of a state change, not just the *mid-flight* path. The post-terminal path is where these bugs hide.
