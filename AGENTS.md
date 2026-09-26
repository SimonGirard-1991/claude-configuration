# Agents — maintainer notes

This file exists so a future maintainer can see why the setup is shaped the way it is.
Claude Code loads it as project instructions in sessions started in `~/.claude` (about
4.7k tokens), and nowhere else. That is kept on purpose: it is the context a session
working on this config needs.

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

- **Hooks and MCP wrappers are carved out of `shell.md`'s shebang and strict mode**
  (2026-09-27). The eight bash hooks and both MCP wrappers in `~/bin` use `#!/bin/bash`
  without `set -euo pipefail`, which broke two of the rule's four hard rules. Rewriting
  them was rejected. A hook's exit code is its interface: Claude Code reads 0 as pass, 2
  as block and anything else as an error. Under `set -e`, a failing command's own status
  would become the hook's, so a stray 2 would block by accident. The fixed interpreter
  matches the Python hooks' `/usr/bin/python3` pin. shellcheck and shfmt still apply, and
  the four files that failed shfmt now pass it.
- **SubagentStop validates only the agents that can edit** (2026-09-27). The 09-24
  denylist skipped `code-reviewer`, `Explore` and `Plan` and checked every other agent
  type by default. That included `claude-code-guide`, which only answers questions and
  could be blocked by drift it cannot fix. Under the sandbox, no subagent can fix
  `skills/`, `rules/` or `hooks/` through Bash either. The matcher is now an allowlist:
  `general-purpose`, `claude`, `learning-doc-writer` and `statusline-setup`. An editing
  agent missing from the list still does not escape the check, because the main
  session's Stop hook runs the same validators at the end of the turn. `fork` is left out
  on purpose. The check covers the whole tree, so any listed agent can be blocked for
  drift the main session has not finished, but a fork is the likeliest case, since it is
  spawned mid-change with the main session's context. When a new agent that can edit
  is added, add it to the matcher too.
- **Secret environment variables are named in managed settings, not here** (2026-09-26).
  The sandbox strips a variable only when `sandbox.credentials.envVars` names it, and a
  token's name can name its project, which in this public repo can be a client's. The two
  project-token entries moved to machine-level managed settings. Deny entries merge across
  every settings scope, so the effect is unchanged: both tokens are absent from a sandboxed
  environment and present outside it, checked both ways. The unpushed commits that carried
  the names were rebuilt before any push. The shell rc still exports both tokens, so
  unsandboxed processes and hooks inherit them. The stronger option, having each consumer
  read the Keychain as brave-search does, was not taken. A new secret variable goes to
  managed settings the same way.
- **This file loads in `~/.claude` sessions, and stays** (2026-09-24). `/context` showed
  it injected as project memory at session start, which contradicted this file's first
  paragraph and README's row, both of which said nothing here loads. Renaming it out of
  the loader's reach was rejected: the cost falls only on sessions that edit this config,
  and those are the sessions that need the decision log. The two sentences were fixed
  instead.
- **The Sonar gate skips a re-run when no fingerprinted input changed** (2026-09-24).
  In an opted-in repo, every Stop re-ran the Maven build and analysis while the branch
  differed from its base in any java file, so a turn that touched only docs paid for a
  full scan. A green run now leaves a fingerprint — the base commit, then the diff and
  untracked files for java sources, poms and the contract schemas `rules/java.md` treats
  as code, then `.sonar-gate`, the gate and the hook — and a Stop that matches it skips
  the scan. The test suite derives the schema list from `rules/java.md`, so a drift
  between the two fails the suite. Resources and `.mvn/` stay out on purpose, because counting them
  would make every config-only turn a Maven build again. Resolved dependencies and the
  server's profile are not in the working tree at all; dependency declarations are, in
  the poms, and those count. Only green runs record the fingerprint, and it is taken
  before the change set is read, so nothing landing later can be recorded as clean.
  The cache would have made one gate flaw permanent, so the gate was fixed first. With
  no task id in the scanner's report, or a server task still unfinished after 300s, it
  read the issues API anyway, which answers from the previous analysis. A stale green
  used to last one Stop; cached, it would have lasted until the next fingerprinted
  change. Both cases now exit 1, which the hook reports as "checks are OFF" and never
  records. The base was a hardcoded `main`, so a `master` repo compared against HEAD and
  never gated committed branch work; it now comes from `origin/HEAD`, then `main`, then
  `master`. No repo carried `.sonar-gate` on that date, so the change waits for the
  first one that opts in.
