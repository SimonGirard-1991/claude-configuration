#!/bin/bash
# Blocks a turn that leaves a body in conventions/ too big for hooks/session-rules.sh to
# inline, or its pointer stub in rules/ broken. Over the hook's cap a session gets a
# pointer instead of the body, and the only sign is a systemMessage in some later session.
#
# A stub is broken when it is missing, has no `paths:` (a rule without one loads in every
# session), does not start with [rule-stub <rule>] (scripts/eval_config.py counts stubs by
# that marker), does not name its body, points at a body that is gone, or passes
# $STUB_CAP characters: it loads natively beside the injected body, so its size is paid
# twice.
#
# It also blocks when the bodies' "### Self-review loop" sections differ, or one is
# missing. That text is shared: each copy runs from its heading to the end of its file, and
# an edit that reaches only one copy is how the loop drifted before.
#
# The oracle is the real session-rules.sh, run against a throwaway repo fixture per body,
# rather than a copy of its cap and header here, which could drift from the hook it guards.
# A change to the oracle itself therefore re-checks every body. fixture() below holds one
# row per body, and a body without a row blocks.
#
# Called by hooks/on-stop-validate.sh with the turn's changed paths; any other path is
# ignored, and a relative one resolves against the working directory. Exit 2 when a body
# overflows or lacks a fixture, a stub is broken, or the loops drift. Exit 1 when the oracle
# gives no answer or warns, so the check is visibly OFF rather than silently green.
#
# CLAUDE_CONFIG_DIR / CLAUDE_SESSION_RULES override for testing.

ROOT="${CLAUDE_CONFIG_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ORACLE="${CLAUDE_SESSION_RULES:-$ROOT/hooks/session-rules.sh}"
JQ=/usr/bin/jq
STUB_CAP=600

# Writes into $2 a repo marker that makes session-rules.sh inject body $1.
fixture() {
  case "$1" in
    java) : >"$2/pom.xml" ;;
    frontend) printf '{"dependencies":{"react":"*"}}\n' >"$2/package.json" ;;
    swift) : >"$2/Package.swift" ;;
    python) : >"$2/pyproject.toml" ;;
    *) return 1 ;;
  esac
}

frontmatter() { awk 'NR == 1 && /^---$/ { f = 1; next } f && /^---$/ { exit } f' "$1"; }
after_frontmatter() { awk 'NR == 1 && /^---$/ { f = 1; next } f && /^---$/ { f = 0; next } !f' "$1"; }
is_stub() { [ -f "$1" ] && after_frontmatter "$1" | head -1 | grep -q '^\[rule-stub '; }

rules=()
queue() {
  local r
  for r in "$@"; do
    [ -f "$ROOT/conventions/$r.md" ] || is_stub "$ROOT/rules/$r.md" || continue
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
    "$ROOT"/conventions/*.md | "$ROOT"/rules/*.md)
      name="${f##*/}"
      queue "${name%.md}"
      ;;
    "$ROOT/hooks/session-rules.sh")
      for body in "$ROOT"/conventions/*.md; do
        [ -f "$body" ] || continue
        name="${body##*/}"
        queue "${name%.md}"
      done
      ;;
  esac
done
[ "${#rules[@]}" -gt 0 ] || exit 0

blocked=""
block() { blocked="${blocked}$1"$'\n'; }

for r in "${rules[@]}"; do
  stub="$ROOT/rules/$r.md"
  if [ ! -f "$stub" ]; then
    block "rules/$r.md is missing: conventions/$r.md needs a stub there that keeps its paths: fallback"
    continue
  fi
  frontmatter "$stub" | grep -q '^paths:' ||
    block "rules/$r.md has no paths:, so it would load in every session"
  text=$(after_frontmatter "$stub")
  case "$text" in
    "[rule-stub $r]"*) ;;
    *) block "rules/$r.md does not start with [rule-stub $r], the marker scripts/eval_config.py counts stubs by" ;;
  esac
  case "$text" in
    *"~/.claude/conventions/$r.md"*) ;;
    *) block "rules/$r.md does not name ~/.claude/conventions/$r.md" ;;
  esac
  [ "${#text}" -le "$STUB_CAP" ] ||
    block "rules/$r.md is ${#text} characters; a stub stays under $STUB_CAP, since it loads beside the injected body"
  [ -f "$ROOT/conventions/$r.md" ] ||
    block "rules/$r.md points at conventions/$r.md, which does not exist"
