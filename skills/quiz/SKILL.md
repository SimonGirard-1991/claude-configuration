---
name: quiz
description: >-
  Generate a self-contained, playable HTML quiz from a source document you have
  studied — a learning-doc-writer guide, a system-design corpus chapter, or any
  Markdown doc. Foundation multiple-choice plus a harder "senior tier" of scenario
  traps and open-ended whiteboard prompts. Use when the user asks to be quizzed on
  a doc, e.g. "/quiz ~/Documents/ClaudeProjects/outbox-explained.md", "quiz me on
  2.03", or "make a quiz for the DDD guide". Output is <out>/<slug>.html, built
  from a validated JSON data file via the bundled template + builder.
---

# Document quiz generator

Produces an interactive quiz identical in behaviour to the tested engine: instant
feedback with explanations, a senior tier (scenario MCQ + self-graded whiteboard),
per-theme scoring, keyboard play, dark mode, and an interviewer-questions panel.
You only author the **question data**; the engine is a fixed, tested asset.

This skill is source-agnostic. It pairs naturally with the `learning-doc-writer`
agent: that agent writes a durable Markdown guide, then this skill turns the guide
into its companion quiz (see "Pairing with learning-doc-writer" below).

## Steps

1. **Resolve the source document(s).** Accept whichever the user gives:
   - **An explicit Markdown path** — e.g. `~/Documents/ClaudeProjects/outbox-pattern-explained.md`.
     This is the common case for a learning-doc-writer output.
   - **A corpus shorthand** — a chapter number ("2.03") or topic ("caching"), *when
     you are in a corpus repo* with a doc tree (e.g. `en/**/<num>-*.md` under
     `en/fundamentals`, `en/building-blocks`, `en/case-studies`, `en/method`,
     `en/cheat-sheets`). Resolve with `ls en/**/<num>-*.md`; confirm the match if the
     request was by topic. (Inside such a repo a project-scoped `quiz` skill usually
     wins over this global one — either is fine.)

   Confirm the resolved file(s) before proceeding.

2. **Read the source document(s) in full.** Every question must be grounded in the
   text. The best-quizzable docs expose their own seams: "confusion vs correct"
   tables, "what this teaches" / synthesis sections, and "the lesson / the pattern /
   a senior tell" call-outs. Mine those.

3. **Read `references/question-design.md`** (in this skill dir) and follow it — it
   defines the JSON schema, per-section counts, the senior-tell recipe, the
   whiteboard format, theme tagging, and the faithfulness rule.

4. **Choose the output location, slug, and brand, then write the data file.**
   - `<slug>` = the source file's stem (e.g. `outbox-pattern-explained`, or
     `2.09-partitioning-sharding`; for a multi-doc quiz, join stems). It must be a
     safe filename (letters, digits, `. _ -`).
   - `<out>` = the output directory. **Default: a `quizzes/` folder next to the
     source doc** (`<source-dir>/quizzes`). In a corpus repo, that is the repo's
     `quizzes/`.
   - `meta.brand` = the header label. Set it to the doc's domain — e.g.
     `"System Design Quiz"` for the corpus, `"DDD Quiz"` for the DDD guide. Defaults
     to `"Quiz"` if omitted.

   Write the JSON to `<out>/data/<slug>.json`. This JSON is the version-controlled
   source of truth — the HTML is generated from it.

5. **Adversarially validate the answers (required — semantic, not mechanical).**
   Before building, confirm the marked answer is the *only* defensible option in
   each MCQ. Prefer **independent reviewers** so author bias doesn't leak: spawn a
   few adversarial reviewer agents (Agent tool, `general-purpose`), each given the
   source document(s) and a slice of the questions, told to *try to defend each
   distractor* and return the flagged ones with a suggested repair. Adjudicate the
   findings against the source, then repair every genuine flag by (a) tightening the
   stem, (b) rewriting the distractor, or (c) reframing as a best-answer question.
   See `references/question-design.md` → "adversarial defensibility". The builder's
   `c:true` count and length gate do **not** replace this step.

   Note: this step needs the Agent tool. If you are running as a subagent without it
   (e.g. inside `learning-doc-writer`), do not silently skip the gate — hand the quiz
   back to a caller that can run the adversarial pass, or state plainly that the quiz
   is single-author-validated only.

6. **Build it:**
   ```bash
   python3 ~/.claude/skills/quiz/scripts/build_quiz.py <out>/data/<slug>.json --out <out>
   ```
   The builder auto-finds its bundled template, validates (exactly one correct option
   per MCQ, no empty fields, safe slug), and checks for length bias. If it errors, fix
   the JSON and re-run — a broken or gameable quiz cannot ship past it.

7. **Report** the output path and the printed summary (counts per section). Offer to
   open it: `open <out>/<slug>.html`.

## Pairing with learning-doc-writer

The intended flow when a user wants "a doc and a quiz on it":

1. Run the `learning-doc-writer` agent → it writes `<doc>.md` in its usual template.
2. Then, at the orchestrating level (which has the Agent tool), invoke this skill on
   that file: `/quiz <doc>.md`. It reads the fresh doc, authors the JSON, runs the
   adversarial pass, and builds `<doc-dir>/quizzes/<doc-stem>.html`.

Keeping the two as separate steps is deliberate: writing a durable doc and writing a
faithful, non-gameable quiz are different quality bars, and the quiz's adversarial
answer-validation needs subagents the doc-writer doesn't spawn. Do not fold the build
into the doc-writer if it costs you that gate.

## Notes

- **Single vs multi-source.** The engine adapts: a single-source quiz shows just "Full
  exam" (+ "Quick mix" when >12 MCQs); a multi-source quiz adds one per-source mode,
  labelled from `meta.chapters`. Senior/whiteboard modes appear only when those
  sections are non-empty. (`meta.chapters` is the section/source label list — for a
  single guide, one entry naming the doc; the field name is historical.)
- **Language.** Match the source doc's language. For a French doc, write French
  questions and, by convention, suffix the slug with `-fr`.
- **Don't regenerate the engine.** Never hand-write the HTML; always go through the
  JSON + builder so every quiz stays consistent and correct.
- **Iterating.** To tweak a quiz, edit `<out>/data/<slug>.json` and re-run the builder
  — same slug overwrites in place.

## Files in this skill

- `assets/template.html` — the engine shell with `__PLACEHOLDER__` markers
  (`__BRAND__`, `__TITLE__`, `__QUESTIONS__`, …).
- `scripts/build_quiz.py` — validator + builder (stdlib only); auto-finds the template.
- `references/question-design.md` — how to write good question data.
