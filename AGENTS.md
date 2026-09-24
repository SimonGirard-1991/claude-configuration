# Agents — maintainer notes

Claude Code reads `CLAUDE.md`, not `AGENTS.md`. Nothing here loads into a session; this
file exists so a future maintainer can see why the setup is shaped the way it is.

## Agents in this setup

| Agent | Role | Invoked by |
|---|---|---|
| `code-reviewer` | Staff-level review of a diff: design, correctness, operability, code-level. Severity-tagged 🔴/🟡/🔵, verdict ✅/⚠️/🔴. | The user directly, or a session running the self-review loop in `rules/java.md`. |
| `learning-doc-writer` | Pandoc-ready learning documents, with a mandatory independent adversarial review before hand-back. | The user directly, or auto-routed on its description. |

Both are `model: inherit`. The one deliberate exception is inside
`learning-doc-writer`: its fetch-only source-gathering spawns pass `sonnet`, because a
gatherer opens an already-identified source and reports what it says. Judgment spawns
never take the flag (decided 2026-08-13).

## Reviewer memory protocol

`memory: user` is set on both agents, so Claude Code injects the generic memory
instructions and the `MEMORY.md` index itself. Only the setup-specific half lives in
`agents/code-reviewer.md` § Memory protocol, and it is this:

- Prompt carries `Invocation: self-review loop`, or context otherwise shows an agent
  drove the invocation → **never save**. End with a **Proposed memory** note; the
  invoking session relays it verbatim and records it only on the user's approval.
- Direct user invocation with explicit feedback → the reviewer saves it itself.
- Ambiguous → fail closed, propose.

The reason is narrow and worth keeping: in a loop the only validator present is another
model, and architect pushback must not be laundered into reviewer calibration without a
human seeing it. Writes are confined to `agent-memory/code-reviewer/` and scratch — never
the repo, never config, never through `Bash` redirects — and since 2026-09-24
`hooks/reviewer-guard.py` enforces that rather than trusting the prompt with it.

Edge cases: a ⚠️ verdict carrying only 🔵 issues may return to the user unchanged, since
🔵 is judged on merit. A failed reviewer spawn falls back to a structured self-review and
says explicitly that the external reviewer was skipped — no retry loop.

## Decision log

- **The reviewer's read-only contract is a hook, not a promise** (2026-09-24).
  `memory: user` auto-enables Write and Edit, so "read-only on the repo" was held by the
  prompt alone. `hooks/reviewer-guard.py` runs from the reviewer's own frontmatter, and
  only while it does:
  - Edit/Write land only in its memory directory or scratch.
  - `git` is allowlisted rather than blocklisted, so an alias or a rare write verb is
    denied by default.
  - In-place edits, editors, `eval`, `sh -c`, write-capable `gh`, file-mutating commands,
    and redirects or `tee` outside scratch are denied.

  It fails closed. Test runners and builds still pass, because the prompt's
  `git status` invariant covers their side effects. `SubagentStop` now skips
  `code-reviewer`, `Explore` and `Plan`: a read-only agent cannot fix README drift, so
  blocking it up to eight times achieved nothing.
- **`bash-guard.py` judges each command segment, pinned by a fixture table**
  (2026-09-24). An audit ran 66 commands through the old guard and 25 got the wrong
  answer. A template name anywhere in a command (`.env.example`) exempted all of it, so
  `diff .env.example .env` read the real file unasked; `+ref` and `:ref` pushes and
  `rm -r .` passed; and joined lines produced false denials (`rm -rf build`, then
  `cd ..` on the next line). Now lines and `; && || |` split segments, templates are
  exempt per match, deny beats ask, and `scripts/test_hooks.py` pins both directions.
  The shebang is `/usr/bin/python3`: `env python3` resolved to a pyenv shim that fails
  in any repo pinning an uninstalled interpreter, so the guard was silently off there.
  Out of reach by design: a secret read that names no file (`grep -r KEY .`) — the
  sandbox trial owns that.
