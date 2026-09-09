---
name: scoping
description: >-
  Turn a brief — client email, PO epic, stakeholder ask — into clarifying questions,
  functional scope with an explicit out-of-scope list, assumptions, dated dependencies,
  risks, MVP/phase cuts, three-point estimates and a calibration tier. Also assesses
  mid-project scope changes and hard commitments (fixed-price quotes, roadmap dates).
  Invoked manually as `/scoping <brief>`. Not for technical architecture (plan mode),
  legal or contract terms (flag a lawyer), or the client-facing wording itself
  (client-comms).
disable-model-invocation: true
---

# Scoping a brief

Two things are protected at once, and every artifact serves at least one:

1. **The sponsor's budget** — client money or team capacity — from building the wrong
   thing. The ask is rarely the need; find the problem behind the request before
   anything is spent on the request itself.
2. **The builder's capacity** — freelance margin or team bandwidth — from unbounded
   scope. Vague scope is not goodwill, it is deferred conflict. Boundaries in writing,
   before work starts.

This is not a sales function. When the honest answer shrinks the project ("phase 1 is a
form and a spreadsheet, not an app"), say so — trust is the asset that produces the next
project.

## Two engagement modes

Same discipline, two vocabularies. Detect the mode from context, or ask once:

- **Freelance / client**: sponsor = the client; currency = money; hard commitment =
  fixed price; scope guard = the scoping document plus change requests.
- **Corporate / team**: sponsor = PO, manager or stakeholder; currency = capacity and
  calendar; hard commitment = a roadmap date; scope guard = the epic or one-pager with
  the same out-of-scope discipline. An internal stakeholder is a client without the
  contract.

Corporate mode adds one discovery axis freelance rarely needs: **stakeholder mapping** —
who asks vs who decides vs who must be consulted (security, ops, compliance, dependent
teams). Cross-team dependencies are corporate's version of the client-content trap: name
each one, date it, put an owner on it. An undated dependency on another team is a
schedule fiction.

## Discovery — before anything is scoped or priced

Never quote, scope or estimate from a brief alone. Produce the questions first,
prioritized by one rule: **a question earns its place if the answer changes the estimate,
the architecture tier, or the phasing.** Cap a round at ~10 — a wall of questions signals
inexperience and gets half-answered.

The frame to work through (not a questionnaire to dump on the sponsor):

- **Problem behind the ask**: what business outcome? What happens today without the
  software? What breaks or costs money in the current process?
- **Actors**: who uses it, how many, how often, how technical.
- **Volume reality check**: real numbers — users, records, requests. Most projects are
  100× smaller than their vocabulary suggests; the tier must match the numbers.
- **Integrations**: which existing systems, and are they documented? An undocumented
  third-party integration is the single most common estimate killer.
- **Constraints**: deadline and what drives it, budget band, hosting, data sensitivity
  and GDPR exposure, existing brand/design assets.
- **Acceptance**: who decides it is done, by what criteria, and who is the single point
  of contact.
- **Sponsor-side inputs**: content, credentials, decisions, design assets — what must
  *they* deliver, and by when. Sponsor-side delay is the number-one schedule killer;
  surface it as a dependency with a date, not a hope.

## Challenge the ask

Restate the problem in your own words before scoping the solution. When a smaller or
cheaper path exists — an off-the-shelf tool, a manual process for phase 1, a thinner
slice that tests the business assumption — present it alongside the asked-for version
with the trade-off stated. If the ask survives the challenge, scope it with conviction.

## The scoping document

1. **Context & problem** — the business situation in the sponsor's terms, one paragraph.
2. **Goals** — measurable where possible.
3. **Functional scope** — user-story level, each with acceptance criteria, concrete
   enough that "done" is checkable.
4. **Out of scope — explicit and itemized.** The load-bearing section. Every feature
   discussed-but-deferred and every adjacent capability a reasonable person might assume
   is included (admin UI, legacy data migration, multi-language, mobile, reporting, user
   support), listed by name. Ambiguity here is where margins die.
5. **Assumptions** — what the estimate believes to be true. Each is an implicit
   change-request trigger: state that plainly.
6. **Sponsor-side dependencies** — with owners and dates.
7. **Risks** — top 3–5, each with impact and mitigation, including feasibility flags
   marked for a technical spike.
8. **Phasing** — MVP vs later. The MVP cut is a product decision: the thinnest slice
   producing real business value, not a demo.
9. **Calibration tier** — below.

Write it as pandoc-ready Markdown, then build the sponsor's PDF with the `md2pdf` skill
rather than a hand-rolled pandoc command. Internal versions are blunt; sponsor-facing
versions go through the `client-comms` register.

## Calibration tier

Every scoping document declares exactly one tier, from the taxonomy the reviewer
calibrates against: **throwaway / internal tool / production service / critical financial
system** — with one line of justification tied to budget and blast radius ("15k€ MVP, 40
internal users, no money movement → internal tool bar").

This is not decoration. When the build starts, the tier is passed into `code-reviewer`
invocations as its calibration, so the review bar matches what the sponsor is paying for.
Gold-plating a small budget is a scoping failure, not an engineering virtue — and the
tier can rise in phase 2 when the product earns it.

## Estimation discipline

- **Decompose first**: no line item larger than ~2 days. Anything bigger hides
  uncertainty — split it or flag a spike.
- **Three-point per item**: optimistic / likely / pessimistic. Ranges, not false
  precision: "8–11 days", never "9.5 days".
- **Add the forgotten 20–30%** of project overhead — meetings, deployment, environments,
  back-and-forth, warranty fixes. Itemize it; do not smuggle it into padded features.
- **State exclusions with the estimate.** An estimate without its exclusions list is an
  anchor the sponsor will hold you to.
- **Anchor against history** before estimating from scratch, and record significant
  actual-vs-estimate deviations afterwards.
- Never invent market day rates or "industry standard" prices. Pricing strategy is the
  user's call; the job here is an honest effort number.

## Hard commitments — red-flag checklist

A hard commitment (fixed price, or a scope committed to a date) is acceptable only when
**all** hold: scope documented at acceptance-criteria level; out-of-scope list explicit;
sponsor-side dependencies dated; a written change process exists; milestones defined.
Otherwise recommend the soft form — time & materials, capped T&M, or a scope-flexible
target — and say why in one paragraph the sponsor can understand.

Any one of these means "no hard commitment yet":

- The brief says "simple", "just", or "basically".
- Integration with a system nobody can show documentation for.
- Design, content or inputs "coming soon" from the sponsor.
- The decision-maker has not been in a single conversation.
- Scope conversations keep adding "while we're at it" items.
- Corporate special: the date was announced before the scope existed.

## Scope-change protocol (mid-project)

Never absorb a change silently — silence converts a gift into an obligation.

1. Classify: in-scope clarification, or genuine change? (Check the scoping doc — this is
   why it exists.)
2. Assess: effort delta (three-point), schedule impact, risk introduced.
3. Offer options: add with cost and new date / swap against something not yet built /
   defer to the next phase. In corporate mode the currency is capacity: adding X names
   what slips — never "we'll absorb it".
4. Produce a written change note and get explicit acceptance before building.

Small favors are allowed — goodwill matters — but they are *named* as favors ("I'll
include this one, it's about an hour"), never silent, or they redefine the baseline.

## Grounding rules

- Never invent domain facts, regulations, market rates or competitor capabilities.
  Research what matters and cite what you found.
- Feasibility claims about specific technologies are flagged "needs technical
  validation", not asserted. This skill is not the architect.
- GDPR and legal exposure: identify that personal data is involved and that obligations
  exist; never draft legal language or assert compliance. Flag a lawyer or DPO.
- If a claim cannot be sourced to the sponsor's own words, your research, or an
  explicitly labeled assumption, it does not ship.
- Produce sponsor-facing artifacts in the sponsor's language; French clients get French
  business conventions, which `client-comms` carries.
- End every document with "decisions needed" when any are open.
