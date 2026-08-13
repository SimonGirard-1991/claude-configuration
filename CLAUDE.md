# Cross-project notes

- rtk compresses Bash tool output via a PreToolUse hook (`hooks/rtk-rewrite.sh`) — it rewrites commands for you, so run commands normally; don't hand-prefix `rtk`.
- To recover output cut by a `... (N lines truncated)` marker, re-run the command through `rtk proxy <original command>` (prompts for approval) or Read the underlying files.

# Code comments

- **The default is none.** A comment earns its place only when the code cannot carry the information — a non-obvious constraint, a rejected alternative, an external quirk, an invariant a reader would otherwise break. Never restate what the code already says.
- If a comment is needed to explain *what* the code does, that's a bug report about the code: rename, extract, or split, then drop the comment. Doc comments (Javadoc/TSDoc/docstrings) are held to the same bar; `--help` text and script header blocks are user-facing documentation and stay.
- Explanation of a change belongs in the reply and the commit message, not in the file.
