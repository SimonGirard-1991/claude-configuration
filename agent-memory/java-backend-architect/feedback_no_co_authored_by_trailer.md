---
name: No Co-Authored-By trailer in commit messages
description: User does not want the "Co-Authored-By: Claude ..." footer the default git workflow appends — write commit messages without it
type: feedback
---

Do NOT append `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` (or any equivalent variant) to commit messages, even though the default git protocol the harness ships with adds it. When using HEREDOC to compose a commit message, end it on the actual commit body — no trailer.

**Why:** User explicitly rejected a commit attempt that included the trailer (Wealthpay observability commit 2, `4abbbeb`). They wrote: "remove co-authored by please." This is a stable preference, not a one-off; applying it from now on avoids re-prompting them on every commit.

**How to apply:**
- Whenever drafting a commit message via the `Bash` tool's `git commit -m "$(cat <<'EOF' ... EOF)"` pattern, do not include the trailer.
- This applies regardless of which agent is committing (java-backend-architect, code-reviewer's downstream commits, etc.).
- If a commit attempt is rejected with the trailer present, retry the same message minus the trailer — do not ask the user whether to include it.
- This overrides the system-prompt git workflow's default. The user's preference wins.