- **MCP keys leave the session environment, and the servers are pinned** (2026-09-24).
  The shell rc exported the Brave key, and an old launcher script exported it again, so
  every Claude session and each of its Bash subprocesses carried it; `bash-guard.py` can
  only deny the obvious ways to print it. Now a wrapper reads the key from the Keychain
  and runs the server, the pattern fal-ai already used. That takes the key out of the
  sessions' environment, not out of reach: the item answers any process that runs
  `/usr/bin/security`, and any process running as this user can. The wrapper starts the
  server from `/`, because Claude Code starts MCP servers in the session's project
  directory, where the server's dotenv would load that project's `.env`.
  All three `npx` servers ran unpinned — playwright as `@latest`, from an absolute nvm
  path that the next Node upgrade would break. brave-search, the one holding a key, now
  runs from a local install with a lockfile, like fal-ai, so its whole tree is pinned.
  context7 and playwright are pinned on plain `npx`, the top-level package only, and
  launch with `--prefix /`: npx fetches metadata at every start from the registry the
  launch directory's `.npmrc` names, so a project pointing at an unreachable registry
  stopped them starting — a 70s failure, against 1s with the flag. `cd /` would have done
  the same, but it needs a wrapper per server, and `--prefix /` needs none: npm looks for
  the project `.npmrc` at the prefix, without moving the process. (playwright takes its
  workspace and output directory from the client's first MCP root and falls back to its
  working directory only when a client sends none, so `cd /` would not have moved them
  either.) The project-scope
  `.mcp.json` held only a duplicate playwright, so it went, along with its enablement
  keys. Hook commands in `settings.json` now use `~/.claude/…`,
  because the absolute paths named the account and would break for any other user. That
  relies on shell form: an exec-form hook (`args`) runs without a shell, so `~` would
  stay literal, and a hook that cannot start is a non-blocking error — a guard would
  fail open.
- **The retired agents' memories were triaged, not abandoned** (2026-09-24). Since the
  09-09 retirement, 41 memory files had loaded nowhere. Each lesson went where it has to
  load:
  - Java conventions and verification discipline into `rules/java.md`, about 30 lines.
  - Placement rules into `hexagonal-ddd-java` and `java-observability`.
  - Two lines into `rules/shell.md` and one into `rules/frontend.md`.
  - Three cross-project preferences into CLAUDE.md.
  - Project-bound lessons into the (untracked) project memories.
  - One review lens into the reviewer's own memory.

  Covered and stale ones were deleted: restore on evidence, from an archive outside this
  repo. Simon settled two conflicts:
  - **AAA markers:** see the comment-doctrine entry.
  - **The service floor:** controllers never touch repositories, and reference-data CRUD
    is `controller → service → repository` with no ports. The skills had said "flat
    controller → repository", and a retired memory contradicted them.

  The migration had also dropped a qualifier: prose is out of scope for the delegated
  skill dimensions, not for review. Load-bearing docs go through `code-reviewer` again.
- **claude.ai plugin sync is off in Claude Code; the connector policy is private**
  (2026-09-24). Nine plugins enabled on the claude.ai account synced into every session:
  91 skills and about 80 MCP servers. The skill listing is capped at 1% of the context
  window, so it overflowed and cut descriptions starting with the least-used skills,
  including the Anthropic document skills. In a Java repo, Skills cost 9.9k of the 33.2k
  tokens at session start. `syncClaudeAiPlugins: false` keeps them on claude.ai and in
  Cowork; synced *skills* (`syncClaudeAiSkills`) stay on. The claude.ai connectors stay
  available, but ask rules on their outbound, hard-to-undo tools and one denied connector
  live in machine-level managed settings, never in this public repo. There are 28 ask
  rules as of 2026-09-26, up from 9, re-derived from the connectors' tool lists that day.
