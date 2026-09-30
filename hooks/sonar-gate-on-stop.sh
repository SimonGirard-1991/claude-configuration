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
# when it carries its reason on the same line. Only the unjustified ones — and "all", which
# suppresses rules nobody chose — are refused.
#
# A Sonar property that excludes, skips or narrows analysis hides findings the same way, and
# excluding the file a red finding sits in is the easy way off it, so poms are held to the same
# rule. Each suppression property that is new or changed against the base needs an XML comment on
# its own lines, or one ending just above its block of adjacent suppression properties. Properties
# are read as elements with comments blanked, in the tag forms Maven reads (whitespace or
# attributes in a start tag, whitespace in an end tag), so a value spread over several lines is one
# property. The report shows each reason, so a borrowed one is visible. The gate accepts such
# properties only in a pom: any in .mvn/maven.config or .mvn/jvm.config is refused. A value routed
# through a ${property} is not traced. Poms are audited even when no java file changed, though
# nothing is scanned then: --files would be empty.
#
# Both audits compare each file with its blob at the base rather than parse a diff, so neither
# diff config nor .gitattributes can hide a line or misnumber one. Lines are counted, so a second
# copy of a grandfathered line is new. A file moved since the base is audited as new, so its old
# suppressions need reasons too; mapping renames was judged not worth it. Every pattern is ASCII,
# so the text tools run under LC_ALL=C: in a UTF-8 locale, macOS awk aborts on a Latin-1 byte and
# grep stops matching the line.
#
# Justified suppressions reach the user as a systemMessage, once per distinct set. An earlier
# version printed them to stderr and exited 0, and stderr from a hook that exits 0 goes to the
# debug log only, so that report reached no one.
#
# Inert unless the repo opts in with a `.sonar-gate` file at its root. A tree that deletes the
# marker while its base still has it gets a systemMessage, because that turns the gate off.
#
# It never boots infrastructure: --no-boot means a stopped SonarQube exits 1 telling you to run
# the script by hand once, rather than a container appearing mid-turn and a ~20s wait landing
# inside somebody's build. Infrastructure failures never block, but they are never silent
# either — same rule as validate-readme.sh.
#
# A green run is remembered: a Stop whose fingerprinted inputs match the last green run skips the
# scan instead of paying for another Maven build. The fingerprint covers the base commit, and the
# diff against it plus the untracked files for java sources, poms and the contract schemas that
# rules/java.md treats as code; then `.sonar-gate`, the gate script and this hook. Only a green
# run records it, and it is taken before the change set is read: anything that lands later,
# mid-scan included, changes the next fingerprint instead of being recorded as clean without
# having been analyzed. Everything else the build reads is outside it — resources,
# `lombok.config`, `.mvn/`, dependencies, the server's quality profile — so a turn that changed
# only those is not re-scanned until a fingerprinted input changes; remove
# $TMPDIR/claude-sonar-fp-* to force one.
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

# Committed work on a feature branch counts too, so compare against the fork point when there
# is one rather than only the working tree.
base=""
for ref in refs/remotes/origin/HEAD refs/heads/main refs/heads/master; do
  base=$(git -C "$repo" merge-base HEAD "$ref" 2>/dev/null) && break
done
[ -n "$base" ] || base="HEAD"

tell_user() {
  MSG="$1" /usr/bin/jq -n \
    '{systemMessage: (env.MSG | if length > 9500 then .[:9500] + "\n[truncated]" else . end)}'
}

if [ ! -f "$repo/.sonar-gate" ]; then
  if git -C "$repo" cat-file -e "$base:.sonar-gate" 2>/dev/null; then
    tell_user "Sonar gate is OFF in $repo: .sonar-gate is deleted there but present in the base commit $(git -C "$repo" rev-parse --short "$base" 2>/dev/null)."
  fi
  exit 0
fi
[ -f "$repo/pom.xml" ] || exit 0
repo_key=$(printf '%s' "$repo" | shasum -a 256 | cut -c1-16)

fp_paths=('*.java' '*pom.xml' '*.proto' '*.avsc' '*.avdl'
  '*openapi*.yaml' '*openapi*.yml' 'openapi/*' '*/openapi/*'
  '*-api.yaml' '*-api.yml')

fingerprint() (
  set -o pipefail
  {
    git -C "$repo" rev-parse --verify --quiet "$base^{commit}" &&
      git -C "$repo" diff --no-ext-diff --no-textconv --no-color "$base" -- "${fp_paths[@]}" &&
      git -C "$repo" ls-files --others --exclude-standard -z -- "${fp_paths[@]}" |
      while IFS= read -r -d '' f; do
        printf '%s ' "$f"
        git -C "$repo" hash-object -- "$f" || exit 1
      done &&
      cat "$repo/.sonar-gate" "$GATE" "${BASH_SOURCE[0]}"
  } | shasum -a 256 | cut -d' ' -f1
)
fp=$(fingerprint) || fp=""

