# ~/.claude — config layout

Personal Claude Code configuration. This directory is a git repo; `.gitignore` keeps secrets and ephemeral state out.

## What's tracked

| Path | Purpose |
|---|---|
| `agents/` | Custom subagents, both `model: inherit`: `code-reviewer` (read-only staff review of a diff) and `learning-doc-writer` (pandoc-ready learning docs). Maintainer notes and the decision log live in `AGENTS.md`. The four architect agents were retired 2026-09-09 — see that file. |
| `skills/` | User-scope skills: `hexagonal-ddd-java`, `hexagonal-module-bootstrap`, five `java-*` skills (testing-strategy, observability, reliability-messaging, performance-patterns, security-baseline), `client-comms` (client-facing register, five message structures, French business conventions), and `scoping` (`disable-model-invocation`, invoked as `/scoping <brief>` — discovery questions, out-of-scope lists, three-point estimates, calibration tier). |
| `rules/` | User-scope path-scoped rules (`~/.claude/rules/*.md` with `paths:` frontmatter): `java.md` (stack conventions, delegated `java-*`/`hexagonal-*` skills, the post-change verification protocol) and `shell.md` (the four hard script rules, bash 3.2 portability floor, zsh dialect) and `frontend.md` (React 19 / Next 15 App Router / TS strict, the fire-on-sight anti-pattern list, WCAG AA checklist, money and date correctness, TanStack cache strategy). `code-reviewer` carries the matching frontend lens, as it does for scripts. They load only when a matching file is read, so they cost nothing in a session that touches neither. |
| `hooks/` | Hook scripts wired via `settings.json`. `bash-guard.py` (PreToolUse on Bash — deny credential-printing commands, environment dumps and catastrophic `rm -r`; ask on force or deleting pushes, `reset --hard`, `git clean`, `rm -r` of the working directory or a `.git`, and shell access to secret files. Judged per command segment, deny beats ask, and it runs on `/usr/bin/python3` so a repo's pyenv pin cannot switch it off). `reviewer-guard.py` (PreToolUse, wired from `code-reviewer`'s own frontmatter rather than `settings.json`, so it runs only while the reviewer does — Edit/Write land only in its memory directory or scratch, and Bash gets a read-only allowlist for `git` plus denials for in-place edits, editors, `eval`, `sh -c`, write-capable `gh`, and redirects or `tee` into the repo; fails closed). **The rest run on `Stop`, not `PostToolUse`**: an `Edit|Write` matcher cannot see file changes made through Bash, and under `defaultMode: auto` the harness steers most edits there — 387 Bash-shaped writes against 263 Edit+Write calls over the fortnight before the switch. A Stop hook reads `git status --porcelain -z -uall`, so it sees the turn's result whatever tool produced it, untracked files included. `on-stop-validate.sh` (Stop + SubagentStop — scoped to this repo; drives `validate-skill-tree.sh` and `validate-readme.sh` over the changed set, exit 2 feeds findings back). `validate-skill-tree.sh` (runs `scripts/lint_skills.py` scoped to each changed skill, blocking on its ERROR tier only). `validate-readme.sh` (checks this file against the repo: every tracked top-level entry and every hook is named here, and nothing this table claims is gitignored). Both take paths as arguments for that, and still read a PostToolUse payload on stdin when called with none. `format-on-stop.sh` (Stop — repo-local prettier over the changed set in one invocation, only when the repo has a prettier config; Java/spotless deliberately not hooked, too slow to sit in a turn; never blocks). `sonar-gate-on-stop.sh` (Stop — runs `scripts/sonar-gate.sh` so a turn cannot end with new Sonar findings; inert unless the repo has a `.sonar-gate` file. Trigger, suppression scan and findings filter all read one file set — `git diff` against the fork point plus `ls-files --others` — so it never blocks on a file it did not read, nor on pre-existing findings in files the turn never touched. Blocks on unjustified `NOSONAR`/`@SuppressWarnings`; a reason on the same line passes and is echoed for the hand-back. Never boots the container: a stopped SonarQube reports "checks are OFF" rather than passing silently). Tune patterns in the scripts, not in `settings.json`. |
| `scripts/` | Repo tooling: `lint_skills.py` (the skill-tree linter behind `validate-skill-tree.sh`), `test_lint_skills.py` (its fixture suite — add the fixture before the check, or a check can silently match nothing while reporting success), `test_hooks.py` (black-box fixture tables for the hooks, pinning what each must catch and what it must let through; `CLAUDE_BASH_GUARD`-style overrides test a candidate before it replaces a live guard), and `sonar-gate.sh` (runs the real Sonar analyzers over a Maven project against a local SonarQube container; the oracle behind `sonar-gate-on-stop.sh`, also usable by hand — `--facets` prints the rule distribution, which is how the authoring rules in `java-testing-strategy` get refreshed from evidence, and `--files` restricts the findings, the count and the exit status to a list of repo-relative paths). |
| `.mcp.json` | Project-scope MCP servers (ones anchored to sessions started in `~/.claude/`). |
| `settings.json` | User-scope settings: permission allow/ask/deny lists (deny covers `.env*`/`.envrc`/`.credentials.json` reads+edits; ask covers `.pem`/ssh-key reads), hook wiring, model/effort defaults, env, plugin enablement. Contains no secrets — safe to track. Note: pre-approved session dirs (e.g. the scratchpad) can bypass deny rules — they protect real project/workspace paths. |
| `CLAUDE.md` | Cross-project notes loaded into **every** session — kept deliberately short, because every line costs tokens in every session on this machine. Anything project-specific still belongs in that project's own `CLAUDE.md`. |
| `AGENTS.md` | Maintainer notes: the two agents, the reviewer memory protocol, and the dated decision log. Claude Code reads `CLAUDE.md`, not this — nothing here loads into a session. |
| `.gitignore` | An allowlist: `/*` ignores every top-level entry and `!/` lines re-admit the tracked ones, so state Claude Code adds beside the config stays out by default. Secret-file patterns (`.env*`, `*.token`, `.credentials.json`) still apply inside tracked directories. Add a tracked top-level entry and it needs both a `!/` line and a row in this table — `validate-readme.sh` enforces the row. |
| `README.md` | This file. |