- **Rules load by repo type at SessionStart** (2026-09-24). The open question — does a
  path-scoped rule fire when a file is read through Bash? — was answered from the
  transcripts, and the answer was no:
  - Only the Read tool triggers a load. Two sessions made eight Edit/Write calls each on
    `.java` files and never got the rule.
  - Auto mode reads through `cat` and `sed`. After the architect's retirement,
    `rules/java.md` reached 3 of 7 Java-editing main sessions. The self-review loop it
    prescribes ran in 2 of those 3 and in 0 of the other 4 (5 of 9 before the retirement).
  - Of the loads that did happen, 37 of 40 landed in subagents, whose context never
    reaches the main session.

  `hooks/session-rules.sh` now injects `java.md` or `frontend.md` when the repo is Java
  or React/Next, which is deterministic and costs nothing elsewhere. The `paths:`
  frontmatter stays as a fallback.

  Rejected alternatives:
  - The rules back in CLAUDE.md: every session pays for them.
  - A skill: model-invoked, the same non-determinism.

  `shell.md` lost its `paths:` and loads everywhere (~770 tokens), because scripts appear
  in any repo. A "read this first" pointer would have been as unreliable as a skill.
  `hooks/log-instructions.sh` logs every load, so step 9 of the fix plan measures the
  change instead of assuming it.
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
  blocking it up to eight times achieved nothing. *Superseded 2026-09-27:* the matcher is
  now an allowlist of editing agents, forks excepted; see that entry.
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
  *Measured 2026-09-24:* the retirement was due for review after two weeks. A transcript
  audit over 2026-09-09 to 09-24 stood in for the weekly snapshots first planned. The
  retirement stands. What came back was loading, not agents: the SessionStart rule
  injection and the memory triage, both above.
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
  its comment density. *Amended 2026-09-24:* test phase markers (`// Arrange`,
  `// Act`, `// Assert`, `// Act + Assert`) are the one always-on exception. They were
  Simon's convention all along, but they were recorded only in the retired architect's
  memory, so the 08-11 cleanup stripped them from the templates too. Both halves carry
  the exception now, and the templates' 23 test methods are marked again. Simon also
  settled one carve-out: a repo whose tests already label phases with comments in another
  vocabulary (`// given` / `// when` / `// then`) keeps its vocabulary. Spacing and
  BDD-named APIs do not count.
- **Reviewers hold conditional memory-write access** (2026-07-08, superseding the
  memory-file half of a 2026-04-23 read-only rule). The April rule conflated "don't
  modify the reviewed artifact" — still absolute — with "don't keep your own notebook",
  which froze the reviewer's learning loop. The risk it actually guarded against stays
  blocked by the loop-context ban above.

## Known open questions

- **Test-running discipline**: the reviewer can run tests, but the invoking session is
  responsible for green tests before invocation. Whether the reviewer re-runs them is
  non-deterministic. Acceptable; revisit if review latency becomes a concern.
- *Answered 2026-09-24 — see the decision log:* path-scoped rules do not fire on a
  Bash read, nor on Edit/Write; only the Read tool triggers them.
- *Answered 2026-09-27, CLI 2.1.283:* a resumed session carries one copy of each
  injected rule, not two. `session-rules.sh` runs again with `source: "resume"`, but the
  resume writes no second injection record to the transcript. The resumed turn's prompt
  was 35 tokens larger than the first turn's: the first reply plus the second prompt. A
  second copy of the Java rule would have added about 2k. Which copy survives, the
  original or the fresh one, was not measured. Either way the hook needs no resume guard,
  since a guard that dropped the fresh copy could leave none.
