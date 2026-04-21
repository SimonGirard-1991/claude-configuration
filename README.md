# ~/.claude — config layout

Personal Claude Code configuration. This directory is a git repo; `.gitignore` keeps secrets and ephemeral state out.

## What's tracked

| Path | Purpose |
|---|---|
| `agents/` | Custom subagent definitions (`code-reviewer`, `java-backend-architect`). |
| `skills/` | User-scope skills (`hexagonal-ddd-java`, `hexagonal-module-bootstrap`). |
| `agent-memory/<agent>/` | Persistent per-agent memory. `MEMORY.md` is the index, siblings hold entries. |
| `plans/` (when non-empty) | Saved implementation plans. Git doesn't track empty dirs, so the folder may not exist on a fresh checkout until a plan lands. Delete plans when done — old plans rot. |
| `.mcp.json` | Project-scope MCP servers (ones anchored to sessions started in `~/.claude/`). |
| `README.md` | This file. |

## What's NOT tracked (gitignored)

`settings.json`, `settings.local.json`, `projects/`, `sessions/`, `history.jsonl`, `backups/`, `todos/`, `tasks/`, `cache/`, `debug/`, `file-history/`, `paste-cache/`, `shell-snapshots/`, `telemetry/`, `plugins/`, credentials, `.env*`.

## MCP servers — where they actually live

MCP config is split across two files. Track both when troubleshooting a missing tool.

### `~/.claude/.mcp.json` (this repo, tracked)
- `playwright` — browser automation via `@playwright/mcp`.

### `~/.claude.json` (user home, NOT tracked, not in this repo)
Added via `claude mcp add --scope user`. Currently holds:
- `context7` — `@upstash/context7-mcp`, library docs lookup. Used by both `java-backend-architect` and `code-reviewer`.
- `brave-search` — `@brave/brave-search-mcp-server`, web search. Used by `java-backend-architect` only.

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

Both agents follow a strict "default is not save" policy — memory is for things that would change behavior in a *future, different* conversation. Project-specific facts belong in the project's `CLAUDE.md`, not in user-scope memory. See the "Persistent Agent Memory" section in each agent file.

## Why no top-level `CLAUDE.md`?

User-scope `~/.claude/CLAUDE.md` would be loaded into every session regardless of project. Currently unused by design: per-project `CLAUDE.md` keeps conventions scoped to the codebase they apply to. Revisit if genuinely cross-project preferences emerge (e.g. global commit-message style, preferred tone).
