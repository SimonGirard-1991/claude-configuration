# Question-design playbook

How to write the `quiz-data.json` that `build_quiz.py` turns into a playable quiz.
The engine is fixed and tested — your only job is the **question data**, and its
quality is the whole quiz. Read the target chapter fully first.

## The one rule that matters most: faithfulness

Every fact, number, name, and claim must be **grounded in the chapter text**. No
outside knowledge, no invented figures. If the chapter states a number (e.g.
"a pool of 100 at 20 ms → 5,000 q/s"), use it exactly. The explanations should
read like the chapter's own reasoning, compressed. A quiz that teaches something
the doc doesn't say is a bug, even if the something is true.

## The second rule: no length tell

**A test-taker must not be able to score well without reading the question.** The
most common way this breaks: the correct answer is the long, careful, fully-hedged
sentence and the distractors are short and blunt. Then "pick the longest option"
beats the quiz. This is the single most important thing to get right after
faithfulness, and the builder **fails the build** if the correct option is >25%
longer than every distractor in more than ~35% of MCQs.

Rules:

- **Match option lengths.** Every option in a question should be within roughly
  ±20% of the others' length. Never let the correct answer be systematically the
  longest — vary which option is longest, and let the correct one be the *shortest*
  sometimes.
- **Distractors are as detailed and specific as the correct answer** — same
  register, same level of qualification, same use of `<code>` terms and numbers.
  A blunt "It's slower" next to a nuanced correct answer is a giveaway.
- **Make wrong answers *subtly* wrong: one precise flaw the reader must find.** The
  distractor should be a confident, well-formed, plausible statement that is wrong
  in exactly one identifiable way. If you can tell it's wrong without reading the
  stem, it's too weak.

Distractor patterns that force reading (mine the chapter for the real version of each):

| Pattern | Example shape |
|---|---|
| Right idea, wrong direction | swaps reads/writes, up/down, primary/replica |
| Right mechanism, wrong layer | attributes a transport fix to the application layer |
| Right mechanism, wrong trigger | correct tool, but for a pain it doesn't relieve |
| True but doesn't answer the stem | a real fact from the chapter, irrelevant here |
| Plausible but wrong number | an estimate that's off by an order of magnitude |
| Cause/effect swapped | names the symptom as the root cause |
| Confident myth | the exact misconception the chapter warns against |

When you finish a question, ask: *"If I hid the stem, could I still pick the answer
from the options alone?"* If yes — by length, by hedging, or by one option being
the only detailed one — rewrite the distractors until you can't.

## The third check: adversarial defensibility (semantic, not mechanical)

Marking exactly one option `c:true` is necessary but **not sufficient**. A
distractor can be *also true* under a realistic reading, giving the question two
defensible answers even though only one is flagged. So run an **adversarial pass**:
for every MCQ, adopt the attacker's stance and try to *defend each distractor*.

For each option that isn't the intended answer, ask: **"Under what realistic
assumption is this also correct?"** If you can construct one a competent engineer
would actually make — an alternative reading of an under-specified stem, a true
statement that technically answers the stem, an "it depends" the stem didn't rule
out — the question is broken. Three repairs, in order of preference:

1. **Tighten the stem** — add the missing context that excludes the assumption
   (best: keeps the distractor genuinely wrong). E.g. change "what correctness
   problem do you now own?" to "what correctness problem does *reading from the
   replicas* introduce?", so a durability-on-failover distractor no longer fits.
2. **Rewrite the distractor** — break the one thing that made it defensible, while
   keeping it the same length and plausibility as the others.
3. **Frame as best-answer** — if the topic is genuinely "it depends" and several
   options have merit, make the stem ask for the *best* / *most defensible* /
   *first* choice, and ensure the marked answer is strictly better than every other
   on the stem's stated criterion. Use sparingly; a true single-answer question
   beats a soft "best answer" one.

Watch especially for the **"true but doesn't answer the stem"** distractor: a real
fact from the chapter is still a defensibility problem if a loose stem lets a reader
read it as an answer.

The test: **hand the question to someone trying to justify a wrong answer — if they
can, fix it.** Do this for every MCQ before building, ideally with *independent*
reviewers, since authors rationalise their own distractors. The skill runs this as
independent adversarial reviewer agents (see `SKILL.md`, step 5).

## JSON schema

```jsonc
{
  "meta": {
    "slug": "2.03-load-balancing",                 // = source-doc filename stem; output is <out>/<slug>.html
    "title": "System Design Quiz — Load Balancing",
    "brand": "System Design Quiz",                 // header brand; set to the doc's domain (default "Quiz")
    "subtitle": "L4 vs L7, algorithms, health checks, and the stateful-tier problem",
    "chapters": ["2.03 · Load Balancing"],         // "<label> · <Name>"; drives the source chips + per-source mode labels
    "themes": ["L4 vs L7", "Algorithms", "Health checks", "..."],  // 8-14 short strings; the controlled vocabulary
    "footer": "Source: <b>2.03 Load Balancing</b> — your own corpus. Explanations mirror the docs."
  },
  "questions":   [ /* foundation MCQs */ ],
  "senior":      [ /* senior-tell MCQs */ ],
  "whiteboard":  [ /* open-ended prompts */ ],
  "interviewer": [ /* classic interviewer prompts + model answers */ ]
}
```

