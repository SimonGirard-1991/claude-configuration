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
| `code-reviewer` | Staff-level code reviewer: read-only review of a diff. | `java-backend-architect` and `script-engineer` (Self-Review Loop) via the `Agent` tool, or user directly. |
| `frontend-architect` | Staff-level frontend architect (React 19 / Next.js 15 / TS strict): design, implement, review. | User directly, or auto-routed by the main assistant based on the agent's `description`. |
| `frontend-code-reviewer` | Staff-level frontend reviewer: read-only review of a frontend diff. | `frontend-architect` (Self-Review Loop) via the `Agent` tool, or user directly. |
| `learning-doc-writer` | Produces pandoc-ready learning docs (Markdown → PDF via LuaLaTeX). | User directly. Leaf agent — invokes no other agent and is invoked by none. |
| `script-engineer` | Staff-level toolsmith: reusable personal scripts and CLI tools (Bash/Python), zsh configuration work, remote-Linux-target scripts. | User directly, or auto-routed by the main assistant based on the agent's `description`. |
| `discovery-analyst` | Delivery scoping, freelance and corporate: discovery questions, scoping docs with out-of-scope lists, estimates, scope-change and hard-commitment assessment, calibration tier declaration. | User directly, or auto-routed by the main assistant based on the agent's `description`. Leaf agent — invokes no other agent; loads the `client-comms` skill for sponsor-facing register. |

---

## Contract between architects and their reviewers

Three instances of the same contract: `java-backend-architect` → `code-reviewer`,
`frontend-architect` → `frontend-code-reviewer`, and `script-engineer` → `code-reviewer`
(the java and script pairs share the same reviewer). The surfaces below are identical
for all pairs unless noted; "the architect" / "the reviewer" mean whichever pair is active.

- **Reviewer receives**: diff scope (paths or git range), change summary, calibration, the invocation marker (surface 6), project conventions (via `CLAUDE.md`).
- **Reviewer returns**: issues categorized 🔴/🟡/🔵, final verdict ✅/⚠️/🔴.
- **Architect iterates** on 🔴 and 🟡; judges 🔵 on merit.
- **Cap**: 3 iterations, then escalate to user.

### Contract surfaces (break these and the other side breaks silently)

1. **Severity taxonomy**: 🔴 Critical, 🟡 Important, 🔵 Suggestion.
   Defined in each reviewer under "Identify issues by severity".
   Consumed by each architect under "Self-Review Loop → Read the verdict".

2. **Verdict taxonomy**: ✅ Looks good, ⚠️ Needs minor changes, 🔴 Needs revision.
   Emitted by each reviewer under "Output Format → Verdict".
   Consumed by each architect under "Self-Review Loop → Read the verdict".

3. **Invocation mechanism**: `Agent` tool with `subagent_type: "code-reviewer"`
   (`java-backend-architect`, `script-engineer`) resp. `"frontend-code-reviewer"`
   (`frontend-architect`). Called from each architect under
   "Self-Review Loop → Protocol". If this name or mechanism changes, update both agents.
   - History: the tool was named `Task` until Claude Code v2.1.63 renamed it to
     `Agent` (`Task` remains a documented alias, so the loop never broke). Both
     architects were migrated to the canonical name on 2026-07-08 (frontmatter
     `tools:` and Self-Review Loop text). Nested spawning (subagent → subagent)
     is officially supported: listing `Agent` in a subagent's `tools` enables it,
     per the sub-agents docs.

4. **Project conventions discovery**: reviewers pick up project-specific
   conventions via Claude Code's standard `CLAUDE.md` resolution (user scope at
   `~/.claude/CLAUDE.md`, parent directories, and repo root, composed per Claude
   Code's documented precedence). Architects do NOT need to pass
   conventions inline — the reviewer fetches them itself.

5. **Reviewer memory protocol**: reviewer memory writes are gated by invocation
   context. In the self-review loop (detected via surface 6) the reviewer never
   saves — it may end the review with an optional **Proposed memory** note; the
   architect relays the note verbatim in its hand-back and, on explicit user
   approval, records it unchanged into the reviewer's memory directory
   (`agent-memory/<reviewer>/`: memory file + `MEMORY.md` index line). Invoked
   directly by the user with explicit feedback, the reviewer saves its own
   memories. Ambiguous context fails closed to propose-only.

6. **Invocation marker**: each architect's Self-Review Loop prompt includes the
   line `Invocation: self-review loop, iteration N of 3`. The reviewers' memory
   rules key off it. If the wording changes, update all three architects and both
   reviewers.

7. **Calibration lens line** (script pair only): `script-engineer`'s Self-Review
   Loop prompt includes `Calibration: … apply the standalone-script lens.` (zsh
   variant: `… apply the standalone-script lens, zsh dialect notes.`), which keys
   into the `code-reviewer` section "The standalone-script lens". Rename either
   side and the reviewer silently reviews scripts against service axes instead.
   The java and frontend pairs pass a plain criticality calibration; no lens
   coupling exists there.

### Shared vocabulary (soft coupling, not hook-enforced)

