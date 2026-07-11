#!/bin/sh
# PreToolUse rewrite for Bash tool calls: RTK token compression, permissions intact.
#
# Pipes the hook payload to rtk and re-emits ONLY a minimal rewrite object:
#   {"hookSpecificOutput":{"hookEventName":"PreToolUse","updatedInput":{...}}}
# The response is CONSTRUCTED, not filtered: anything else rtk emits now or
# later (permissionDecision:"allow" on every rewrite today, a hypothetical
# top-level continue:false tomorrow) never reaches Claude Code. Permission
# authority stays with settings.json rules and bash-guard.py.
#
# Empirically verified on Claude Code + rtk 0.43.0 (2026-07):
# - Permission rules evaluate the REWRITTEN command, so settings.json carries
#   Bash(rtk ...) mirror entries kept 1:1 with rtk's actual rewrites.
#   git diff and npm run lint are excluded from rewriting in rtk's own config
#   (~/Library/Application Support/rtk/config.toml) — see README "rtk" section.
# - All PreToolUse hooks run in parallel on the ORIGINAL input; most
#   restrictive decision wins, so bash-guard.py's ask/deny cannot be bypassed
#   by a rewrite.
# - Paths are pinned deliberately: a PATH-resolved `rtk` can be shadowed (npm
#   publishes an unrelated package named rtk, and the nvm bin dir precedes
#   Homebrew's in the hook PATH); /usr/bin/jq ships with macOS. On a machine
#   where either path is absent the script silently no-ops (fail-open) and
#   commands run unrewritten under normal permission flow.
#
# Fail-open contract (mirrors bash-guard.py): no output + exit 0 = no rewrite.
# rtk absent, garbage output, or a jq error all resolve to that. No inner
# timeout; the hook entry's settings.json timeout (10s) bounds the pipe.

/opt/homebrew/bin/rtk hook claude 2>/dev/null | /usr/bin/jq -c '
  select(.hookSpecificOutput.updatedInput) |
  {hookSpecificOutput: {hookEventName: "PreToolUse",
                        updatedInput: .hookSpecificOutput.updatedInput}}
' 2>/dev/null
exit 0
