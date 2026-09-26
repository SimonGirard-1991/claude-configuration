#!/bin/bash
# Stop / SubagentStop: re-check this repo's own invariants over everything the turn
# changed, not over what it changed through Edit|Write.
#
# The PostToolUse ancestors of these checks matched on `Edit|Write` and therefore
# missed most of the edits that actually happened: under `defaultMode: auto` the
# harness steers file changes into Bash (heredocs, `sed -i`, short scripts), and in
# the fortnight before this hook existed those outnumbered Edit+Write calls roughly
# 387 to 263. A Stop hook sees the result regardless of which tool produced it.
#
# The changed set comes from `git status --porcelain`, so it covers untracked files
# too — a new skill reference is exactly the case the old hooks were blindest to.
#
# Scoped to ~/.claude and nothing else: these are checks about *this* repo's layout,
# and running them against a session in someone's project repo would be noise.
#
# stop_hook_active is deliberately not an exit: a session that cannot fix the drift
# would otherwise learn that ending the turn twice clears the gate. Claude Code caps
# the loop at 8 blocks, which is the real backstop.
#
# CLAUDE_CONFIG_DIR overrides for testing.

ROOT="${CLAUDE_CONFIG_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

payload=$(cat)
cwd=$(printf '%s' "$payload" | /usr/bin/jq -r '.cwd // empty' 2>/dev/null)
[ -n "$cwd" ] || cwd="$PWD"

repo=$(cd "$cwd" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)
[ -n "$repo" ] || exit 0
[ "$repo" -ef "$ROOT" ] 2>/dev/null || exit 0

# -z, not plain --porcelain: paths with spaces or non-ASCII come back C-quoted
# otherwise, and a quoted path matches none of the prefixes below. Rename entries
# emit their old path as an extra record, which is harmless — both halves are repo
# paths and the checks only care which directory a path falls in.
changed=()
while IFS= read -r -d '' rec; do
  case "$rec" in
    ??\ *) changed+=("$ROOT/${rec#???}") ;;
    *) [ -n "$rec" ] && changed+=("$ROOT/$rec") ;;
  esac
done < <(git -C "$ROOT" status --porcelain -z --untracked-files=all 2>/dev/null)
[ "${#changed[@]}" -gt 0 ] || exit 0

errs=""
broke=""

run() { # $1 hook script, rest: paths
  local hook="$ROOT/hooks/$1"; shift
  [ -x "$hook" ] || {
    broke="${broke}on-stop-validate: hooks/$(basename "$hook") missing or not executable; that check is OFF"$'\n'
    return
  }
  local out; out=$("$hook" "$@" 2>&1); local st=$?
  case "$st" in
    0) ;;
    2) errs="${errs}${out}"$'\n' ;;
    *) broke="${broke}${out}"$'\n' ;;
  esac
}

run validate-skill-tree.sh "${changed[@]}"
run validate-readme.sh "${changed[@]}"
run validate-rules.sh "${changed[@]}"

if [ -n "$broke" ]; then
  printf '%s' "$broke" >&2
fi
if [ -n "$errs" ]; then
  printf '%s' "$errs" >&2
  exit 2
fi
[ -n "$broke" ] && exit 1
exit 0