untracked=$(git -c core.quotePath=false -C "$repo" ls-files --others --exclude-standard -- '*.java' 2>/dev/null)
changed=$(
  {
    git -c core.quotePath=false -C "$repo" diff --name-only "$base" -- '*.java' 2>/dev/null
    printf '%s\n' "$untracked"
  } | grep -v '^$' | sort -u
)

base_blob() {
  git -C "$repo" cat-file blob "$base:$1" 2>/dev/null
}

# Prints line<TAB>text for each line of the working-tree file $1 that matches the ERE $KEEP and
# does not appear as a whole line in the file at the base.
new_lines() {
  KEEP="$KEEP" LC_ALL=C awk '
    { sub(/\r$/, "") }
    FILENAME == ARGV[1] { if ($0 ~ ENVIRON["KEEP"]) seen[$0]++; next }
    $0 ~ ENVIRON["KEEP"] {
      if (seen[$0] > 0) {
        seen[$0]--
        next
      }
      print FNR "\t" $0
    }
  ' <(base_blob "$1") "$repo/$1"
}

SONAR_SUPPRESSION='sonar\.(issue\.(ignore|enforce)\.|([[:alnum:]_-]+\.)*(exclusions|inclusions|skip|sources|tests|suffixes)([^[:alnum:]_.-]|$))'

# Awk functions that read a pom as elements with comments blanked. scan() fills F, L, N and V
# with the first line, last line, name and whitespace-collapsed value of each property whose
# name matches ENVIRON["RE"], and returns how many it found.
POM_SCAN='
    function collapse(s) {
      gsub(/[[:space:]]+/, " ", s)
      sub(/^ /, "", s)
      sub(/ $/, "", s)
      return s
    }
    function line_of(d, p, t) {
      t = substr(d, 1, p)
      return gsub(/\n/, "", t) + 1
    }
    function comment(s, a, b) {
      a = index(s, "<!--")
      if (a == 0) return ""
      s = substr(s, a + 4)
      b = index(s, "-->")
      if (b) s = substr(s, 1, b - 1)
      return collapse(s)
    }
    function blank_comments(d, out, a, b, seg) {
      out = ""
      while ((a = index(d, "<!--")) > 0) {
        out = out substr(d, 1, a - 1)
        d = substr(d, a)
        b = index(d, "-->")
        if (b) {
          seg = substr(d, 1, b + 2)
          d = substr(d, b + 3)
        } else {
          seg = d
          d = ""
        }
        gsub(/[^\n]/, " ", seg)
        out = out seg
      }
      return out d
    }
    # A self-closing or unterminated tag ends at its own ">", so it swallows nothing after it.
    function scan(d, F, L, N, V, pos, n, start, name, esc, body, endp, value) {
      d = blank_comments(d)
      pos = 1
      n = 0
      while (match(substr(d, pos), /<sonar\.[^>[:space:]\/]+([[:space:]][^>]*)?>/)) {
        start = pos + RSTART - 1
        body = start + RLENGTH
        name = substr(d, start + 1, RLENGTH - 2)
        sub(/[[:space:]].*$/, "", name)
        value = ""
        endp = body - 1
        if (substr(d, body - 2, 1) != "/") {
          esc = name
          gsub(/\./, "[.]", esc)
          if (match(substr(d, body), "</" esc "[[:space:]]*>")) {
            value = substr(d, body, RSTART - 1)
            endp = body + RSTART + RLENGTH - 2
          }
        }
        pos = endp + 1
        if (name !~ ENVIRON["RE"]) continue
        n++
        F[n] = line_of(d, start)
        L[n] = line_of(d, endp)
        N[n] = name
        V[n] = collapse(value)
      }
      return n
    }
'

# Prints G or B, a tab, then an entry for each suppression property of the pom $1 that is new or
# changed against the base: G when an XML comment gives its reason, B when none does.
pom_audit() {
  RE="$SONAR_SUPPRESSION" P="$1" LC_ALL=C awk "$POM_SCAN"'
    { sub(/\r$/, "") }
    FILENAME == ARGV[1] { old = old $0 "\n"; next }
    { doc = doc $0 "\n"; line[FNR] = $0 }
    END {
      m = scan(old, OF, OL, ON, OV)
      for (i = 1; i <= m; i++) seen[ON[i] "\t" OV[i]] = 1
      n = scan(doc, F, L, N, V)
      for (i = 1; i <= n; i++) opens[L[i]] = F[i]
      for (i = 1; i <= n; i++) {
        if ((N[i] "\t" V[i]) in seen) continue
        why = comment(line[F[i]])
        if (why == "" && L[i] != F[i]) why = comment(line[L[i]])
        if (why == "") {
          k = F[i] - 1
          while (k > 0 && (k in opens)) k = opens[k] - 1
          if (k > 0 && line[k] ~ /-->[[:space:]]*$/) {
            text = line[k]
            for (j = k - 1; j > 0 && index(text, "<!--") == 0; j--) text = line[j] "\n" text
            why = comment(text)
          }
        }
        entry = "  " ENVIRON["P"] ":" F[i] ": <" N[i] ">" V[i] "</" N[i] ">"
        if (why == "") print "B\t" entry
        else print "G\t" entry " (reason: " why ")"
      }
    }' <(base_blob "$1") "$repo/$1"
}