## What's NOT tracked (gitignored)

Everything the table above does not name. The ones worth knowing: `agent-memory/` (persistent per-agent memory — `MEMORY.md` index + entries; personal calibration data, stays local), `plans/` (saved implementation plans — local working state; delete them when done, old plans rot), `settings.local.json`, `projects/` (transcripts and per-project auto-memory), `plugins/` (all of it — `installed_plugins.json` is derived state whose recorded SHAs churn on every commit; plugin *enablement* is tracked via `settings.json`), `skills/synced/` (skills synced from claude.ai — Anthropic-licensed, never republish), `uploads/` (images pasted into sessions), `logs/`, credentials, `.env*`. The remote is public: treat anything that is not in the table as private.

## MCP servers — where they actually live

MCP config is split across two files. Track both when troubleshooting a missing tool.

### `~/.claude/.mcp.json` (this repo, tracked)
- `playwright` — browser automation via `@playwright/mcp`.

### `~/.claude.json` (user home, NOT tracked, not in this repo)
Added via `claude mcp add --scope user`. Currently holds:
- `context7` — `@upstash/context7-mcp`, library docs lookup. Allowed to both agents.
- `brave-search` — `@brave/brave-search-mcp-server`, web search. Allowed to `learning-doc-writer`. Kept over the built-in `WebSearch` by decision 2026-09-09, though the agents that leaned on it hardest are retired — revisit if `/usage` shows no attribution.

Agents reference these via `mcp__context7__*` / `mcp__brave-search__*` in their `tools:` frontmatter — the allowlists are not uniform, so check the specific agent when a tool appears missing. If a pattern stops matching anything at all, the server itself may have been removed or renamed in `~/.claude.json`.

### Enablement
`~/.claude/.claude/settings.local.json` controls which project-scope MCP servers are enabled per directory (`enabledMcpjsonServers`, `enableAllProjectMcpServers`).

## Secrets

- `BRAVE_API_KEY` lives in the **macOS Keychain** (source of truth). A shell rc (`~/.zshenv` / `~/.zshrc`) reads it into the environment at shell startup, e.g.:
  ```sh
  export BRAVE_API_KEY="$(security find-generic-password -s BRAVE_API_KEY -w)"
  ```
  The brave-search MCP server launches via `npx` with no `env` override in `~/.claude.json`, so it inherits the shell env of whatever spawned the Claude process. Net effect: Keychain → shell → Claude → MCP.
- Never put the key value in `settings.json`, `.mcp.json`, `~/.claude.json`, or any other file on disk. If you wire env through an MCP config block, use variable reference only (`"env": {"BRAVE_API_KEY": "${BRAVE_API_KEY}"}`) — never the literal value.
- Rotate in Keychain (`security add-generic-password -U -s BRAVE_API_KEY -a $USER -w <new>`); next shell spawn picks it up. No config edits needed.

## Agent memory policy

Both agents set `memory: user`, so Claude Code injects the generic memory instructions and the `MEMORY.md` index itself — the agent files carry only what is specific to this setup. The standing policy is "default is not save": memory is for things that would change behavior in a *future, different* conversation. Project-specific facts belong in the project's `CLAUDE.md`, not in user-scope memory. Reviewer writes are gated by invocation context — invoked directly by the user it saves its own memories; inside a self-review loop it ends with a **Proposed memory** note that the invoking session records only on user approval (see `AGENTS.md` § Reviewer memory protocol).

## Top-level `CLAUDE.md`

This file was deliberately absent until 2026-07 (per-project `CLAUDE.md` keeps conventions scoped; the old rule was "revisit if genuinely cross-project preferences emerge"). What earns its place today is the comment doctrine (decided 2026-08-11, `AGENTS.md` surface 8): it is language-agnostic, it applies to every session on this machine, and removing it measurably brings the over-commenting back. Keep the file minimal — every line costs tokens in every session, and anything derivable from the code does not belong here.
