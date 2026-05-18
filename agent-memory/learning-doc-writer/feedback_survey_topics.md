---
name: Survey topics need different structure than concept or system docs
description: When the topic is a broad survey (sécurité backend, perf Postgres, microservices patterns) rather than a focused concept or system, classify it explicitly and adapt structure — or propose splitting into 2-3 docs before drafting.
type: feedback
---

A survey topic is a category of doc the system prompt does not name explicitly, and which the agent treats as a "system walkthrough" by default. This produces a mismatch: the doc is written as a linear narrative (with `**La leçon :**` closures, opinions stacking, takeaways at the end) but the length and breadth force the reader to use it as a reference manual consulted by section. The two modes are incompatible.

**Why:** the user's "Sécurité backend pour développeurs" doc (May 2026) hit 2200 lines / 46 PDF pages on a topic that is a survey, not a system. Another Claude reviewing the doc identified that the structure (narrative ton, lessons closing each section) clashed with the size (read-by-section reference). The system prompt's default targets (200-400 / 800-1500) did not produce a "stop and propose split" signal because the user said "exhaustif".

**How to apply:**

1. **Classify the topic before drafting.** Three categories:
   - *Focused concept* (rate limiting, idempotence, what `rate()` computes) → narrative, 200-400 lines, read end-to-end.
   - *Concrete system* (the Wealthpay observability stack, the Postgres upgrade) → narrative also, 800-1500 lines, justified by a real story.
   - *Broad survey* (sécurité backend en général, perf Postgres en général, microservices patterns) → reference manual, NOT a narrative. Different structural rules apply.

2. **For surveys, surface the trade-off before drafting.** "exhaustif" from the user is a breadth signal, not a single-doc signal. Ask: *"tu veux un manuel de référence en 1 PDF (sera consulté par section), ou 2-3 docs ciblés (lus séquentiellement)?"*. Do not unilaterally choose the single-doc path on a topic that has 5+ independent sub-domains.

3. **If forced into a single survey doc, adapt the structure:**
   - Fewer `**La leçon :**` closures. Not every section needs one. The lesson goes in the synthesis at the end.
   - Sections must be autonomous — usable without having read the previous one.
   - The intro of each section explicitly names what question it answers, because the reader will jump in cold.
   - Cross-references in the text (`see §X`) become important.

4. **Hard rule for the `**Une subtilité travaillée :**` label.** Reserved for content NOT findable on page 1 of OWASP / Spring docs / RFC / Stack Overflow top result. If the "subtilité" is documented by the framework maintainer, integrate it as prose without label — the label promises a discovery, and applied to standard content it becomes hollow. On a conceptual survey, expect >50% of "subtilities" to be standard, hence not labellisable. The Postgres-doc rate of labels-honouring-promise was ~100% because each came from lived incident; the security-doc rate was ~40% (5 real, 4 standard mislabellisé, 2 borderline out of 11). The label dilutes when it is over-applied.

5. **Self-critique pass extension for `**La leçon :**` and `**Le pattern :**`.** For each occurrence, ask: *"Could a careful reader of the previous paragraph derive this lesson without me stating it?"* If yes, cut. If the lesson re-states the paragraph's main claim in fewer words, it is a structural marker, not a synthesis — cut it. On the security doc, ~25% of lessons (6-8 of 25) were paraphrases. Catching them at self-critique would have removed a tic without losing content.

6. **The structural limit, owned explicitly.** On a purely conceptual topic without lived material (no repo to ground in, no incident to remember), the agent CAN organize and hierarchize but CANNOT invent vécu subtleties. Pretending otherwise via inflated labels promises depth not delivered. The right response on conceptual surveys is *more restraint on labels*, not more labels — and to consider whether the user is better served by a chat-mode discussion than a single agent-produced doc.