done

LOOP='### Self-review loop'
loop_of() { awk -v h="$LOOP" 'f; $0 == h { f = 1 }' "$1"; }

drift=""
ref=""
ref_loop=""
for body in "$ROOT"/conventions/*.md; do
  [ -f "$body" ] || continue
  name="conventions/${body##*/}"
  loop=$(loop_of "$body")
  case "$loop" in
    *"Invocation: self-review loop"*) ;;
    *)
      drift="${drift}$name has no '$LOOP' section at its end"$'\n'
      continue
      ;;
  esac
  if [ -z "$ref" ]; then
    ref="$name"
    ref_loop="$loop"
  elif [ "$loop" != "$ref_loop" ]; then
    first=$(A="$ref_loop" B="$loop" NA="${ref##*/}" NB="${name##*/}" awk 'BEGIN {
      n = split(ENVIRON["A"], a, "\n"); m = split(ENVIRON["B"], b, "\n")
      for (i = 1; i <= (n > m ? n : m); i++)
        if (a[i] != b[i]) { printf "%s has \"%s\", %s has \"%s\"", ENVIRON["NA"], a[i], ENVIRON["NB"], b[i]; exit }
    }')
    drift="${drift}the '$LOOP' sections of $ref and $name differ: $first"$'\n'
  fi
done
if [ -n "$drift" ]; then
  drift="${drift}Keep one text in every body, last in each file; an edit to one copy goes to the others."$'\n'
fi

blocking() {
  [ -z "$blocked" ] || printf '%s' "$blocked" >&2
  [ -z "$drift" ] || printf '%s' "$drift" >&2
  [ -z "$blocked$drift" ] || exit 2
}

size_check_off() {
  printf 'validate-rules: %s; the body-size check is OFF\n' "$1" >&2
  blocking
  exit 1
}

if [ ! -x "$ORACLE" ] || [ ! -x "$JQ" ]; then
  size_check_off "$ORACLE or $JQ is missing or not executable"
fi

# Templated, because macOS mktemp ignores $TMPDIR and its default directory is closed under
# the Bash sandbox.
fx=$(mktemp -d "${TMPDIR:-/tmp}/validate-rules.XXXXXX") ||
  size_check_off "cannot create a fixture directory"
trap 'rm -rf "$fx"' EXIT

broke=""
for rule in "${rules[@]}"; do
  body="$ROOT/conventions/$rule.md"
  [ -f "$body" ] || continue
  mkdir "$fx/$rule"
  if ! fixture "$rule" "$fx/$rule"; then
    block "conventions/$rule.md has no fixture row in hooks/validate-rules.sh, so its size is never checked"
    continue
  fi
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
  # The body's last line reaches the injection only when the whole body was inlined. The
  # oracle's notice wording is not the signal: rewording it would pass every overflow.
  last=$(awk 'NF { l = $0 } END { print l }' "$body")
  case "$ctx" in
    *"$last"*) [ -z "$msg" ] || broke="${broke}validate-rules: session-rules.sh $rule: $msg"$'\n' ;;
    *) block "conventions/$rule.md is too big to inline at session start${msg:+: $msg}" ;;
  esac
done

[ -z "$broke" ] || printf '%s' "$broke" >&2
case "$blocked" in
  *"too big"*) blocked="${blocked}Trim the body until hooks/validate-rules.sh passes; a session in a matching repo would otherwise start without it."$'\n' ;;
esac
blocking
[ -z "$broke" ] || exit 1
exit 0
