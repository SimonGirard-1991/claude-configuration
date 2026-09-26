#!/bin/bash
# InstructionsLoaded: append one line per instruction-file load to logs/rules.jsonl.
#
# The event fires only for CLAUDE.md and rules/*.md files, so other instruction files
# never reach this log: AGENTS.md loads into ~/.claude sessions and leaves no line here.
#
# The event has no decision control and ignores exit codes and output, so the log is the
# hook's only product, and a dead logger shows only as silence. It therefore records
# every load it sees with no matcher, the session_start load of CLAUDE.md included: that
# line per session is the proof the logger is alive, and the path_glob_match lines are
# the rules/*.md fallback loads that session-rules.sh exists to make unnecessary.
#
# CLAUDE_CONFIG_DIR / CLAUDE_RULES_LOG override for testing.

ROOT="${CLAUDE_CONFIG_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG="${CLAUDE_RULES_LOG:-$ROOT/logs/rules.jsonl}"

entry=$(TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)" /usr/bin/jq -c \
  '{ts: env.TS, session_id, cwd, file_path, memory_type, load_reason, globs, trigger_file_path,
    via: "instructions_loaded"}' 2>/dev/null) || exit 0
mkdir -p "$(dirname "$LOG")" 2>/dev/null
printf '%s\n' "$entry" >>"$LOG" 2>/dev/null
exit 0
