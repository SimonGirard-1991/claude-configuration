#!/bin/bash
# SessionStart: inject a language's conventions into sessions whose repo needs them, keyed
# on the repo rather than on a tool call.
#
# The body lives in conventions/<rule>.md. rules/<rule>.md is a pointer stub that keeps the
# `paths:` fallback for repos this detector misses and for subagents, which get rules only
# natively. Claude Code loads a path-scoped rule on a Read, an Edit, a Write or a
# single-file Bash read, and never checks whether the same text is already in context:
# with the body in rules/, half the Java sessions held it twice (MAINTAINERS, 2026-10-22).
#
# Usage: session-rules.sh <java|frontend|swift|python>. One rule per invocation, because
# every hook output field is capped at 10,000 characters and two bodies together exceed
# it; over the cap Claude receives a file path and a 2,000-character preview instead of
# the rule.
# hooks/validate-rules.sh blocks a turn that pushes one body past $CAP.
#
# Detection probes the session cwd and its git toplevel:
#   java      pom.xml, build.gradle(.kts) or settings.gradle(.kts)
#   frontend  a package.json depending on react or next but not on @angular/core or
#             react-native (frontend.md is React/Next; Angular Storybook setups list react)
#   swift     Package.swift, a *.xcodeproj or *.xcworkspace directory, or an XcodeGen
#             project.yml: one whose top-level targets: mapping has a target declaring
#             type: and an Apple platform: or supportedDestinations:. Never in a repo whose
#             root package.json depends on react-native: its Swift is the native shell.
#   python    pyproject.toml, setup.py, setup.cfg, requirements.txt or uv.lock, at the top
#             only: a Python tool nested in a Java or React repo is not a Python repo.
# Each marker is checked directly, then down to the rule's depth: two levels, or none for
# python. Those globs run only strictly under $HOME: never at /, /Users, a mount point or
# $HOME itself, where a two-level glob can walk a network share and stall the first turn.
# A marker under node_modules, .build, Pods or DerivedData does not count.
#
# Output is JSON. additionalContext carries one factual header line with a marker,
# [session-rules <rule> <sha8 of the body>], then the body; the header states a fact rather
# than an instruction, since injected imperatives can trip prompt-injection handling. Each
# injection appends a line to logs/rules.jsonl.
#
# Failures are loud: an unreadable body, an oversized body or an unwritable log becomes a
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

# One row per rule: its label, how deep its markers are searched, the test a candidate
# must pass, a test that vetoes a whole repo, and the marker names, globs allowed.
veto=""
case "$rule" in
  java)
    label=Java depth=2 accept=is_file
    markers=(pom.xml build.gradle build.gradle.kts settings.gradle settings.gradle.kts)
    ;;
  frontend)
    label=React/Next depth=2 accept=react_manifest
    markers=(package.json)
    ;;
  swift)
    label=Swift depth=2 accept=swift_marker veto=react_native_root
    markers=(Package.swift '*.xcodeproj' '*.xcworkspace' project.yml)
    ;;
  python)
    label=Python depth=0 accept=is_file
    markers=(pyproject.toml setup.py setup.cfg requirements.txt uv.lock)
    ;;
  *)
    printf 'session-rules: usage: session-rules.sh <java|frontend|swift|python>\n' >&2
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