- **The architect layer is retired** (2026-09-09). `java-backend-architect` became
  `rules/java.md`, a path-scoped rule that loads only when a Java file is read;
  `script-engineer` became `rules/shell.md`; `discovery-analyst` became the manually
  invoked `scoping` skill; the two frontend agents were deleted outright. Evidence over
  the preceding month: 67 `code-reviewer` spawns, 3 `learning-doc-writer`, 1
  `java-backend-architect`, 0 for the other four — while seven agent descriptions cost
  ~3,170 words in every session's startup context, and Java skills were being loaded
  from main sessions rather than from the architect. `hooks/validate-agent-contracts.sh`
  went with them: it existed to police architect↔reviewer coupling that no longer has
  two sides. Recover any of them from tag `pre-best-practices-2026-09-07`.
- **Three architect stances restored into `rules/java.md`** (2026-09-09, same day).
  The first cut of the rule kept the stack conventions and the verification protocol but
  dropped what the architect prompt had owned outright rather than delegated to a skill:
  the contract-first mandate, modular-monolith-by-default, and the non-functional priority
  ordering with its review-scope rule. No skill carries them, so they were simply gone.
  Restored on Simon's call. The rule's `paths:` grew to cover `.avsc`, `.avdl`, `.proto`
  and OpenAPI YAML at the same time — a rule stating that a schema change *is* a code
  change cannot fire from a `**/*.java` scope, because the file being edited is the
  schema. 36 → 93 lines, against the architect's 424.
- **`rules/frontend.md` added; `code-reviewer` gains a frontend lens** (2026-09-09).
  The first pass retired both frontend agents with no replacement, on 0 spawns in the
  audit window — but 0 spawns meant "has not come up lately", not "will not". Restored on
  Simon's call: `frontend-architect`'s owned standards became a path-scoped rule, and
  `frontend-code-reviewer`'s six review dimensions became a **frontend lens** in
  `code-reviewer.md`, mirroring the standalone-script lens already there. Without that
  second half the rule would tell a session what to build while the only surviving
  reviewer judged a `.tsx` diff by backend axes. 658 agent lines → 161 rule lines plus a
  43-line lens.
- **The calibration tier taxonomy is shared vocabulary**, not an enforced contract:
  *throwaway / internal tool / production service / critical financial system*. It
  originates in `code-reviewer` ("Calibrate your bar") and is emitted by the `scoping`
  skill, so a project's business tier flows into review calibration during the build.
  Reword it in one place and the other stops speaking the same language.
- **Fetch-only spawns take Sonnet; judgment spawns never do** (2026-08-13). A sub-agent
  that opens an already-identified source and reports what it says is retrieval. Anything
  that judges — a reviewer above all — is the opposite job: out of its depth, a reviewer
  does not return "unsure", it returns a confident ✅, and it is the last gate before work
  ships.
- **Comments default to none in generated code** (2026-08-11). The rule lives in
  `CLAUDE.md` § Code comments at user scope, and `code-reviewer` carries the matching
  **Comment noise** bullet in its code-level layer — which is what makes the review
  enforce it rather than merely assert it. Keep both halves: doctrine alone and breaches
  ship unopposed; reviewer bullet alone and nobody was told the rule they are judged on.
  The fix was structural — `skills/hexagonal-module-bootstrap` had carried 119
  explanatory comment lines inside its Java fences, so copying a template meant copying
  its comment density.
- **Reviewers hold conditional memory-write access** (2026-07-08, superseding the
  memory-file half of a 2026-04-23 read-only rule). The April rule conflated "don't
  modify the reviewed artifact" — still absolute — with "don't keep your own notebook",
  which froze the reviewer's learning loop. The risk it actually guarded against stays
  blocked by the loop-context ban above.

## Known open questions

- **Test-running discipline**: the reviewer can run tests, but the invoking session is
  responsible for green tests before invocation. Whether the reviewer re-runs them is
  non-deterministic. Acceptable; revisit if review latency becomes a concern.
- **Do path-scoped rules fire when a file is read through Bash?** `rules/java.md` earns
  its place only if it loads. The docs say path-scoped rules trigger when Claude *reads*
  a matching file, and under `defaultMode: auto` the harness steers reads toward `cat`
  and `sed -n` rather than the Read tool. This is the same blind spot that moved the
  validators off `PostToolUse`. Verify with `/context` in a Java repo, or the
  `InstructionsLoaded` hook; if it does not fire, the conventions belong back in
  `CLAUDE.md` or in a skill.
