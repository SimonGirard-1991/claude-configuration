---
name: A11y — fieldset UA defaults and the legend/aria-describedby trap
description: Always reset fieldset UA border/padding under Tailwind; never split a fieldset's label from its description via aria-describedby on the fieldset itself.
type: feedback
---

Two recurring traps with `<fieldset>` + `<legend>` for radio/checkbox groups:

**1. UA-default border + padding.** Browsers render `<fieldset>` with a 2px groove border and horizontal padding by default, and the `<legend>` notches into that border. Tailwind doesn't reset these. Result: a stray frame around the radio group that looks broken. Fix: `border-0 p-0` (and arguably `m-0` for paranoia, though no current browser adds margin).

**2. Splitting label and description via `aria-describedby` on the `<fieldset>`.** Tempting refactor when the legend feels "too long": short noun phrase in `<legend>`, longer instruction in a `<p id={descId}>`, link via `aria-describedby={descId}` on the fieldset. Looks correct on paper. Don't do it: NVDA and VoiceOver historically don't reliably announce descriptions on `<fieldset>` because the fieldset's accessible name comes from `<legend>` and the ATs handle the group as a unit. Sighted users see the description (it's on the page); AT users may not hear it.

**Right options, in order:**
1. Keep the full label-and-description text in `<legend>` — works everywhere.
2. If you really need a split, put `aria-describedby` on each `<input>` inside the group, not on the fieldset. Per-control descriptions are well-supported.

**Why:** Code-reviewer agent flagged this as 🟡 in TicTacToe `StartingPlayerChoice`. The split-via-fieldset pattern is "correct-looking" enough that I almost shipped it; the AT-support reality is what made it wrong.

**How to apply:** Any time I'm building a radio/checkbox group with native `<fieldset>` + `<legend>`: (a) zero out border/padding on the fieldset, (b) put the full accessible name in `<legend>`, (c) only reach for `aria-describedby` if I'm willing to put it on each control instead of on the fieldset.
