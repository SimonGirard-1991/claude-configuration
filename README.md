# ~/.claude — config layout

Personal Claude Code configuration. This directory is a git repo; `.gitignore` keeps secrets and ephemeral state out.

## What's tracked

| Path | Purpose |
|---|---|
| `agents/` | Custom subagents: two architect+reviewer pairs (`java-backend-architect`+`code-reviewer`, `frontend-architect`+`frontend-code-reviewer`), `script-engineer` (reusable Bash/Python scripts, zsh config, remote-Linux targets; self-reviews via `code-reviewer`), `discovery-analyst` (delivery scoping — freelance clients and corporate stakeholders — estimates, calibration tier), plus `learning-doc-writer`. Inter-agent contracts live in `AGENTS.md`. |
| `skills/` | User-scope skills: `hexagonal-ddd-java`, `hexagonal-module-bootstrap`, five `java-*` skills (testing-strategy, observability, reliability-messaging, performance-patterns, security-baseline), and `client-comms` (client-facing register, five message structures, French business conventions). |
| `hooks/` | Hook scripts wired via `settings.json`: `bash-guard.py` (PreToolUse on Bash — ask on force-push/reset --hard/git clean/secrets access, deny catastrophic `rm -r`), `rtk-rewrite.sh` (PreToolUse on Bash — forwards rtk's command rewrite, strips its auto-allow; see § rtk below), `format-on-edit.sh` (PostToolUse — repo-local prettier, only when the repo has a prettier config; Java/spotless deliberately not hooked, too slow per edit), `validate-agent-contracts.sh` (PostToolUse on edits under `agents/` or `AGENTS.md` — automates the AGENTS.md maintenance checklist, exit 2 feeds drift back to the editing session). Tune patterns in the scripts, not in `settings.json`. |
| `plans/` (when non-empty) | Saved implementation plans. Git doesn't track empty dirs, so the folder may not exist on a fresh checkout until a plan lands. Delete plans when done — old plans rot. |
| `.mcp.json` | Project-scope MCP servers (ones anchored to sessions started in `~/.claude/`). |
| `settings.json` | User-scope settings: permission allow/ask/deny lists (deny covers `.env*`/`.envrc`/`.credentials.json` reads+edits; ask covers `.pem`/ssh-key reads), hook wiring, model/effort defaults, env, plugin enablement. Contains no secrets — safe to track. Note: pre-approved session dirs (e.g. the scratchpad) can bypass deny rules — they protect real project/workspace paths. |
| `CLAUDE.md` | Cross-project notes loaded into **every** session — deliberately kept to a two-bullet minimum (rtk transparency + truncation-marker recovery). Anything project-specific still belongs in that project's own `CLAUDE.md`. |
| `RTK.md` | Vendor template owned by `rtk init -g`. **Not** imported into context (CLAUDE.md carries a trimmed note instead); kept on disk so rtk's idempotency check recognizes its install. |
| `README.md` | This file. |

## What's NOT tracked (gitignored)

`agent-memory/` (persistent per-agent memory — `MEMORY.md` index + entries; personal calibration data, stays local), `settings.local.json`, `projects/`, `sessions/`, `history.jsonl`, `backups/`, `todos/`, `tasks/`, `cache/`, `debug/`, `file-history/`, `paste-cache/`, `shell-snapshots/`, `telemetry/`, `plugins/` (all of it — `installed_plugins.json` is derived state whose recorded SHAs churn on every commit; plugin *enablement* is tracked via `settings.json`), credentials, `.env*`.

## MCP servers — where they actually live

MCP config is split across two files. Track both when troubleshooting a missing tool.

### `~/.claude/.mcp.json` (this repo, tracked)
- `playwright` — browser automation via `@playwright/mcp`.

### `~/.claude.json` (user home, NOT tracked, not in this repo)
Added via `claude mcp add --scope user`. Currently holds:
- `context7` — `@upstash/context7-mcp`, library docs lookup. Used by all agents except `discovery-analyst` (no library-docs need there).
- `brave-search` — `@brave/brave-search-mcp-server`, web search. Used by `java-backend-architect`, `frontend-architect`, `learning-doc-writer`, `script-engineer`, and `discovery-analyst`.

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

All agents follow a strict "default is not save" policy — memory is for things that would change behavior in a *future, different* conversation. Project-specific facts belong in the project's `CLAUDE.md`, not in user-scope memory. See the "Persistent Agent Memory" section in each agent file. Reviewer memory writes are gated by invocation context: invoked directly by the user they save their own memories; inside a self-review loop they end the review with a **Proposed memory** note and the architect records it on user approval (see `AGENTS.md` § Decisions).

## Top-level `CLAUDE.md`

This file was deliberately absent until 2026-07 (per-project `CLAUDE.md` keeps conventions scoped; the old rule was "revisit if genuinely cross-project preferences emerge"). That condition fired with rtk: the hook applies to every session, so the two notes about it are genuinely cross-project. Keep the file minimal — every line costs tokens in every session on this machine.

## rtk (token-compressing CLI proxy)

`brew install rtk`. The PreToolUse hook `hooks/rtk-rewrite.sh` pipes each Bash command through `rtk hook claude` and forwards **only** the rewrite (`updatedInput`) as a constructed minimal object — never rtk's `permissionDecision: "allow"` (upstream auto-allows everything it can rewrite, incl. `git push`/`curl`) nor any future field. Permission authority stays with `settings.json` rules and `bash-guard.py`; because Claude Code evaluates permission rules against the *rewritten* command, `settings.json` carries `Bash(rtk ...)` mirror entries kept 1:1 with rtk's actual rewrites (probe with `rtk hook check "<cmd>"`). Paths in the script are pinned on purpose — npm publishes an unrelated `rtk` that a global install would let shadow the Homebrew one, and hooks are spawned by Claude Code rather than a login shell, so they cannot assume a profile was read.

Out-of-repo state to know about (`~/Library/Application Support/rtk/`, dir chmod 700):

- `config.toml` — `[hooks] exclude_commands = ["git diff", "npm run lint"]` (prefix match). `git diff` stays uncompressed because review agents treat the diff as ground truth and rtk truncates large diffs; `npm run lint` because its rewrite target `rtk lint` (a direct ESLint proxy, arbitrary args) is broader than the allowlisted npm script. **If you change `exclude_commands` or add Bash allowlist entries, re-sync the mirrors.**
- `tee/` — on command *failure* rtk persists the full unfiltered output (max 20 files × 1 MB) as the recovery path behind its compression. Contents are whatever the failing command printed — treat like shell history, purge if a secret ever lands there.
- `history.db` — command records pooled across **all** projects; `rtk gain` reads it (not allowlisted, prompts — cross-project paths would otherwise leak into any session's transcript).

Re-running `rtk init -g` re-adds an `@RTK.md` import to `CLAUDE.md` and its own raw `rtk hook claude` settings entry — decline both and keep the wrapper.
