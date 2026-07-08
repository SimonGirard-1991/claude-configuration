#!/bin/bash
# PostToolUse on Edit|Write: when a file under ~/.claude/agents/ or AGENTS.md
# changes, re-check the architect<->reviewer contract surfaces documented in
# AGENTS.md. On drift: exit 2 with findings on stderr, which Claude Code feeds
# back to whichever session made the edit so it can fix the drift in-turn.
#
# This automates the "Maintenance checklist" section of AGENTS.md.
# CLAUDE_AGENTS_DIR / CLAUDE_AGENTS_MD overrides exist for testing only.

AGDIR="${CLAUDE_AGENTS_DIR:-/Users/simongirard/.claude/agents}"
AGMD="${CLAUDE_AGENTS_MD:-/Users/simongirard/.claude/AGENTS.md}"

f=$(/usr/bin/jq -r '.tool_input.file_path // empty' 2>/dev/null)
case "$f" in
  "$AGDIR"/*.md|"$AGMD") ;;
  *) exit 0 ;;
esac

errs=""
add() { errs="${errs}CONTRACT DRIFT: $1"$'\n'; }

check_pair() { # $1 architect.md  $2 reviewer.md  $3 reviewer agent name
  local a="$AGDIR/$1" r="$AGDIR/$2"
  [ -f "$a" ] || { add "$1 is missing"; return; }
  [ -f "$r" ] || { add "$2 is missing"; return; }
  grep -q "subagent_type: \"$3\"" "$a" \
    || add "$1 no longer invokes $3 via subagent_type (surface 3)"
  grep -q 'Invocation: self-review loop, iteration N of 3' "$a" \
    || add "$1 lost the invocation marker line (surface 6)"
  grep -q 'Invocation: self-review loop' "$r" \
    || add "$2 no longer references the invocation marker its memory rules key off (surfaces 5/6)"
  local e
  for e in 🔴 🟡 🔵; do
    grep -q "$e" "$a" || add "$1 missing severity $e (surface 1)"
    grep -q "$e" "$r" || add "$2 missing severity $e (surface 1)"
  done
  for e in ✅ ⚠️; do
    grep -q "$e" "$a" || add "$1 missing verdict $e (surface 2)"
    grep -q "$e" "$r" || add "$2 missing verdict $e (surface 2)"
  done
}

check_frontmatter() { # $1 file.md — frontmatter opens and name matches filename
  local file="$AGDIR/$1" base="${1%.md}"
  [ -f "$file" ] || return 0
  [ "$(head -1 "$file")" = "---" ] || add "$1 frontmatter does not start with ---"
  grep -q "^name: \"$base\"" "$file" || add "$1 frontmatter name does not match filename"
}

check_pair java-backend-architect.md code-reviewer.md code-reviewer
check_pair frontend-architect.md frontend-code-reviewer.md frontend-code-reviewer
for m in java-backend-architect.md code-reviewer.md frontend-architect.md \
         frontend-code-reviewer.md learning-doc-writer.md; do
  check_frontmatter "$m"
done
[ -f "$AGMD" ] || add "AGENTS.md is missing"

if [ -n "$errs" ]; then
  printf '%s' "$errs" >&2
  printf 'Contract surfaces are defined in %s — fix the drift, or update AGENTS.md and this validator if the contract itself changed.\n' "$AGMD" >&2
  exit 2
fi
exit 0