Item shapes:

- **MCQ** (`questions` and `senior`):
  `{ "ch":"2.03", "theme":"Algorithms", "q":"...", "opts":[ {"t":"...","c":false}, {"t":"...","c":true}, ... ], "ex":"..." }`
  — 3 or 4 options, **exactly one** with `"c":true`. `senior` items may omit `tier`; the builder stamps `"tier":"senior"`.
- **Whiteboard** (`whiteboard`):
  `{ "type":"open", "ch":"2.03", "theme":"...", "q":"...", "points":[ "...", "..." ], "trap":"..." }`
  — `points` is the checklist a senior hits (4-6); `trap` is the common wrong move.
- **Interviewer** (`interviewer`):
  `{ "ch":"2.03", "q":"“...the question...”", "a":"↳ one-line model answer" }` (don't include the ↳; the engine adds it).

## Calibration (scale to the chapter's richness)

| Section      | Count   | Notes |
|--------------|---------|-------|
| `questions`  | 12–18   | the foundation MCQs; broad coverage |
| `senior`     | 8–14    | the hard scenario traps |
| `whiteboard` | 6–10    | open synthesis prompts |
| `interviewer`| 8–12    | classic prompts, short model answers |
| `themes`     | 8–14    | one controlled vocabulary; every item tagged with one |

A meaty chapter (~25 KB) supports the upper end. Don't pad — a wrong or thin
question is worse than a missing one.

## Writing foundation MCQs (`questions`)

- Test **understanding, not recall**. The best source is the chapter's own
  "confusion vs correct" tables — the wrong column becomes your distractors.
- **Distractors must be plausible.** Each should be something a reasonable person
  might believe; no obvious throwaways. Keep options **parallel in length** so the
  correct one isn't guessable by being the longest.
- The **explanation** (`ex`) restates the chapter's reasoning and is
  self-contained — the reader learns even if they got it right. Lead with the
  verdict fragment isn't needed (the engine prepends "Correct." / "Not quite.").

## Writing senior tells (`senior`)

A "senior tell" is a question where **every option looks defensible** and the
wrong ones are exactly what a confident mid-level engineer would say. The right
answer reflects judgment: sequencing, knowing what *not* to do, naming the precise
mechanism, sizing with the chapter's numbers, or calling out the hidden cost.

Recipe: embed a **plausible-but-flawed decision or design** in the scenario, then
ask for the senior read or the fix. Mine the chapter's callouts: "**a senior
tell**", "**worked subtlety**", "**the lesson**", "**the signal / the pattern**",
and any "X before its pain is felt" warnings. These are the seams the chapter
itself flags as where juniors go wrong.

Good senior-tell scenarios: a teammate proposes the premature/over-engineered
move; a plausible design that breaks under a named condition; a number that
sounds fine but fails a Little's-Law/estimate check; "synthetic passes but real
users don't"; a diagnosis where the obvious cause is wrong.

## Writing whiteboard prompts (`whiteboard`)

Open synthesis questions the reader answers out loud, then self-grades against a
model answer. Ground them in the chapter's "**what this teaches**" / summary
section — those are the load-bearing takeaways.

- `q` — a realistic prompt ("Design X and justify every choice", "Explain to a
  mid-level why Y", "Walk the ladder for Z").
- `points` — the 4–6 things a senior actually says. Each a crisp, checkable claim,
  not a paragraph. Order them the way a strong answer flows.
- `trap` — the one wrong move that most answers make.

## Themes (the controlled vocabulary)

Pick 8–14 short theme strings for the chapter and **tag every item** with one of
them (put the same strings in `meta.themes`). Consistency matters: the results
screen aggregates accuracy per theme, so "Caching" and "Cache" as two themes
would split the bar. Reuse, don't invent per-item.

## Formatting notes

- HTML is allowed inside any string: `<code>max_connections</code>`, `<i>emphasis</i>`,
  `<b>bold</b>`. The builder neutralises `</script>` automatically.
- Use **curly quotes** `“ ”` for quotations embedded in a string, so you never
  fight JSON's `\"` escaping. Apostrophes are fine as-is.
- `meta.footer` accepts HTML (that's where the `<b>` chapter name goes).
- `meta.slug` **must** equal the chapter's filename stem (e.g. `2.09-partitioning-sharding`)
  so quizzes sort next to the chapters and rebuilds overwrite cleanly.

## Before you hand off

- Exactly one `c:true` per MCQ (the builder enforces this, but check as you write).
- Every item tagged with a theme that appears in `meta.themes`.
- No claim that isn't in the chapter. Re-scan the doc for the specific numbers.
- Options parallel in length; distractors genuinely tempting.