# shellcheck disable=SC2329  # the rule table names these tests; they run through $accept and $veto
{
  is_file() { [ -f "$1" ]; }

  depends_on() {
    DEP="$2" "$JQ" -e '(.dependencies // {}) + (.devDependencies // {}) | has(env.DEP)' "$1" \
      >/dev/null 2>&1
  }

  react_manifest() {
    [ -f "$1" ] && "$JQ" -e '(.dependencies // {}) + (.devDependencies // {})
      | (has("react") or has("next"))
        and (has("@angular/core") | not)
        and (has("react-native") | not)' "$1" >/dev/null 2>&1
  }

  react_native_root() { [ -f "$1/package.json" ] && depends_on "$1/package.json" react-native; }

  # XcodeGen's spec: targets maps each name to a target whose own keys include type and a
  # platform (iOS, tvOS, macOS, watchOS, visionOS, or a list of them), or
  # supportedDestinations for a multi-platform target. Keys nested deeper do not count.
  xcodegen_spec() {
    LC_ALL=C awk '
      /^targets:[[:space:]]*(#.*)?$/ { inside = 1; target = -1; next }
      inside && /^[^[:space:]#]/ { inside = 0 }
      !inside || /^[[:space:]]*(#.*)?$/ { next }
      {
        match($0, /^[[:space:]]*/)
        if (target < 0) target = RLENGTH
        if (RLENGTH == target) { typed = 0; apple = 0; own = -1; next }
        if (own < 0) own = RLENGTH
        if (RLENGTH != own) next
        if ($0 ~ /^[[:space:]]*type:[[:space:]]*[^[:space:]#]/) typed = 1
        if ($0 ~ /^[[:space:]]*platform:[[:space:]]*\[?[[:space:]]*["'\'']?(iOS|tvOS|macOS|watchOS|visionOS)/) apple = 1
        if ($0 ~ /^[[:space:]]*supportedDestinations:/) apple = 1
        if (typed && apple) { found = 1; exit }
      }
      END { exit !found }' "$1"
  }

  swift_marker() {
    case "$1" in
      *.xcodeproj | *.xcworkspace) [ -d "$1" ] ;;
      */project.yml) [ -f "$1" ] && xcodegen_spec "$1" ;;
      *) [ -f "$1" ] ;;
    esac
  }
}

find_marker() {
  local dir="$1" level=0 prefix="" marker f
  while [ "$level" -le "$depth" ]; do
    [ "$level" -eq 0 ] || globbable "$dir" || return 1
    for marker in "${markers[@]}"; do
      # shellcheck disable=SC2231  # $prefix and $marker are globs on purpose; neither holds a space
      for f in "$dir"/$prefix$marker; do
        case "/${f#"$dir"/}" in */node_modules/* | */.build/* | */Pods/* | */DerivedData/*) continue ;; esac
        if "$accept" "$f"; then
          printf '%s\n' "${f#"$dir"/}"
          return 0
        fi
      done
    done
    prefix="$prefix*/"
    level=$((level + 1))
  done
  return 1
}

candidates=()
for candidate in "$cwd" "$top"; do
  [ -n "$candidate" ] && [ -d "$candidate" ] || continue
  physical=$(cd "$candidate" 2>/dev/null && pwd -P) || continue
  if [ -n "$veto" ] && "$veto" "$physical"; then
    exit 0
  fi
  candidates+=("$physical")
done
marker=""
for physical in "${candidates[@]}"; do
  marker=$(find_marker "$physical") && break
done
[ -n "$marker" ] || exit 0

rule_file="$ROOT/conventions/$rule.md"
notice=""
if [ ! -r "$rule_file" ]; then
  MSG="session-rules: $rule_file is unreadable; the $label conventions are OFF for this session" \
    "$JQ" -n '{systemMessage: env.MSG}'
  exit 0
fi

body=$(cat "$rule_file")
sha=$(printf '%s' "$body" | shasum -a 256 | cut -c1-8)
header="[session-rules $rule $sha] The user's $label conventions from ~/.claude/conventions/$rule.md follow; loaded because the session directory contains $marker."
context="$header"$'\n\n'"$body"
if [ "${#context}" -gt "$CAP" ]; then
  context="[session-rules $rule $sha] The user's $label conventions live in ~/.claude/conventions/$rule.md, which is over the hook output cap; it is not inlined here."
  notice="session-rules: conventions/$rule.md exceeds $CAP characters, so only a pointer was injected; trim it back under the cap"
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
