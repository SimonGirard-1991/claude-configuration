---
name: Invoke code-reviewer for load-bearing documentation
description: Don't auto-skip reviewer because the diff is markdown — operational docs (ADRs, runbooks, alert descriptions) need the same verification as code; only skip for trivial doc edits
type: feedback
---

The "Documentation, comments, or formatting" entry in my self-review Skip list is meant for *trivial* doc edits — typo fixes, comment-only changes, README cosmetic updates. Do NOT extend it to mean "any file ending in `.md` is exempt from review."

Load-bearing operational documentation gets reviewed. This includes (non-exhaustive):

- **ADRs** — define architectural decisions and threshold methodology that future operators rely on.
- **Runbooks** — incident response procedures that page someone follows under time pressure.
- **Alert descriptions / annotations** — read by on-call at 3am; a wrong claim misleads triage.
- **Dashboard panel docs / SLO definitions** — embedded in operational artifacts.
- **Schema migration commentary** — references to behavior that ops teams depend on.

A wrong commit hash, miscategorized SLI, unrealistic fire drill, or hand-wavy rationale in an ADR misleads the reader as effectively as a buggy alert expression. Skipping review on these is a false economy.

**Why:** User explicitly corrected me on Wealthpay observability commit 3 (ADR-008). I had unstaged the file and skipped the reviewer because "ADR is doc-only (no runtime effect)" — citing the protocol's Documentation entry in the Skip list. User wrote: "invoke code reviewer because documentation is important too." Their reasoning was implicit but clear: the ADR documents threshold rationale, fire-drill procedure, and the calibration log; future operators will treat it as truth. Wrong claims in it cause real-world bad decisions.

**How to apply:**
- Default for any non-trivial doc change: invoke `code-reviewer`. The cost is one Task spawn; the upside is catching wrong commit hashes, miscategorized severities, hand-wavy rationale.
- Skip only when the diff is genuinely trivial: a typo fix, a single-word comment-only change, a README link update, a CHANGELOG entry that just lists what shipped.
- The honest test: "If a future engineer reads this and acts on it, can they be misled?" If yes → review. If no (cosmetic only) → skip.
- Brief the reviewer with the same calibration depth as for code: state who reads the doc, what decisions they'll make from it, what's plausibly load-bearing. Generic "review this markdown" prompts produce shallow reviews.
- The "trust but verify" principle still applies — the reviewer's verdict on a doc is a second opinion, not a rubber stamp. Push back on style nits or scope creep.