# An audit that cannot run must not pass as one that found nothing.
audit_failed() {
  printf 'sonar gate: the suppression audit failed on %s; Sonar checks are OFF for this turn\n' "$1" >&2
  exit 1
}

pom_bad=""
pom_good=""
while IFS= read -r -d '' f; do
  [ -f "$repo/$f" ] || continue
  found=$(pom_audit "$f") || audit_failed "$f"
  while IFS=$'\t' read -r verdict entry; do
    case "$verdict" in
      G) pom_good="${pom_good}${entry}"$'\n' ;;
      B) pom_bad="${pom_bad}${entry}"$'\n' ;;
    esac
  done < <(printf '%s\n' "$found")
done < <(
  git -C "$repo" diff --name-only -z --no-ext-diff "$base" -- pom.xml '*/pom.xml' 2>/dev/null
  git -C "$repo" ls-files --others --exclude-standard -z -- pom.xml '*/pom.xml' 2>/dev/null
)
for f in .mvn/maven.config .mvn/jvm.config; do
  [ -f "$repo/$f" ] || continue
  found=$(KEEP="$SONAR_SUPPRESSION" new_lines "$f") || audit_failed "$f"
  while IFS=$'\t' read -r n text; do
    [ -n "$n" ] || continue
    pom_bad="${pom_bad}  $f:$n: ${text#"${text%%[![:space:]]*}"}"$'\n'
  done < <(printf '%s\n' "$found")
done

# One grep over the changed set, so a Stop pays a process per file only for the files that
# carry a suppression at all.
suppressing=""
if [ -n "$changed" ]; then
  suppressing=$(cd "$repo" && printf '%s\n' "$changed" | tr '\n' '\0' |
    LC_ALL=C xargs -0 grep -lE -e '@SuppressWarnings|NOSONAR' -- 2>/dev/null)
fi

# Prints, as one anchored ERE, the paths the base's root pom keeps out of analysis through
# sonar.exclusions. Sonar reads them as ant patterns relative to each module, so "**/" matches
# any leading directories, none included, while "*" and "?" stop at a "/". A pattern not rooted
# in "**/" is matched from the repository root instead, which can only exempt less than Sonar does.
excluded_paths_ere() {
  RE='^sonar[.]exclusions$' LC_ALL=C awk "$POM_SCAN"'
    { sub(/\r$/, ""); doc = doc $0 "\n" }
    END { n = scan(doc, F, L, N, V); for (i = 1; i <= n; i++) print V[i] }
  ' <(base_blob pom.xml) | tr ',' '\n' | LC_ALL=C sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^$/d' |
    LC_ALL=C sed -e 's/[].[^$+(){}|\\]/\\&/g' -e 's|?|[^/]|g' -e 's|[*][*]/|@DIRS@|g' \
      -e 's|[*][*]|@ANY@|g' -e 's|[*]|[^/]*|g' -e 's|@DIRS@|(.*/)?|g' -e 's|@ANY@|.*|g' |
    LC_ALL=C awk '{ ere = ere (NR > 1 ? "|" : "") $0 } END { if (NR) print "^(" ere ")$" }'
}

# Code that Sonar never analyzes cannot hide a Sonar finding, so its suppressions are not
# audited: generators such as jOOQ and openapi-generator put @SuppressWarnings("all") on every
# class they write. Only exclusions the base already has count. One added in this change is
# held to the pom audit above and exempts nothing until it is committed, so every exemption
# rests on an exclusion whose reason has been seen.
if [ -n "$suppressing" ]; then
  excluded=$(excluded_paths_ere) || audit_failed pom.xml
  if [ -n "$excluded" ]; then
    suppressing=$(printf '%s\n' "$suppressing" | LC_ALL=C grep -vE -e "$excluded")
  fi
fi

