---
name: client-comms
description: Use when writing anything a client or a non-technical internal stakeholder (PO, management, another team) will read — proposals, scoping documents (sponsor-facing version), status updates, scope-change or trade-off notes, delay or incident notices, and explanations of technical topics for non-technical readers. Covers register (plain language, outcome-first), ready structures for the five recurring formats, and French business conventions (vouvoiement, formats, formules). Skip for developer-facing documentation (learning-doc-writer), internal notes, code comments, commit messages, or anything only the author reads — blunt internal register is correct there.
---

# Client Communications — register and structures

This skill encodes how to write for clients: people who are paying for outcomes, reading on a phone between meetings, and judging professionalism by clarity, not vocabulary. It pairs with the `discovery-analyst` agent (which produces the scoping substance) — this skill governs the *wording* of anything that crosses the client boundary.

## First decide: is a client (or a non-technical stakeholder) reading this?

- Written for a client, their stakeholders, or a non-technical internal audience (PO, management, another team) → apply this skill. An internal stakeholder is a client without the contract: same register, same structures, minus the contractual weight — the devis/proposal legal caution applies only to real clients.
- Internal working notes, dev docs, anything for future-self or fellow developers → close this skill; blunt and technical is correct.
- A contract, legal commitment, or liability wording → this skill does not apply; flag a lawyer. You may draft *around* legal sections, never the sections themselves.

## Register rules — all formats

1. **Outcome first, technique second.** Lead with what it means for their business ("orders won't be lost during payment retries"), not the mechanism ("implemented an idempotent consumer"). Technique goes in one supporting sentence, only if it builds confidence.
2. **Plain language.** Every unavoidable technical term gets a half-line translation on first use. If a sentence needs two, rewrite it.
3. **Numbers over adjectives.** "Page loads in under a second" beats "much faster". "8–11 days" beats "quite quick". No number available → say what will be measured.
4. **Commit only to what you can hold.** Dates you control get a date; dates with dependencies get a range plus the dependency named. Never promise absolutes ("100% secure", "no downtime") — offer the practice instead ("industry-standard encryption, tested restore procedure").
5. **Honesty with a plan.** Problems are stated as fact + impact + plan + new commitment, in that order, without burying the fact. Never blame — not the client, not a previous contractor, not a library. Neutral craft ("the existing system doesn't support X, so we'll…") reads as professionalism.
6. **The one-screen rule.** The key message and any ask sit in the first three lines. Detail follows for those who scroll. One topic per message when possible.
7. **Every message that needs something ends with an explicit ask and a date** ("To stay on schedule, I need the product photos by Friday 12th").

## The five structures

### 1. Status update (weekly rhythm)
- Done since last update (outcomes, not task names)
- Next (what the client will see, when)
- **Needs from you** (decisions/inputs, each with a date and what it blocks)
- Risks & dates (only real ones — an empty risk section some weeks builds trust in the non-empty ones)

### 2. Proposal / scoping letter
- Context: their problem, in their words (proof of listening — one paragraph)
- Proposed scope: what they get, phrased as capabilities
- **Out of scope**: itemized, framed constructively ("planned for a later phase" where true)
- Timeline & price: ranges with what drives them; payment milestones
- Assumptions & what we need from you
- Next step: one concrete action to accept

### 3. Scope-change note
- Your request, restated (so they see they were heard)
- Impact: effort, schedule, cost — numbers
- Options: add / swap / defer, each one line, with a recommendation
- What happens on acceptance (and that work starts after written OK)

### 4. Delay or problem notice
- The fact and the impact on them, first sentence, no wind-up
- Cause in one sentence (no essay, no blame)
- The plan and the new committed date
- What, if anything, you're doing to compensate — offered, not begged

### 5. Technical explanation for a decision
- The choice in business terms + what it costs/saves (money, time, risk)
- One analogy if it genuinely clarifies (skip forced ones)
- The recommendation and its trade-off, honestly stated
- The decision you need from them, with a default if they don't care ("if I don't hear otherwise, I'll do A")

## French clients — conventions

- **Vouvoiement** by default; switch only if the client tutoies first and the relationship supports it.
- Modern business formules — professional but not 19th-century: « Bonjour Madame/Monsieur X », close with « Bien cordialement » / « Cordialement ». Skip « Je vous prie d'agréer… » outside formal letters (devis/courrier officiel, where it remains correct).
- A clear « Objet : » line on emails; one objet, one sujet.
- Formats: dates « 12 juillet 2026 », numbers « 1 234,56 € » (space thousands, comma decimals), 14h30.
- Keep anglicisms minimal in client-facing prose: « planning », « deadline » are accepted; prefer « périmètre » to "scope", « livrable » to "deliverable", « recette » for acceptance testing.
- Quotes and proposals for French clients: « devis » carries legal weight once accepted — keep the scope wording in it aligned word-for-word with the scoping document.

## Formal deliverables — PDF path

Proposals, scoping documents, and end-of-phase reports go out as PDFs, not raw Markdown: write pandoc-ready Markdown with YAML frontmatter and build via the existing LuaLaTeX pipeline (same toolchain as `learning-doc-writer` — see that agent's conventions for frontmatter that the template expects). Emails stay emails: no PDF for a status update.

## Never

- Never criticize prior contractors or the client's existing system beyond neutral fact.
- Never send a number (price, date) you haven't checked against the estimate or plan.
- Never let enthusiasm write a commitment the scoping document doesn't back.
- Never bury a needed decision in paragraph four — it goes in the first three lines and the closing ask.
