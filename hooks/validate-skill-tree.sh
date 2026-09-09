#!/bin/bash
# Lints the skill tree when a file under skills/ or an agent prompt changes.
# On certain findings: exit 2 with them on stderr, which Claude Code feeds back
# to whichever session made the edit so it can fix the drift in-turn.
#
# Two calling conventions. With no arguments it reads a hook payload on stdin and
# takes `.tool_input.file_path` — the PostToolUse shape. With arguments it lints
# those paths instead, which is how hooks/on-stop-validate.sh drives it over a
# turn's whole changed set. Multiple paths in one skill collapse to one lint run:
# --scope is per skill, and repeating it would repeat every finding.
#
# Three rules keep this gate honest, all learned the hard way:
#
#   1. Block only on the linter's ERROR tier. Its WARN tier is heuristic and
#      fires on ordinary prose; blocking there teaches sessions to route around
#      the hook. --quiet drops warnings entirely.
#   2. Scope to the edited skill (--scope). Linting the whole tree hands a
#      session drift it did not cause and cannot fix from its own diff.
#   3. Never block on the linter's own breakage. Exit 3 means findings; anything
#      else non-zero means the linter crashed or was misinvoked, which is
#      reported but must not stop the edit.
#
# --transient-ok downgrades the map checks, because adding a reference file is
# unavoidably a two-file edit and the intermediate state is not a defect. That is a
# statement about *when* the check runs, so the flag follows the calling convention:
# mid-turn (stdin, PostToolUse) it applies; over a finished turn's changed set
# (arguments, from on-stop-validate.sh) it does not, because by then the second half
# of the edit either landed or the route really is dangling. Passing it in both modes
# would leave the map checks permanently unreachable.
#
# The linter's checks are covered by scripts/test_lint_skills.py. If you add a
# check, add its fixture test first — an untested check can silently match
# nothing while the tool reports success.
#
# CLAUDE_SKILLS_DIR / CLAUDE_AGENTS_DIR / CLAUDE_PYTHON override for testing.

ROOT="${CLAUDE_CONFIG_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SKDIR="${CLAUDE_SKILLS_DIR:-$ROOT/skills}"
AGDIR="${CLAUDE_AGENTS_DIR:-$ROOT/agents}"
LINTER="${CLAUDE_SKILL_LINTER:-$ROOT/scripts/lint_skills.py}"

# A hook that disables itself in silence is worse than no hook: settings.json
# still advertises the gate while drift accumulates. Every bail-out below says so.
PY="$CLAUDE_PYTHON"
if [ -z "$PY" ]; then
  for cand in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    [ -x "$cand" ] && { PY="$cand"; break; }
  done
fi
[ -n "$PY" ] || PY=$(command -v python3 2>/dev/null)
if [ -z "$PY" ]; then
  printf 'skill-tree hook: no python3 found; skill-tree linting is OFF\n' >&2
  exit 1
fi

transient=(--transient-ok)
if [ "$#" -gt 0 ]; then
  candidates=("$@")
  transient=()
else
  payload=$(cat)
  candidates=()
  while IFS= read -r line; do
    [ -n "$line" ] && candidates+=("$line")
  done < <(printf '%s' "$payload" | "$PY" -c \
    'import json,sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("file_path", "") or "")
except Exception:
    print("")' 2>/dev/null)
fi
[ "${#candidates[@]}" -gt 0 ] || exit 0

# One --scope per skill: the linter scopes to the skill containing the path, so two
# edited files in one skill would otherwise print the same findings twice.
scopes=()
seen=$'\n'
for f in "${candidates[@]}"; do
  case "$f" in
    "$SKDIR"/*) scope="$SKDIR/$(printf '%s' "${f#"$SKDIR"/}" | cut -d/ -f1)" ;;
    "$AGDIR"/*.md) scope="$f" ;;
    *) continue ;;
  esac
  case "$seen" in
    *$'\n'"$scope"$'\n'*) continue ;;
  esac
  seen="${seen}${scope}"$'\n'
  scopes+=("$scope")
done
[ "${#scopes[@]}" -gt 0 ] || exit 0

if [ ! -f "$LINTER" ]; then
  printf 'skill-tree hook: linter not found at %s; skill-tree linting is OFF\n' \
    "$LINTER" >&2
  exit 1
fi

findings=""
broke=""
for scope in "${scopes[@]}"; do
  out=$("$PY" "$LINTER" --skills-dir "$SKDIR" --agents-dir "$AGDIR" \
        --scope "$scope" ${transient[@]+"${transient[@]}"} --quiet 2>&1)
  case "$?" in
    0) ;;
    3) findings="${findings}${out}"$'\n' ;;
    *) broke="${broke}skill-tree linter did not run for ${scope}:"$'\n'"${out}"$'\n' ;;
  esac
done

if [ -n "$findings" ]; then
  printf '%s' "$findings" >&2
  printf 'Skill-tree lint failed. Fix the findings above, or if the rule itself is wrong, change scripts/lint_skills.py and add a fixture to scripts/test_lint_skills.py.\n' >&2
  exit 2
fi

# Misinvocation or an uncaught exception. Visible, never blocking.
if [ -n "$broke" ]; then
  printf '%s' "$broke" >&2
  exit 1
fi
exit 0
