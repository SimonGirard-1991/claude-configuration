#!/bin/bash
# PostToolUse on Edit|Write: keep README.md honest about what this repo contains.
#
# README is the only document describing this setup that nothing validated, and it
# is therefore the only one that rotted. The four drifts found on 2026-08-13 had
# three mechanical shapes, and those are the three checked here:
#
#   1. A tracked top-level entry README never mentions (scripts/ — the linter and
#      its 412-line fixture suite — had no row at all).
#   2. A hook on disk README never mentions (validate-skill-tree.sh, missing from
#      the day it was registered).
#   3. A path the "What's tracked" table claims, that .gitignore actually excludes
#      (plans/ was listed as tracked and ignored at the same time).
#
# Plus the reverse of 2: a script named in README that no longer exists on disk.
#
# Prose claims are deliberately NOT checked. The fourth drift was README calling
# CLAUDE.md "a two-bullet minimum" when it had five; the fix was deleting the
# brittle claim, not teaching a hook to count bullets. A gate that fires on correct
# content teaches you to route around the gate — same rule as scripts/lint_skills.py.
#
# Known limit, and it is the right one: checks 1 and 3 read `git ls-files`, so a new
# directory is only demanded of README once something in it is tracked. README
# documents what is tracked; an untracked scratch directory owes it nothing.
#
# CLAUDE_CONFIG_DIR / CLAUDE_README override for testing.

ROOT="${CLAUDE_CONFIG_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
README="${CLAUDE_README:-$ROOT/README.md}"

f=$(/usr/bin/jq -r '.tool_input.file_path // empty' 2>/dev/null)
case "$f" in
  "$ROOT"/*) ;;
  *) exit 0 ;;
esac

# A hook that disables itself in silence is worse than no hook: settings.json still
# advertises the gate while drift accumulates. Every bail-out below says so.
if [ ! -f "$README" ]; then
  printf 'readme hook: %s not found; README checks are OFF\n' "$README" >&2
  exit 1
fi
if ! git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  printf 'readme hook: %s is not a git repo (or git is missing); README checks are OFF\n' \
    "$ROOT" >&2
  exit 1
fi

errs=""
add() { errs="${errs}README DRIFT: $1"$'\n'; }

# The inventory is the table, not the whole file. Matching anywhere in README would
# let a passing mention elsewhere — "scripts/lint_skills.py" inside the hooks row —
# stand in for the row the entry is owed.
# shellcheck disable=SC2016  # the backticks are markdown, not command substitution
claimed=$(awk '/^## What.s tracked/{f=1; next} /^## /{f=0} f' "$README" \
          | sed -n 's/^| *`\([^`]*\)`.*/\1/p')

while IFS= read -r entry; do
  [ -n "$entry" ] || continue
  if [ -d "$ROOT/$entry" ]; then needle="$entry/"; else needle="$entry"; fi
  printf '%s\n' "$claimed" | grep -qxF -- "$needle" \
    || add "'$needle' is tracked at the top level but the \"What's tracked\" table omits it"
done < <(git -C "$ROOT" ls-files | awk -F/ '{print $1}' | sort -u)

for h in "$ROOT"/hooks/*; do
  [ -f "$h" ] || continue
  b=$(basename "$h")
  grep -qF -- "$b" "$README" \
    || add "hooks/$b is wired up but README.md never names it"
done

while IFS= read -r p; do
  [ -n "$p" ] || continue
  if git -C "$ROOT" check-ignore -q "$p" 2>/dev/null; then
    add "README.md lists '$p' under \"What's tracked\", but .gitignore excludes it"
  fi
done <<< "$claimed"

# shellcheck disable=SC2016  # the backticks are markdown, not command substitution
named_scripts=$(grep -oE '`[^`]*\.(sh|py)`' "$README" | tr -d '`' \
                | while IFS= read -r t; do basename "$t"; done | sort -u)

while IFS= read -r b; do
  [ -n "$b" ] || continue
  [ -f "$ROOT/hooks/$b" ] || [ -f "$ROOT/scripts/$b" ] \
    || add "README.md names '$b', which is in neither hooks/ nor scripts/"
done <<< "$named_scripts"

if [ -n "$errs" ]; then
  printf '%s' "$errs" >&2
  printf 'README.md describes this repo and nothing else validates it. Fix the drift above, or if README is right and the repo is wrong, fix the repo.\n' >&2
  exit 2
fi
exit 0