The calibration tier taxonomy — *throwaway / internal tool / production service /
critical financial system* — originates in the reviewers ("Calibrate your bar")
and is emitted by `discovery-analyst` in scoping documents (§ Calibration tier),
so a project's business tier flows into architect/reviewer calibration during the
build. If the reviewer taxonomy is reworded, update `discovery-analyst.md` to
match, or scoping docs stop speaking the tier language the reviewers calibrate
against.

### Edge cases worth remembering

- **Verdict ⚠️ with only 🔵 issues**: the architect may return to the user without
  changes, because 🔵 is judged on merit. This is intentional — not a bug.
- **No invocation marker, ambiguous context**: the reviewer treats it as loop
  context — propose-only, no memory writes. Fail closed.
- **Reviewer invocation failure** (Agent tool error, subagent unavailable, timeout):
  the architect falls back to a structured self-review against its own
  "When Reviewing" checklist and tells the user explicitly that the external
  reviewer was skipped. No retry loop.
- **Override protocol**: the architect is allowed to push back on the reviewer
  when a suggestion conflicts with an explicit decision in the architect's
  prompt (e.g. the reviewer suggests a pattern the architect's prompt explicitly
  refuses — see `java-backend-architect.md` § Boilerplate Philosophy or
  `frontend-architect.md` § "Pushing back on the reviewer" for standing
  refusals). When overriding, the architect must state the
  override in the next review prompt so the reviewer doesn't re-raise the same
  point.

---

## Maintenance checklist

Since 2026-07-08 the mechanical parts of this checklist are enforced by
`~/.claude/hooks/validate-agent-contracts.sh`, a PostToolUse hook that runs on
every edit under `agents/` or to this file and feeds drift back to the editing
session (exit 2). It checks surfaces 1–3, 6, and 7 plus frontmatter sanity; the
judgment items below still need a human. If a contract surface legitimately
changes, update AGENTS.md **and** the validator in the same commit.

When editing `java-backend-architect.md` (same checklist for `frontend-architect.md`
and `script-engineer.md`):
- [ ] If you change how it invokes `code-reviewer`, update the Contract section above.
- [ ] If you change the severity or verdict it consumes, update `code-reviewer.md` to match.
- [ ] If you add a new sub-agent invocation, add the contract here.

When editing `code-reviewer.md` (same checklist for `frontend-code-reviewer.md`):
- [ ] If you change the output format (severity emojis, verdict labels, section headings
      that the architect parses), update `java-backend-architect.md` and the Contract above.
      `code-reviewer` has two architect consumers (`java-backend-architect`,
      `script-engineer`) — check both.
- [ ] If you rename or remove "The standalone-script lens" section, update
      `script-engineer.md`'s calibration line and the validator (surface 7).
- [ ] If you change the Freshness protocol or Tool access rules, check that nothing in
      `java-backend-architect.md` assumes the old behavior.
- [ ] If you change the memory path, update that too in the agent prompt.

When editing `AGENTS.md` itself:
- [ ] When adding a new agent, update the Agents table and add a Contract section if it
      is invoked by (or invokes) another agent.
- [ ] When the invocation mechanism changes globally (e.g. the v2.1.63 `Task` →
      `Agent` rename, migrated here 2026-07-08), update the Contract section for
      every affected agent.

---

## Decisions

- **Reviewers hold conditional memory-write access** (decided 2026-07-08;
  supersedes the memory-file part of the 2026-04-23 decision below). `Write`/`Edit`
  are back in both reviewers' tools, prompt-scoped to their own memory directory
  plus `/tmp` scratch. Saving is gated by invocation context: direct user
  invocation with explicit feedback → the reviewer saves itself; self-review loop
  (marker, surface 6) → propose-only, architect records on user approval
  (surface 5); ambiguous → propose-only. Rationale: the April rule conflated
  "don't modify the reviewed artifact" (still absolute — see "Hard rule: never
  mutate tracked state" in both reviewers) with "don't keep your own notebook",
  which froze the reviewers' learning loop. The risk the April rule actually
  guarded against — architect pushback laundered into reviewer calibration
  without human validation — remains blocked by the loop-context ban.
- **`code-reviewer` is read-only** (decided 2026-04-23; superseded 2026-07-08 for
  memory files by the decision above — still in force for repo, config, and all
  tracked state). Original rule: no `Write`, no `Edit`, no file mutation of any
  kind, including via `Bash` redirects. The `memory: user` frontmatter entry
  stays in the YAML so the harness injects prior memory into the reviewer's
  context.
  - Follow-up history: the "How to save memories" mechanics were stripped to
    read-only guidance on 2026-07-08, then reinstated the same day in conditional
    form when the superseding decision landed.
  - Caveat: the precise semantics of the `memory: user` frontmatter key are
    *assumed* here to govern memory-context injection. This has not been verified
    against authoritative Claude Code subagent docs — verify before relying on it
    for anything load-bearing.

---

## Known open questions

- **Test-running discipline**: the reviewer has the ability to run tests, but the
  architect is responsible for ensuring tests pass before invocation. Current
  behavior is non-deterministic (reviewer chooses whether to re-run). Acceptable
  for now; revisit if review latency becomes a concern.