bad=""
good=""
while IFS= read -r f; do
  [ -n "$f" ] && [ -f "$repo/$f" ] || continue
  found=$(KEEP='@SuppressWarnings|NOSONAR' new_lines "$f") || audit_failed "$f"
  while IFS=$'\t' read -r n text; do
    [ -n "$n" ] || continue
    text="${text#"${text%%[![:space:]]*}"}"
    entry="  $f:$n: $text"$'\n'
    case "$text" in
      *'@SuppressWarnings'*)
        if printf '%s' "$text" | LC_ALL=C grep -qE '@SuppressWarnings[[:space:]]*\([[:space:]]*"all"'; then
          bad="${bad}${entry}"
        elif printf '%s' "$text" | LC_ALL=C grep -qE '@SuppressWarnings.*//[[:space:]]*[^[:space:]]'; then
          good="${good}${entry}"
        else
          bad="${bad}${entry}"
        fi
        ;;
      *NOSONAR*)
        if printf '%s' "$text" | LC_ALL=C grep -qE 'NOSONAR[[:space:]]*[-:(][[:space:]]*[^[:space:]]'; then
          good="${good}${entry}"
        else
          bad="${bad}${entry}"
        fi
        ;;
    esac
  done < <(printf '%s\n' "$found")
done < <(printf '%s\n' "$suppressing")

refuse_unjustified() {
  if [ -n "$bad" ]; then
    printf 'SONAR GATE: unjustified suppression(s) added:\n%s' "$bad" >&2
    printf 'Suppressing is allowed when Sonar is wrong, but the reason goes on the same line:\n' >&2
    printf '  // NOSONAR: <why this rule does not apply here>\n' >&2
    printf '  @SuppressWarnings("java:S1234") // <why>\n' >&2
    printf '@SuppressWarnings("all") is never accepted. Fix the finding or justify it.\n' >&2
  fi
  if [ -n "$pom_bad" ]; then
    printf 'SONAR GATE: Sonar properties that exclude, skip or narrow analysis, added without a reason:\n%s' "$pom_bad" >&2
    printf 'They hide findings the way NOSONAR does. Give each its reason in an XML comment, on its own\n' >&2
    printf 'lines or ending just above its block of adjacent suppression properties. The gate accepts them\n' >&2
    printf 'only in a pom: move any from .mvn/maven.config or .mvn/jvm.config into one.\n' >&2
  fi
  exit 2
}

[ -z "${bad}${pom_bad}" ] || refuse_unjustified

reported_file="${TMPDIR:-/tmp}/claude-sonar-reported-${repo_key}"

# Keyed without line numbers, so an edit above a suppression does not report the set again.
report_suppressions() {
  local all key
  all="${good}${pom_good}"
  if [ -z "$all" ]; then
    rm -f "$reported_file"
    return 0
  fi
  key=$(printf '%s' "$all" | LC_ALL=C sed 's/^\(  [^:]*\):[0-9]*: /\1: /' | shasum -a 256 | cut -d' ' -f1)
  [ "$key" != "$(cat "$reported_file" 2>/dev/null)" ] || return 0
  tell_user "Sonar gate: this change adds Sonar suppressions, each with its reason:"$'\n'"$all" &&
    printf '%s\n' "$key" >"$reported_file"
}

if [ -z "$changed" ]; then
  report_suppressions
  exit 0
fi

if [ ! -x "$GATE" ]; then
  printf 'sonar gate: %s missing or not executable; Sonar checks are OFF\n' "$GATE" >&2
  exit 1
fi

counter="${TMPDIR:-/tmp}/claude-sonar-gate-${agent}"
fp_file="${TMPDIR:-/tmp}/claude-sonar-fp-${repo_key}"

clean() {
  rm -f "$counter"
  report_suppressions
  exit 0
}

if [ -n "$fp" ] && [ "$fp" = "$(cat "$fp_file" 2>/dev/null)" ]; then
  clean
fi

rounds=$(cat "$counter" 2>/dev/null || echo 0)

# Templated, because macOS mktemp ignores $TMPDIR and its default directory is closed under
# the Bash sandbox.
out=$(mktemp "${TMPDIR:-/tmp}/claude-sonar-out.XXXXXX")
err=$(mktemp "${TMPDIR:-/tmp}/claude-sonar-err.XXXXXX")
pat=$(mktemp "${TMPDIR:-/tmp}/claude-sonar-files.XXXXXX")
trap 'rm -f "$out" "$err" "$pat"' EXIT
printf '%s\n' "$changed" >"$pat"

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
  [ -n "$fp" ] && printf '%s\n' "$fp" >"$fp_file"
  clean
fi

rounds=$((rounds + 1))
printf '%s' "$rounds" >"$counter"

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
[ -n "${good}${pom_good}" ] &&
  printf 'Justified suppression(s) already present, report these:\n%s' "${good}${pom_good}" >&2
printf 'Fix these, or justify a suppression inline. Do not end the turn dirty.\n' >&2
exit 2
