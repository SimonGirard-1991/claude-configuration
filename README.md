# ~/.claude — config layout

Personal Claude Code configuration. This directory is a git repo; `.gitignore` keeps secrets and ephemeral state out.

## What's tracked

| Path | Purpose |
|---|---|
| `agents/` | Custom subagents: two architect+reviewer pairs (`java-backend-architect`+`code-reviewer`, `frontend-architect`+`frontend-code-reviewer`) plus `learning-doc-writer`. Inter-agent contracts live in `AGENTS.md`. |
| `skills/` | User-scope skills: `hexagonal-ddd-java`, `hexagonal-module-bootstrap`, and five `java-*` skills (testing-strategy, observability, reliability-messaging, performance-patterns, security-baseline). |
| `agent-memory/<agent>/` | Persistent per-agent memory. `MEMORY.md` is the index, siblings hold entries. |
| `hooks/` | Hook scripts wired via `settings.json`: `bash-guard.py` (PreToolUse on Bash — ask on force-push/reset --hard/git clean/secrets access, deny catastrophic `rm -r`), `format-on-edit.sh` (PostToolUse — repo-local prettier, only when the repo has a prettier config; Java/spotless deliberately not hooked, too slow per edit), `validate-agent-contracts.sh` (PostToolUse on edits under `agents/` or `AGENTS.md` — automates the AGENTS.md maintenance checklist, exit 2 feeds drift back to the editing session). Tune patterns in the scripts, not in `settings.json`. |
| `plans/` (when non-empty) | Saved implementation plans. Git doesn't track empty dirs, so the folder may not exist on a fresh checkout until a plan lands. Delete plans when done — old plans rot. |
| `.mcp.json` | Project-scope MCP servers (ones anchored to sessions started in `~/.claude/`). |
| `settings.json` | User-scope settings: permission allow/ask/deny lists (deny covers `.env*`/`.envrc`/`.credentials.json` reads+edits; ask covers `.pem`/ssh-key reads), hook wiring, model/effort defaults, env, plugin enablement. Contains no secrets — safe to track. Note: pre-approved session dirs (e.g. the scratchpad) can bypass deny rules — they protect real project/workspace paths. |
| `README.md` | This file. |

## What's NOT tracked (gitignored)

`settings.local.json`, `projects/`, `sessions/`, `history.jsonl`, `backups/`, `todos/`, `tasks/`, `cache/`, `debug/`, `file-history/`, `paste-cache/`, `shell-snapshots/`, `telemetry/`, `plugins/` (all of it — `installed_plugins.json` is derived state whose recorded SHAs churn on every commit; plugin *enablement* is tracked via `settings.json`), credentials, `.env*`.

## MCP servers — where they actually live

MCP config is split across two files. Track both when troubleshooting a missing tool.

### `~/.claude/.mcp.json` (this repo, tracked)
- `playwright` — browser automation via `@playwright/mcp`.

### `~/.claude.json` (user home, NOT tracked, not in this repo)
Added via `claude mcp add --scope user`. Currently holds:
- `context7` — `@upstash/context7-mcp`, library docs lookup. Used by all five agents.
- `brave-search` — `@brave/brave-search-mcp-server`, web search. Used by `java-backend-architect`, `frontend-architect`, and `learning-doc-writer`.

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

## Why no top-level `CLAUDE.md`?

User-scope `~/.claude/CLAUDE.md` would be loaded into every session regardless of project. Currently unused by design: per-project `CLAUDE.md` keeps conventions scoped to the codebase they apply to. Revisit if genuinely cross-project preferences emerge (e.g. global commit-message style, preferred tone).
