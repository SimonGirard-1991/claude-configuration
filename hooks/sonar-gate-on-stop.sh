#!/bin/bash
# Stop: refuse to let a turn finish with new Sonar findings.
#
# It hung off SubagentStop matching java-backend-architect until that agent was retired into
# rules/java.md; the gate belongs on the session itself now, which is where the Java work
# actually happens. Nothing in the body changed: the trigger already read `.cwd` from the
# payload and is inert unless the repo carries a `.sonar-gate` file.
#
# The rule it enforces is one a model cannot check itself. A self-review loop spawning
# `code-reviewer` is a model checking a model, and that is the wrong instrument for a property
# an analyzer decides. scripts/sonar-gate.sh runs the real Sonar ruleset and exit 2 feeds the
# findings back, so the turn cannot end dirty.
#
# One file set, computed once, used three times. The trigger, the suppression scan and the
# findings filter all read `git diff` against the fork point UNION `ls-files --others`, so an
# untracked new class is seen by all three or none. An earlier version triggered on
# `git status --porcelain` (which collapses untracked directories) while scanning `git diff`
# alone (which cannot see untracked files at all): it could block on a file it had not read,
# or pass one it never looked at.
#
# That set is handed to the script as --files, which filters inside its own jq pipeline before
# ranking and capping. Filtering the script's printed output here instead was a false pass: the
# script caps at 30 findings, so on a project with more pre-existing issues a real finding in a
# changed file fell past the cap and the hook reported nothing to fix.
#
# Suppression is justified, not forbidden. Sonar is wrong often enough that banning NOSONAR
# outright would make the gate something to argue with rather than use. A suppression passes
# when it carries its reason on the same line, and is echoed back so it reaches the user
# rather than being buried in a diff. Only the unjustified ones — and "all", which suppresses
# rules nobody chose — are refused.
#
# Inert unless the repo opts in with a `.sonar-gate` file at its root.
#
# It never boots infrastructure: --no-boot means a stopped SonarQube exits 1 telling you to run
# the script by hand once, rather than a container appearing mid-turn and a ~20s wait landing
# inside somebody's build. Infrastructure failures never block, but they are never silent
# either — same rule as validate-readme.sh.
#
# CLAUDE_CONFIG_DIR / CLAUDE_SONAR_GATE overrides exist for testing.

ROOT="${CLAUDE_CONFIG_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GATE="${CLAUDE_SONAR_GATE:-$ROOT/scripts/sonar-gate.sh}"
MAX_ROUNDS=3

payload=$(cat)
cwd=$(printf '%s' "$payload" | /usr/bin/jq -r '.cwd // empty' 2>/dev/null)
agent=$(printf '%s' "$payload" | /usr/bin/jq -r '.agent_id // .session_id // "noagent"' 2>/dev/null)
[ -n "$cwd" ] || cwd="$PWD"
agent=$(printf '%s' "$agent" | tr -c 'a-zA-Z0-9_-' '-')

repo=$(cd "$cwd" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)
[ -n "$repo" ] || exit 0
[ -f "$repo/.sonar-gate" ] || exit 0
[ -f "$repo/pom.xml" ] || exit 0

# Committed work on a feature branch counts too, so compare against the fork point when there
# is one rather than only the working tree.
base=$(git -C "$repo" merge-base HEAD main 2>/dev/null) || base=""
[ -n "$base" ] || base="HEAD"

untracked=$(git -C "$repo" ls-files --others --exclude-standard -- '*.java' 2>/dev/null)
changed=$(
  { git -C "$repo" diff --name-only "$base" -- '*.java' 2>/dev/null
    printf '%s\n' "$untracked"
  } | grep -v '^$' | sort -u
)
[ -n "$changed" ] || exit 0

if [ ! -x "$GATE" ]; then
  printf 'sonar gate: %s missing or not executable; Sonar checks are OFF\n' "$GATE" >&2
  exit 1
fi

