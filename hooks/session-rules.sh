#!/bin/bash
# SessionStart: inject the Java or React/Next conventions into sessions whose repo needs
# them, keyed on the repo rather than on a tool call.
#
# Path-scoped rules load only when the Read tool opens a matching file, and auto mode
# steers reads to `cat` and `sed`. In the fortnight after the Java architect was retired
# into rules/java.md, the rule reached 3 of 7 Java-editing main sessions; the self-review
# loop it prescribes ran in 2 of those 3 and in none of the other 4. The rules keep their
# `paths:` as a fallback for repos this detector misses.
#
# Usage: session-rules.sh <java|frontend>. One rule per invocation, because every hook
# output field is capped at 10,000 characters and frontend.md alone is ~9.2k; over the
# cap Claude receives a file path and a 2,000-character preview instead of the rule.
#
# Detection probes the session cwd and its git toplevel:
#   java      pom.xml, build.gradle(.kts) or settings.gradle(.kts)
#   frontend  a package.json depending on react or next but not on @angular/core or
#             react-native (frontend.md is React/Next; Angular Storybook setups list react)
# Each candidate is checked directly, then one and two directory levels down, and those
# globs run only strictly under $HOME: never at /, /Users, a mount point or $HOME itself,
# where a two-level glob can walk a network share and stall the first turn.
#
# Output is JSON. additionalContext carries one factual header line with a marker,
# [session-rules <rule> <sha8 of the body>], then the rule without its frontmatter; the
# header states a fact rather than an instruction, since injected imperatives can trip
# prompt-injection handling. Each injection appends a line to logs/rules.jsonl.
#
# Failures are loud: an unreadable rule, an oversized rule or an unwritable log becomes a
# systemMessage the user sees; a missing jq exits 1 with one line on stderr.
#
# CLAUDE_CONFIG_DIR / CLAUDE_RULES_LOG override for testing.

ROOT="${CLAUDE_CONFIG_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG="${CLAUDE_RULES_LOG:-$ROOT/logs/rules.jsonl}"
JQ=/usr/bin/jq
CAP=9800
rule="$1"

if [ ! -x "$JQ" ]; then
  printf 'session-rules: %s not found; the %s conventions were not injected\n' "$JQ" "${rule:-?}" >&2
  exit 1
fi
case "$rule" in
  java | frontend) ;;
  *)
    printf 'session-rules: usage: session-rules.sh <java|frontend>\n' >&2
    exit 1
    ;;
esac

payload=$(cat)
field() { printf '%s' "$payload" | KEY="$1" "$JQ" -r '.[env.KEY] // empty' 2>/dev/null; }
cwd=$(field cwd)
[ -n "$cwd" ] || cwd="$PWD"
top=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
home_p=$(cd "$HOME" 2>/dev/null && pwd -P)

globbable() {
  [ -n "$home_p" ] || return 1
  case "$1" in
    "$home_p"/*) return 0 ;;
    *) return 1 ;;
  esac
}

java_marker() {
  local dir="$1" f
  for f in pom.xml build.gradle build.gradle.kts settings.gradle settings.gradle.kts; do
    if [ -f "$dir/$f" ]; then
      printf '%s\n' "$f"
      return 0
    fi
  done
  globbable "$dir" || return 1
  for f in "$dir"/*/pom.xml "$dir"/*/build.gradle* "$dir"/*/settings.gradle* \
    "$dir"/*/*/pom.xml "$dir"/*/*/build.gradle* "$dir"/*/*/settings.gradle*; do
    case "$f" in */node_modules/*) continue ;; esac
    if [ -f "$f" ]; then
      printf '%s\n' "${f#"$dir"/}"
      return 0
    fi
  done
  return 1
}

react_manifest() {
  "$JQ" -e '(.dependencies // {}) + (.devDependencies // {})
    | (has("react") or has("next"))
      and (has("@angular/core") | not)
      and (has("react-native") | not)' "$1" >/dev/null 2>&1
}

frontend_marker() {
  local dir="$1" f
  if [ -f "$dir/package.json" ] && react_manifest "$dir/package.json"; then
    printf 'package.json\n'
    return 0
  fi
  globbable "$dir" || return 1
  for f in "$dir"/*/package.json "$dir"/*/*/package.json; do
    case "$f" in */node_modules/*) continue ;; esac
    if [ -f "$f" ] && react_manifest "$f"; then
      printf '%s\n' "${f#"$dir"/}"
      return 0
    fi
  done
  return 1
}

marker=""
for candidate in "$cwd" "$top"; do
  [ -n "$candidate" ] && [ -d "$candidate" ] || continue
  physical=$(cd "$candidate" 2>/dev/null && pwd -P) || continue
  case "$rule" in
    java) marker=$(java_marker "$physical") ;;
    frontend) marker=$(frontend_marker "$physical") ;;
  esac
  [ -n "$marker" ] && break
done
[ -n "$marker" ] || exit 0

label="Java"
[ "$rule" = frontend ] && label="React/Next"
rule_file="$ROOT/rules/$rule.md"
notice=""
if [ ! -r "$rule_file" ]; then
  MSG="session-rules: $rule_file is unreadable; the $label conventions are OFF for this session" \
    "$JQ" -n '{systemMessage: env.MSG}'
  exit 0
fi

body=$(awk 'NR == 1 && /^---$/ { fm = 1; next } fm && /^---$/ { fm = 0; next } !fm' "$rule_file")
sha=$(printf '%s' "$body" | shasum -a 256 | cut -c1-8)
header="[session-rules $rule $sha] The user's $label conventions from ~/.claude/rules/$rule.md follow; loaded because the session directory contains $marker."
context="$header"$'\n\n'"$body"
if [ "${#context}" -gt "$CAP" ]; then
  context="[session-rules $rule $sha] The user's $label conventions live in ~/.claude/rules/$rule.md, which is over the hook output cap; it is not inlined here."
  notice="session-rules: rules/$rule.md exceeds $CAP characters, so only a pointer was injected; trim it back under the cap"
fi

mkdir -p "$(dirname "$LOG")" 2>/dev/null
ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
session=$(field session_id)
origin=$(field source)
entry=$(TS="$ts" SESSION="$session" CWD="$cwd" SOURCE="$origin" RULE="$rule" MARKER="$sha" "$JQ" -cn \
  '{ts: env.TS, session_id: env.SESSION, cwd: env.CWD, source: env.SOURCE, rule: env.RULE,
    marker: env.MARKER, via: "session_start_hook"}')
if ! printf '%s\n' "$entry" >>"$LOG" 2>/dev/null; then
  notice="${notice:+$notice; }session-rules: cannot write $LOG, so rule loads are not being measured"
fi

CTX="$context" MSG="$notice" "$JQ" -n \
  '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: env.CTX}}
   + (if env.MSG == "" then {} else {systemMessage: env.MSG} end)'
exit 0
