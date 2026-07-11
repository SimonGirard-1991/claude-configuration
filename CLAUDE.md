# Cross-project notes

- rtk compresses Bash tool output via a PreToolUse hook (`hooks/rtk-rewrite.sh`) — it rewrites commands for you, so run commands normally; don't hand-prefix `rtk`.
- To recover output cut by a `... (N lines truncated)` marker, re-run the command through `rtk proxy <original command>` (prompts for approval) or Read the underlying files.