added=$(git -C "$repo" diff --unified=0 "$base" -- '*.java' 2>/dev/null | grep '^+' | grep -v '^+++')
while IFS= read -r f; do
  [ -n "$f" ] && [ -f "$repo/$f" ] || continue
  added="${added}"$'\n'"$(sed 's/^/+/' "$repo/$f")"
done <<< "$untracked"

bad=""
good=""
while IFS= read -r line; do
  [ -n "$line" ] || continue
  case "$line" in
    *'@SuppressWarnings'*)
      if printf '%s' "$line" | grep -qE '@SuppressWarnings[[:space:]]*\([[:space:]]*"all"'; then
        bad="${bad}  ${line#+}"$'\n'
      elif printf '%s' "$line" | grep -qE '@SuppressWarnings.*//[[:space:]]*[^[:space:]]'; then
        good="${good}  ${line#+}"$'\n'
      else
        bad="${bad}  ${line#+}"$'\n'
      fi
      ;;
    *NOSONAR*)
      if printf '%s' "$line" | grep -qE 'NOSONAR[[:space:]]*[-:(][[:space:]]*[^[:space:]]'; then
        good="${good}  ${line#+}"$'\n'
      else
        bad="${bad}  ${line#+}"$'\n'
      fi
      ;;
  esac
done <<< "$added"

if [ -n "$bad" ]; then
  printf 'SONAR GATE: unjustified suppression(s) added:\n%s' "$bad" >&2
  printf 'Suppressing is allowed when Sonar is wrong, but the reason goes on the same line:\n' >&2
  printf '  // NOSONAR: <why this rule does not apply here>\n' >&2
  printf '  @SuppressWarnings("java:S1234") // <why>\n' >&2
  printf '@SuppressWarnings("all") is never accepted. Fix the finding or justify it.\n' >&2
  exit 2
fi

counter="${TMPDIR:-/tmp}/claude-sonar-gate-${agent}"
rounds=$(cat "$counter" 2>/dev/null || echo 0)

out=$(mktemp); err=$(mktemp); pat=$(mktemp)
trap 'rm -f "$out" "$err" "$pat"' EXIT
printf '%s\n' "$changed" > "$pat"

"$GATE" --project-dir "$repo" --no-boot --files "$pat" >"$out" 2>"$err"
status=$?

if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then
  printf 'sonar gate: could not run (exit %s); Sonar checks are OFF for this turn\n' "$status" >&2
  cat "$err" >&2
  exit 1
fi

gate_failed=0
grep -q '^QUALITY GATE: FAILED' "$out" && gate_failed=1
mine=$(grep -E '^[[:space:]]+[^[:space:]]+:[0-9]+ \[' "$out" || true)
count=$(printf '%s' "$mine" | grep -c . || true)

if [ "$status" -eq 0 ]; then
  rm -f "$counter"
  [ -n "$good" ] && printf 'SONAR GATE: clean. New justified suppression(s), report these:\n%s' "$good" >&2
  exit 0
fi

rounds=$((rounds + 1))
printf '%s' "$rounds" > "$counter"

if [ "$rounds" -ge "$MAX_ROUNDS" ]; then
  rm -f "$counter"
  printf 'sonar gate: still red after %s attempts; not blocking again.\n' "$MAX_ROUNDS" >&2
  printf 'Report the outstanding findings to the user rather than suppressing them.\n' >&2
  [ "$gate_failed" -eq 1 ] && grep -A20 '^QUALITY GATE: FAILED' "$out" >&2
  printf '%s\n' "$mine" >&2
  exit 1
fi

printf 'SONAR GATE: new Sonar findings (attempt %s of %s)\n' "$rounds" "$MAX_ROUNDS" >&2
[ "$gate_failed" -eq 1 ] && grep -A20 '^QUALITY GATE: FAILED' "$out" >&2
[ "$count" -gt 0 ] && printf '%s\n' "$mine" >&2
[ -n "$good" ] && printf 'Justified suppression(s) already present, report these:\n%s' "$good" >&2
printf 'Fix these, or justify a suppression inline. Do not end the turn dirty.\n' >&2
exit 2
