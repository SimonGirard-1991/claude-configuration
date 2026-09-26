#!/bin/bash
# Blocks a turn that leaves rules/java.md or rules/frontend.md too big for
# hooks/session-rules.sh to inline. Over the hook's cap a session gets a pointer instead
# of the rule, and the only sign is a systemMessage in some later session.
#
# The oracle is the real session-rules.sh, run against a throwaway repo fixture, rather
# than a copy of its cap and header here, which could drift from the hook it guards. A
# change to the oracle itself therefore re-checks both rules.
#
# Called by hooks/on-stop-validate.sh with the turn's changed paths; any other path is
# ignored, and a relative one resolves against the working directory. Exit 2 when a rule
# overflows. Exit 1 when the oracle gives no answer or warns, so the check is visibly OFF
# rather than silently green.
#
# CLAUDE_CONFIG_DIR / CLAUDE_SESSION_RULES override for testing.

ROOT="${CLAUDE_CONFIG_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ORACLE="${CLAUDE_SESSION_RULES:-$ROOT/hooks/session-rules.sh}"
JQ=/usr/bin/jq

rules=()
queue() {
  local r
  for r in "$@"; do
    [ -f "$ROOT/rules/$r.md" ] || continue
    case " ${rules[*]} " in
      *" $r "*) continue ;;
    esac
    rules+=("$r")
  done
}

for f in "$@"; do
  case "$f" in
    /*) ;;
    *) f="$PWD/$f" ;;
  esac
  case "$f" in
    "$ROOT/rules/java.md") queue java ;;
    "$ROOT/rules/frontend.md") queue frontend ;;
    "$ROOT/hooks/session-rules.sh") queue java frontend ;;
  esac
done
[ "${#rules[@]}" -gt 0 ] || exit 0

if [ ! -x "$ORACLE" ] || [ ! -x "$JQ" ]; then
  printf 'validate-rules: %s or %s is missing or not executable; the rule-size check is OFF\n' \
    "$ORACLE" "$JQ" >&2
  exit 1
fi

# Templated, because macOS mktemp ignores $TMPDIR and its default directory is closed under
# the Bash sandbox.
fx=$(mktemp -d "${TMPDIR:-/tmp}/validate-rules.XXXXXX") || {
  printf 'validate-rules: cannot create a fixture directory; the rule-size check is OFF\n' >&2
  exit 1
}
trap 'rm -rf "$fx"' EXIT
mkdir "$fx/java" "$fx/frontend"
: >"$fx/java/pom.xml"
printf '{"dependencies":{"react":"*"}}\n' >"$fx/frontend/package.json"

overflow=""
broke=""
for rule in "${rules[@]}"; do
  payload=$(DIR="$fx/$rule" "$JQ" -cn '{cwd: env.DIR, source: "startup", session_id: "validate-rules"}')
  out=$(printf '%s' "$payload" |
    CLAUDE_CONFIG_DIR="$ROOT" CLAUDE_RULES_LOG="$fx/rules.jsonl" "$ORACLE" "$rule" 2>"$fx/err")
  st=$?
  msg=$(printf '%s' "$out" | "$JQ" -r '.systemMessage // empty' 2>/dev/null)
  ctx=$(printf '%s' "$out" | "$JQ" -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)
  if [ "$st" -ne 0 ] || [ -z "$ctx" ]; then
    broke="${broke}validate-rules: session-rules.sh $rule gave no injection (exit $st)${msg:+: $msg} $(head -c 300 "$fx/err")"$'\n'
    continue
  fi
  # The rule's last line reaches the injection only when the whole rule was inlined. The
  # oracle's notice wording is not the signal: rewording it would pass every overflow.
  last=$(awk 'NF { l = $0 } END { print l }' "$ROOT/rules/$rule.md")
  case "$ctx" in
    *"$last"*) [ -z "$msg" ] || broke="${broke}validate-rules: session-rules.sh $rule: $msg"$'\n' ;;
    *) overflow="${overflow}rules/$rule.md is too big to inline at session start${msg:+: $msg}"$'\n' ;;
  esac
done

[ -z "$broke" ] || printf '%s' "$broke" >&2
if [ -n "$overflow" ]; then
  printf '%s' "$overflow" >&2
  printf 'Trim the rule until hooks/validate-rules.sh passes; a session in a matching repo would otherwise start without it.\n' >&2
  exit 2
fi
[ -z "$broke" ] || exit 1
exit 0
