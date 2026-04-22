# Agents — inter-agent contracts and maintenance notes

This file documents the contracts between agents in `~/.claude/agents/`.
Its primary audience is the human maintainer (you), to avoid silent drift
when editing one agent without remembering what the other one assumes.

`AGENTS.md` is a recognized convention (originated with OpenAI/Codex, now
honored by several agentic tools including Claude Code) — assume this file
may be auto-loaded into agent context. Keep the contents safe to load:
factual contract notes, no secrets, no private commentary.

Edit this file whenever you change a contract surface (output format,
invocation protocol, expected inputs) of any agent that another agent
invokes.

---

## Agents in this setup

| Agent | Role | Invoked by |
|---|---|---|
| `java-backend-architect` | Staff-level Java backend architect: design, implement, review Java code. | User directly, or auto-routed by the main assistant based on the agent's `description`. |
| `code-reviewer` | Staff-level code reviewer: read-only review of a diff. | `java-backend-architect` (Self-Review Loop) via the `Task` tool, or user directly. |

---

## Contract between `java-backend-architect` and `code-reviewer`

- **Reviewer receives**: diff scope (paths or git range), change summary, calibration, project conventions (via `CLAUDE.md`).
- **Reviewer returns**: issues categorized 🔴/🟡/🔵, final verdict ✅/⚠️/🔴.
- **Architect iterates** on 🔴 and 🟡; judges 🔵 on merit.
- **Cap**: 3 iterations, then escalate to user.

### Contract surfaces (break these and the other side breaks silently)

1. **Severity taxonomy**: 🔴 Critical, 🟡 Important, 🔵 Suggestion.
   Defined in `code-reviewer` under "Identify issues by severity".
   Consumed by `java-backend-architect` under "Self-Review Loop → Read the verdict".

2. **Verdict taxonomy**: ✅ Looks good, ⚠️ Needs minor changes, 🔴 Needs revision.
   Emitted by `code-reviewer` under "Output Format → Verdict".
   Consumed by `java-backend-architect` under "Self-Review Loop → Read the verdict".

3. **Invocation mechanism**: `Task` tool with `subagent_type: "code-reviewer"`.
   Called from `java-backend-architect` under "Self-Review Loop → Protocol".
   If this name or mechanism changes, update both agents.

4. **Project conventions discovery**: `code-reviewer` picks up project-specific
   conventions via Claude Code's standard `CLAUDE.md` resolution (user scope at
   `~/.claude/CLAUDE.md`, parent directories, and repo root, composed per Claude
   Code's documented precedence). `java-backend-architect` does NOT need to pass
   conventions inline — the reviewer fetches them itself.

### Edge cases worth remembering

- **Verdict ⚠️ with only 🔵 issues**: the architect may return to the user without
  changes, because 🔵 is judged on merit. This is intentional — not a bug.
- **Reviewer invocation failure** (Task error, subagent unavailable, timeout):
  the architect falls back to a structured self-review against its own
  "When Reviewing" checklist and tells the user explicitly that the external
  reviewer was skipped. No retry loop.
- **Override protocol**: the architect is allowed to push back on the reviewer
  when a suggestion conflicts with an explicit decision in the architect's
  prompt (e.g. the reviewer suggests a pattern the architect's prompt explicitly
  refuses — see `java-backend-architect.md` § Boilerplate Philosophy for one
  such standing refusal). When overriding, the architect must state the
  override in the next review prompt so the reviewer doesn't re-raise the same
  point.

---

## Maintenance checklist

When editing `java-backend-architect.md`:
- [ ] If you change how it invokes `code-reviewer`, update the Contract section above.
- [ ] If you change the severity or verdict it consumes, update `code-reviewer.md` to match.
- [ ] If you add a new sub-agent invocation, add the contract here.

When editing `code-reviewer.md`:
- [ ] If you change the output format (severity emojis, verdict labels, section headings
      that the architect parses), update `java-backend-architect.md` and the Contract above.
- [ ] If you change the Freshness protocol or Tool access rules, check that nothing in
      `java-backend-architect.md` assumes the old behavior.
- [ ] If you change the memory path, update that too in the agent prompt.

When editing `AGENTS.md` itself:
- [ ] When adding a new agent, update the Agents table and add a Contract section if it
      is invoked by (or invokes) another agent.
- [ ] When the invocation mechanism changes globally (e.g. `Task` tool renamed or
      replaced), update the Contract section for every affected agent.

---

## Decisions

- **`code-reviewer` is read-only** (decided 2026-04-23). No `Write`, no `Edit`,
  no file mutation of any kind — including memory files, including via `Bash`
  redirects. The reviewer's role is to review, not modify. The `memory: user`
  frontmatter entry stays in the YAML so the harness injects prior memory into
  the reviewer's context for reads.
  - Follow-up (pending): the reviewer prompt's "How to save memories" section
    instructs a `Write` call the agent cannot make and must be stripped or
    converted to read-only guidance. Tracked here until executed in
    `code-reviewer.md`.
  - Caveat: the precise semantics of the `memory: user` frontmatter key are
    *assumed* here to govern memory-context injection for reads only. This
    has not been verified against authoritative Claude Code subagent docs —
    verify before relying on it for anything load-bearing.

---

## Known open questions

- **Test-running discipline**: the reviewer has the ability to run tests, but the
  architect is responsible for ensuring tests pass before invocation. Current
  behavior is non-deterministic (reviewer chooses whether to re-run). Acceptable
  for now; revisit if review latency becomes a concern.
