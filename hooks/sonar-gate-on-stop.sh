#!/bin/bash
# Stop: refuse to let a turn finish with new Sonar findings.
#
# It hung off SubagentStop matching java-backend-architect until that agent was retired into
# the Java conventions (conventions/java.md); the gate belongs on the session itself now,
# which is where the Java work actually happens. Nothing in the body changed: the trigger
# already read `.cwd` from the payload and is inert unless the repo carries a `.sonar-gate`
# file.
#
# The rule it enforces is one a model cannot check itself. A self-review loop spawning
# `code-reviewer` is a model checking a model, and that is the wrong instrument for a property
# an analyzer decides. scripts/sonar-gate.sh runs the real Sonar ruleset and exit 2 feeds the
# findings back, so the turn cannot end dirty.
#
# One file set (java sources, poms and the JS project's whole directory), computed once, used
# three times. The trigger, the suppression scan (prose aside) and the findings filter all read
# `git diff` against the fork point UNION `ls-files --others`, so an untracked new class is seen
# by all three or none. An earlier version triggered on
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
# rule. Every Sonar property counts, not a list of the narrowing ones: sonar.lang.patterns.<lang>
# drops a language and sonar.java.source turns version-gated rules off, and a list misses the
# next such key. Each Sonar property that is new or changed against the base needs an XML comment on
# its own lines, or one ending just above its block of adjacent suppression properties. Properties
# are read as elements with comments blanked, in the tag forms Maven reads (whitespace or
# attributes in a start tag, whitespace in an end tag), so a value spread over several lines is one
# property. The report shows each reason, so a borrowed one is visible. The gate accepts such
# properties only in a pom: any in .mvn/maven.config or .mvn/jvm.config is refused. A value routed
# through a ${property} is not traced. A changed pom is audited and, since the Maven scan analyses
# each module's pom.xml, listed for the gate too. The pom scan is hand-rolled, so each property's
# name and value must also be what xmllint reads.
#
# Two forms are never accepted, reason or not, because sonar-java honours them for every rule:
# @Generated (javax or jakarta annotation[.processing]) on a class or method, whose
# GeneratedCodeFilter drops all its issues, and in Java a \uXXXX escape for a printable ASCII
# character (measured 2026-10-12 on the server, both hiding every issue of a planted method). A
# text match cannot read Java the way javac does (escapes, identifier-ignorable characters,
# comments or line breaks inside an annotation), so javac's parser
# (scripts/SuppressionAnnotations.java) lists every @SuppressWarnings and @Generated of the changed
# Java files, and each must be one the line audit read as written. That check covers whole files,
# not only the lines added since the base: an annotation already there is refused when its file
# is touched, as scope = changed blocks on a touched file's existing findings.
#
# Exclusions are not the only way a file leaves analysis: a module missing from the build, a
# source root, a size limit or a language setting does it too. So every changed source file (Java
# under src/main/java or src/test/java, a pom, the JS project's code) goes to the gate as
# --indexed, and the gate refuses one its latest analysis holds no component for. Java under the
# base's root-pom exclusions is not analysed by design, so it must carry a generator's header.
#
# Both audits compare each file with its blob at the base rather than parse a diff, so neither
# diff config nor .gitattributes can hide a line or misnumber one. Lines are counted, so a second
# copy of a grandfathered line is new. A file moved since the base is audited as new, so its old
# suppressions need reasons too; mapping renames was judged not worth it. Every pattern is matched
# as bytes, the few non-ASCII ones spelled in UTF-8, so the text tools run under LC_ALL=C: in a
# UTF-8 locale, macOS awk aborts on a Latin-1 byte and grep stops matching the line. Source lines
# end where Java or JavaScript ends them (a lone CR; LS and PS too), and every space JavaScript's
# \s takes reads as a space, since ESLint trims a comment with them before reading its directive.
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
# either: they reach the user whole as a systemMessage, as does a gate still red after
# MAX_ROUNDS. A Stop hook's exit 1 would show the user only the first line of its stderr.
#
# Settings come from `.sonar-gate`, `KEY = value` lines read as sonar-gate.sh reads them.
# `js-project = DIR` adds that directory to the file set, and its sonar-project.properties to the
# suppression audit, under the pom rule; `rules = FILE` adds the rules file to the fingerprint
# and to an audit of its own, since a rule taken out narrows the gate. `scope = project`
# blocks on any finding anywhere instead of the changed files' findings: a commit then moves the
# fingerprint through the base, so the whole project is counted again.
#
# A green run is remembered: a Stop whose fingerprinted inputs match the last green run skips the
# scan instead of paying for another Maven build. The fingerprint covers the base commit, and the
# diff against it plus the untracked files for java sources, poms, the contract schemas that
# rules/java.md's paths: lists, the JS project's directory and the rules file; then
# `.sonar-gate`, the gate script and this hook. Only a green
# run records it, and it is taken before the change set is read: anything that lands later,
# mid-scan included, changes the next fingerprint instead of being recorded as clean without
# having been analyzed. Everything else the build reads is outside it — resources,
# `lombok.config`, `.mvn/`, dependencies, the server's quality profile — so a turn that changed
# only those is not re-scanned until a fingerprinted input changes; remove
# $TMPDIR/claude-sonar-fp-* to force one.
#
# CLAUDE_CONFIG_DIR / CLAUDE_SONAR_GATE / CLAUDE_SONAR_JAVA_ANNOTATIONS overrides exist for testing.

ROOT="${CLAUDE_CONFIG_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GATE="${CLAUDE_SONAR_GATE:-$ROOT/scripts/sonar-gate.sh}"
JAVA_ANNOTATIONS="${CLAUDE_SONAR_JAVA_ANNOTATIONS:-$ROOT/scripts/SuppressionAnnotations.java}"
MAX_ROUNDS=3
GATE_TIMEOUT="${CLAUDE_SONAR_GATE_TIMEOUT:-360}"

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
# Prints the value of the last `KEY = value` line of .sonar-gate, as sonar-gate.sh reads it.
gate_setting() {
  KEY="$1" LC_ALL=C awk '
    { sub(/\r$/, "") }
    /^[[:space:]]*#/ { next }
    {
      line = $0
      sub(/^[[:space:]]*/, "", line)
      if (index(line, ENVIRON["KEY"]) != 1) next
      rest = substr(line, length(ENVIRON["KEY"]) + 1)
      if (rest !~ /^[[:space:]]*=/) next
      sub(/^[[:space:]]*=[[:space:]]*/, "", rest)
      sub(/[[:space:]]+$/, "", rest)
      value = rest
    }
    END { print value }
  ' "$repo/.sonar-gate"
}
scope=$(gate_setting scope)
js_dir=$(gate_setting js-project)
js_dir="${js_dir%/}"
rules_file=$(gate_setting rules)
case "$scope" in
  '') scope=changed ;;
  changed | project) ;;
  *)
    tell_user "Sonar gate is OFF in $repo: .sonar-gate sets scope = $scope, and only changed and project exist."
    exit 0
    ;;
esac
# Both become pathspecs below, so a path that leaves the repository or carries pathspec magic
# would scope the gate to something else than it says.
for setting in "$js_dir" "$rules_file"; do
  case "$setting" in
    /* | . | .. | ../* | */../* | */.. | ./* | *[!A-Za-z0-9._/-]*)
      tell_user "Sonar gate is OFF in $repo: .sonar-gate names $setting, which is not a plain path inside the repository."
      exit 0
      ;;
  esac
done
[ -f "$repo/pom.xml" ] || [ -n "$js_dir" ] || exit 0
repo_key=$(printf '%s' "$repo" | shasum -a 256 | cut -c1-16)

fp_paths=('*.java' '*pom.xml' '*.proto' '*.avsc' '*.avdl'
  '*openapi*.yaml' '*openapi*.yml' 'openapi/*' '*/openapi/*'
  '*-api.yaml' '*-api.yml')
# The JS project counts whole: its analyzer reads .mts, .cts, .html and more than a suffix list
# would keep up with, and listing a file it never reads costs nothing, since the script matches
# findings to exact paths.
js_sources=()
[ -z "$js_dir" ] || js_sources=("$js_dir/")
fp_paths+=(${js_sources[@]+"${js_sources[@]}"})
[ -z "$rules_file" ] || fp_paths+=("$rules_file")

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

sources=('*.java' pom.xml '*/pom.xml' ${js_sources[@]+"${js_sources[@]}"})
untracked=$(git -c core.quotePath=false -C "$repo" ls-files --others --exclude-standard -- "${sources[@]}" 2>/dev/null)
changed=$(
  {
    git -c core.quotePath=false -C "$repo" diff --name-only "$base" -- "${sources[@]}" 2>/dev/null
    printf '%s\n' "$untracked"
  } | grep -v '^$' | sort -u
)

base_blob() {
  git -C "$repo" cat-file blob "$base:$1" 2>/dev/null
}

# Splits the source text of file $1 into lines where its language ends one: LF, CRLF and a lone
# CR, and in JavaScript LS and PS (U+2028, U+2029) too. Every other space in JavaScript's \s
# becomes an ASCII space: U+00A0, U+1680, U+2000 to U+200A, U+202F, U+205F, U+3000 and U+FEFF.
# A NUL is dropped, since macOS awk ends a line at one and would hide the rest of it.
CR=$'\r'
LS_PS=$'\xe2\x80[\xa8\xa9]'
UNICODE_SPACE=$'(\xc2\xa0|\xe1\x9a\x80|\xe2\x80[\x80-\x8a\xaf]|\xe2\x81\x9f|\xe3\x80\x80|\xef\xbb\xbf)'
source_lines() {
  local edits=(-e "s/$CR\$//" -e "s/$UNICODE_SPACE/ /g")
  case "$1" in *.java) ;; *) edits+=(-e "s/$LS_PS/$CR/g") ;; esac
  LC_ALL=C tr -d '\000' | LC_ALL=C sed -E "${edits[@]}" | LC_ALL=C tr '\r' '\n'
}

# Prints line<TAB>text for each source line of the working-tree file $1 that matches the ERE $KEEP
# and does not appear as a whole line in the file at the base.
new_lines() {
  KEEP="$KEEP" LC_ALL=C awk '
    FILENAME == ARGV[1] { if ($0 ~ ENVIRON["KEEP"]) seen[$0]++; next }
    $0 ~ ENVIRON["KEEP"] {
      if (seen[$0] > 0) {
        seen[$0]--
        next
      }
      print FNR "\t" $0
    }
  ' <(base_blob "$1" | source_lines "$1") <(source_lines "$1" <"$repo/$1")
}

SONAR_SUPPRESSION='sonar\.[[:alnum:]_-]'

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
# changed against the base: G when an XML comment gives its reason, B when none does. Then P, a
# tab, and the name and value of each Sonar property it read, tab-separated.
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
      for (i = 1; i <= n; i++) print "P\t" N[i] "\t" V[i]
    }' <(base_blob "$1") "$repo/$1"
}

# The pom scan above is hand-rolled, so a construct it misreads (a CDATA section holding "<!--",
# say, or one that moves where a value ends) could hide a property Maven reads. xmllint reads the
# Sonar properties too, and both must find the same names with the same values. Prints them
# sorted, one `name<TAB>value` per line, the value with its whitespace collapsed as the scan
# collapses it.
xml_sonar_props() {
  local path="$repo/$1" all='//*[starts-with(local-name(),"sonar.")]' tab=$'\t' n i one out=""
  n=$(xmllint --xpath "count($all)" "$path" 2>/dev/null) || return 1
  case "$n" in '' | *[!0-9]*) return 1 ;; esac
  i=1
  while [ "$i" -le "$n" ]; do
    one=$(xmllint --xpath "concat(local-name(($all)[$i]), '$tab', normalize-space(($all)[$i]))" "$path" 2>/dev/null) ||
      return 1
    out="$out$one"$'\n'
    i=$((i + 1))
  done
  printf '%s' "$out" | LC_ALL=C sort
}

# A .properties line ends at LF, CRLF or a lone CR (java.util.Properties, and properties-file,
# which @sonar/scan reads them with).
line_ends() {
  LC_ALL=C sed 's/\r$//' | LC_ALL=C tr '\r' '\n'
}

# Prints G or B, a tab, then an entry for each suppression property of the .properties file $1
# that is new or changed against the base: G when # or ! comment lines give its reason just above
# it, or just above its block of adjacent suppression properties; B when none does.
# A line ending in a backslash continues its property, so a value spread over several lines is
# one property.
props_audit() {
  RE="$SONAR_SUPPRESSION" P="$1" LC_ALL=C awk '
    function collapse(s) {
      gsub(/[[:space:]]+/, " ", s)
      sub(/^ /, "", s)
      sub(/ $/, "", s)
      return s
    }
    function parse(n, LINE, F, L, K, V, E, i, m, text, start, key, value, more) {
      m = 0
      for (i = 1; i <= n; i++) {
        text = LINE[i]
        start = i
        if (text ~ /^[[:space:]]*([#!]|$)/) continue
        while (text ~ /(^|[^\\])(\\\\)*\\$/ && i < n) {
          sub(/\\$/, "", text)
          more = LINE[++i]
          sub(/^[[:space:]]+/, "", more)
          text = text more
        }
        key = text
        sub(/^[[:space:]]*/, "", key)
        value = key
        sub(/[=:[:space:]].*$/, "", key)
        E[m + 1] = (key ~ /\\/)
        gsub(/\\/, "", key)
        sub(/^[^=:[:space:]]*[[:space:]]*[=:]?/, "", value)
        m++
        F[m] = start
        L[m] = i
        K[m] = key
        V[m] = collapse(value)
      }
      return m
    }
    { sub(/\r$/, "") }
    FILENAME == ARGV[1] { old[++no] = $0; next }
    { line[++nl] = $0 }
    END {
      mo = parse(no, old, OF, OL, OK, OV, OE)
      for (j = 1; j <= mo; j++) if (OK[j] ~ ENVIRON["RE"]) seen[OK[j] "\t" OV[j]] = 1
      m = parse(nl, line, F, L, K, V, E)
      for (j = 1; j <= m; j++) if (K[j] ~ ENVIRON["RE"]) opens[L[j]] = F[j]
      for (j = 1; j <= m; j++) {
        if (E[j]) {
          print "B\t  " ENVIRON["P"] ":" F[j] ": " K[j] "=" V[j] " (an escaped key, which the scanner decodes: write it plain)"
          continue
        }
        if (K[j] !~ ENVIRON["RE"] || (K[j] "\t" V[j]) in seen) continue
        k = F[j] - 1
        while (k > 0 && (k in opens)) k = opens[k] - 1
        why = ""
        for (; k > 0 && line[k] ~ /^[[:space:]]*[#!]/; k--) {
          text = line[k]
          sub(/^[[:space:]]*[#!]+/, "", text)
          why = text " " why
        }
        why = collapse(why)
        entry = "  " ENVIRON["P"] ":" F[j] ": " K[j] "=" V[j]
        if (why == "") print "B\t" entry
        else print "G\t" entry " (reason: " why ")"
      }
    }' <(base_blob "$1" | line_ends) <(line_ends <"$repo/$1")
}

# Prints G or B, a tab, then an entry for each rule line of the rules file $1 that the base has
# and the working tree lost or changed: taking a rule or a value out narrows the gate as an
# exclusion does. G when a # line added since the base names the rule and says why, B otherwise.
# The base's own comments justify nothing, so a header that mentions a rule cannot excuse its
# removal.
rules_audit() {
  P="$1" LC_ALL=C awk '
    function rule_line(s) {
      sub(/#.*$/, "", s)
      gsub(/[[:space:]]+/, " ", s)
      sub(/^ /, "", s)
      sub(/ $/, "", s)
      return s
    }
    { sub(/\r$/, "") }
    FILENAME == ARGV[1] {
      t = rule_line($0)
      if (t != "") old[t]++
      if ($0 ~ /^[[:space:]]*#/) old_comment[$0]++
      next
    }
    {
      t = rule_line($0)
      if (t != "") now[t]++
      if ($0 ~ /^[[:space:]]*#/) {
        if (old_comment[$0] > 0) old_comment[$0]--
        else added[++na] = $0
      }
    }
    # The added comment line naming rule k and saying why, other than t itself commented out.
    function reason(k, t, i, c, own, p, rest, why) {
      for (i = 1; i <= na; i++) {
        c = added[i]
        own = c
        sub(/^[[:space:]]*#+/, "", own)
        if (rule_line(own) == t) continue
        p = index(c, k)
        if (p == 0) continue
        rest = substr(c, p + length(k))
        if (rest ~ /^[A-Za-z0-9_]/) continue
        gsub(/^[^A-Za-z0-9]+/, "", rest)
        if (rest == "") continue
        why = c
        sub(/^[[:space:]]*#+[[:space:]]*/, "", why)
        return why
      }
      return ""
    }
    function report(t, what, f, why) {
      split(t, f, " ")
      why = reason(f[1], t)
      if (why == "") print "B\t  " ENVIRON["P"] ": " t " (" what ")"
      else print "G\t  " ENVIRON["P"] ": " t " (" what ") (reason: " why ")"
    }
    END {
      for (t in old)
        if (now[t] + 0 < old[t]) report(t, "taken out or changed")
      for (t in now)
        if (now[t] > old[t] + 0 && t ~ / /) report(t, "added with parameters, which may override Sonar way")
    }' <(base_blob "$1") "$repo/$1"
}

# Prints G or B, a tab, then an entry for each change to .sonar-gate that narrows the gate: the
# JS project or the rules file changed or gone, scope moved off `project`, a pattern added to the
# IDE's exclusions. G when a # line added since the base names the setting and says why, B
# otherwise; the base's own comments justify nothing.
gate_audit() {
  LC_ALL=C awk '
    function trim(s) {
      sub(/^[[:space:]]+/, "", s)
      sub(/[[:space:]]+$/, "", s)
      return s
    }
    function setting(line, into, k, v) {
      if (line !~ /^[[:space:]]*[A-Za-z-]+[[:space:]]*=/) return
      k = line
      sub(/=.*$/, "", k)
      v = line
      sub(/^[^=]*=/, "", v)
      into[trim(k)] = trim(v)
    }
    function reason(key, i, c, own, p, rest, why) {
      for (i = 1; i <= na; i++) {
        c = added[i]
        own = c
        sub(/^[[:space:]]*#+[[:space:]]*/, "", own)
        if (index(own, key) == 1 && substr(own, length(key) + 1) ~ /^[[:space:]]*=/) continue
        p = index(c, key)
        if (p == 0) continue
        rest = substr(c, p + length(key))
        if (rest ~ /^[A-Za-z0-9_-]/) continue
        gsub(/^[^A-Za-z0-9]+/, "", rest)
        if (rest == "") continue
        why = c
        sub(/^[[:space:]]*#+[[:space:]]*/, "", why)
        return why
      }
      return ""
    }
    function report(key, what, why) {
      why = reason(key)
      if (why == "") print "B\t  .sonar-gate: " what
      else print "G\t  .sonar-gate: " what " (reason: " why ")"
    }
    { sub(/\r$/, "") }
    FILENAME == ARGV[1] {
      if ($0 ~ /^[[:space:]]*#/) old_comment[$0]++
      else setting($0, old)
      next
    }
    {
      if ($0 ~ /^[[:space:]]*#/) {
        if (old_comment[$0] > 0) old_comment[$0]--
        else added[++na] = $0
      } else setting($0, now)
    }
    END {
      if (old["js-project"] != "" && now["js-project"] != old["js-project"])
        report("js-project", "js-project " old["js-project"] " is now \"" now["js-project"] "\"")
      if (old["rules"] != "" && now["rules"] != old["rules"])
        report("rules", "rules " old["rules"] " is now \"" now["rules"] "\"")
      if (old["scope"] == "project" && now["scope"] != "project")
        report("scope", "scope project is now \"" now["scope"] "\"")
      n = split(old["ide-exclusions"], before, ",")
      for (i = 1; i <= n; i++) had[trim(before[i])] = 1
      n = split(now["ide-exclusions"], after, ",")
      for (i = 1; i <= n; i++) {
        pattern = trim(after[i])
        if (pattern != "" && !(pattern in had)) report("ide-exclusions", "ide-exclusions adds " pattern)
      }
    }' <(base_blob .sonar-gate) "$repo/.sonar-gate"
}

# An audit that cannot run must not pass as one that found nothing.
audit_failed() {
  tell_user "Sonar gate: the suppression audit failed on $1; Sonar checks are OFF for this turn."
  exit 0
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
  scanned=$(printf '%s\n' "$found" | LC_ALL=C awk -F'\t' '$1 == "P" { print $2 "\t" $3 }' | LC_ALL=C sort)
  parsed=$(xml_sonar_props "$f") || audit_failed "$f"
  if [ "$parsed" != "$scanned" ]; then
    pom_bad="${pom_bad}  $f: xmllint reads its Sonar properties apart from the audit; write them as plain elements:"$'\n'
    pom_bad="${pom_bad}$(LC_ALL=C comm -3 <(printf '%s' "${parsed:+$parsed$'\n'}") <(printf '%s' "${scanned:+$scanned$'\n'}") |
      LC_ALL=C awk -F'\t' '$1 == "" { print "    audit:   " $2 "=" $3; next } { print "    xmllint: " $1 "=" $2 }')"$'\n'
  fi
done < <(
  git -C "$repo" diff --name-only -z --no-ext-diff "$base" -- pom.xml '*/pom.xml' 2>/dev/null
  git -C "$repo" ls-files --others --exclude-standard -z -- pom.xml '*/pom.xml' 2>/dev/null
)
while IFS= read -r -d '' f; do
  [ -f "$repo/$f" ] || continue
  found=$(props_audit "$f") || audit_failed "$f"
  while IFS=$'\t' read -r verdict entry; do
    case "$verdict" in
      G) pom_good="${pom_good}${entry}"$'\n' ;;
      B) pom_bad="${pom_bad}${entry}"$'\n' ;;
    esac
  done < <(printf '%s\n' "$found")
done < <(
  git -C "$repo" diff --name-only -z --no-ext-diff "$base" -- sonar-project.properties '*/sonar-project.properties' 2>/dev/null
  git -C "$repo" ls-files --others --exclude-standard -z -- sonar-project.properties '*/sonar-project.properties' 2>/dev/null
)
found=$(gate_audit) || audit_failed .sonar-gate
while IFS=$'\t' read -r verdict entry; do
  case "$verdict" in
    G) pom_good="${pom_good}${entry}"$'\n' ;;
    B) pom_bad="${pom_bad}${entry}"$'\n' ;;
  esac
done < <(printf '%s\n' "$found")
if [ -n "$rules_file" ] && [ -f "$repo/$rules_file" ]; then
  found=$(rules_audit "$rules_file") || audit_failed "$rules_file"
  while IFS=$'\t' read -r verdict entry; do
    case "$verdict" in
      G) pom_good="${pom_good}${entry}"$'\n' ;;
      B) pom_bad="${pom_bad}${entry}"$'\n' ;;
    esac
  done < <(printf '%s\n' "$found")
fi
for f in .mvn/maven.config .mvn/jvm.config; do
  [ -f "$repo/$f" ] || continue
  found=$(KEEP="$SONAR_SUPPRESSION" new_lines "$f") || audit_failed "$f"
  while IFS=$'\t' read -r n text; do
    [ -n "$n" ] || continue
    pom_bad="${pom_bad}  $f:$n: ${text#"${text%%[![:space:]]*}"}"$'\n'
  done < <(printf '%s\n' "$found")
done

# What the analyzers take as a suppression, measured by scanning planted lines on this server
# rather than assumed (2026-10-11; the forms marked * on 2026-10-12, each hiding a planted issue
# its control showed). sonar-java: NOSONAR anywhere in a comment; @SuppressWarnings resolved by
# type, so `@ SuppressWarnings` and `@java.lang.SuppressWarnings` count, with values resolved as
# constants, so `"a" + "ll"`* and a constant holding "all"* suppress everything, as does a "all"
# on the line after the annotation's reason*; @Generated*, and any of these spelled with \u
# escapes*. SonarJS: a comment starting with NOSONAR in any case, upper-cased the way JavaScript
# does it, which turns U+017F into S (noſonar*, the only code point that becomes a letter of
# NOSONAR); every ESLint directive, the comment trimmed of any space JavaScript knows first, so
# a block comment whose text starts with `eslint` on a later line* or after U+00A0* is one; an
# inline `/* eslint rule: off */` config, which hides an issue without a warning. The CSS
# analyzer: NOSONAR and stylelint's disable directives. Every form is read in every file: a match
# stricter than one analyzer's costs a reason, a looser one a silent green.
LONG_S=$'\xc5\xbf'
NOSONAR="[Nn][Oo]([Ss]|$LONG_S)[Oo][Nn][Aa][Rr]"
SUPPRESSION_WORDS="SuppressWarnings|$NOSONAR|eslint|stylelint|exported|global|\\\\u"

# The suffixes SonarJS and its CSS analyzer read by default, the files whose comments ESLint and
# stylelint directives live in.
JS_CODE='[.](js|jsx|cjs|mjs|vue|ts|tsx|cts|mts|css|less|scss|sass)$'

# ESLint reads a directive from a comment whose trimmed text starts with one of these words and
# a space or its end; in a line comment, only the two -line forms count. eslint-enable is one too,
# but it suppresses nothing.
ESLINT_DIRECTIVE='(eslint(-env|-disable(-next)?-line|-disable)?|exported|globals?)([[:space:]]|[*]/|$)'

# @SuppressWarnings with nothing but string literals for values, all on one line: a constant or
# an expression can resolve to "all", and a value on a later line escapes the line's reason.
SW_PREFIX='@[[:space:]]*(java[[:space:]]*[.][[:space:]]*lang[[:space:]]*[.][[:space:]]*)?'
SW_ANNOTATION="${SW_PREFIX}SuppressWarnings"
SW_LITERAL='"[^"\\]*"'
SW_LITERALS="$SW_LITERAL([[:space:]]*,[[:space:]]*$SW_LITERAL)*"
SW_WELL_FORMED="${SW_ANNOTATION}[[:space:]]*[(][[:space:]]*(value[[:space:]]*=[[:space:]]*)?($SW_LITERAL|[{][[:space:]]*(${SW_LITERALS}[[:space:]]*,?)?[[:space:]]*[}])[[:space:]]*[)]"

# A Java form never accepted: a \u escape for a printable ASCII character, which Java decodes
# before it reads a token, so it can spell a word the text audit looks for. The escape must start
# with a backslash that an even number of backslashes precede, as in Java. What an annotation is,
# @Generated included, javac's parser settles below.
ASCII_ESCAPE='(^|[^\\])(\\\\)*\\u+(00[2-6][0-9A-Fa-f]|007[0-9A-Ea-e])'

# One grep over the changed set, so a Stop pays a process per file only for the files that
# carry a suppression at all.
suppressing=""
code_changed=$(printf '%s\n' "$changed" | LC_ALL=C grep -vE '[.](md|markdown|txt|rst)$' || true)
if [ -n "$code_changed" ]; then
  suppressing=$(cd "$repo" && printf '%s\n' "$code_changed" | tr '\n' '\0' |
    LC_ALL=C xargs -0 grep -lE -e "$SUPPRESSION_WORDS" -- 2>/dev/null)
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
excluded=""
[ -z "$changed" ] || excluded=$(excluded_paths_ere) || audit_failed pom.xml

# Prints the paths of $1 that the root pom's exclusions leave in analysis. They say nothing about
# the JS project's files.
not_excluded() {
  local js_part=""
  if [ -z "$excluded" ]; then
    printf '%s\n' "$1"
    return 0
  fi
  [ -z "$js_dir" ] || js_part=$(printf '%s\n' "$1" | LC_ALL=C grep -F -- "$js_dir/" | LC_ALL=C grep -E "^${js_dir//./[.]}/" || true)
  {
    printf '%s\n' "$1" | LC_ALL=C grep -vE -e "$excluded"
    printf '%s\n' "$js_part"
  } | grep -v '^$' | sort -u
}

# Code that Sonar never analyzes cannot hide a Sonar finding, so its suppressions are not
# audited: generators such as jOOQ and openapi-generator put @SuppressWarnings("all") on every
# class they write. Only exclusions the base already has count. One added in this change is
# held to the pom audit above and exempts nothing until it is committed, so every exemption
# rests on an exclusion whose reason has been seen.
[ -z "$suppressing" ] || suppressing=$(not_excluded "$suppressing")

# Prints `forbidden`, `justified` or `unjustified` for line $2 of file $1 when it holds a
# suppression, nothing for a line that only names one. Each form on the line needs its own reason:
# NOSONAR a `:`, `-` or `(` and words after it; each @SuppressWarnings a `//` comment, string
# literals for values and never "all"; an ESLint or stylelint directive its ` -- description`,
# ESLint's own syntax, which a decrement such as `x--` does not satisfy.
suppression_verdict() {
  local path="$1" line="$2" found=0 reasoned=1 directive=0 uses well
  case "$path" in
    *.java)
      if printf '%s' "$line" | LC_ALL=C grep -qE -e "$ASCII_ESCAPE"; then
        echo forbidden
        return 0
      fi
      ;;
  esac
  uses=$(printf '%s' "$line" |
    LC_ALL=C grep -oE "($SW_PREFIX)?SuppressWarnings([[:space:]]*[(])?" |
    LC_ALL=C grep -cE '^@|[(]$' || true)
  if [ "$uses" -gt 0 ]; then
    found=1
    well=$(printf '%s' "$line" | LC_ALL=C grep -oE "$SW_WELL_FORMED" || true)
    if [ "$(printf '%s' "$well" | grep -c .)" -ne "$uses" ] || printf '%s' "$well" | grep -qF '"all"' ||
      ! printf '%s' "$line" | LC_ALL=C grep -qE 'SuppressWarnings.*//[[:space:]]*[^[:space:]]'; then
      reasoned=0
    fi
  fi
  if printf '%s' "$line" | LC_ALL=C grep -qE '(eslint|stylelint)-disable'; then
    directive=1
  elif printf '%s' "$path" | LC_ALL=C grep -qE "$JS_CODE" &&
    printf '%s' "$line" | LC_ALL=C grep -qE -e "/[*][[:space:]]*$ESLINT_DIRECTIVE" -e "^[[:space:]]*$ESLINT_DIRECTIVE"; then
    directive=1
  fi
  if [ "$directive" -eq 1 ]; then
    found=1
    printf '%s' "$line" | LC_ALL=C grep -qE '(eslint|stylelint|exported|global)[^*]*[[:space:]]--+[[:space:]]+[^[:space:]*]' ||
      reasoned=0
  fi
  if printf '%s' "$line" | LC_ALL=C grep -qE "$NOSONAR"; then
    found=1
    printf '%s' "$line" | LC_ALL=C grep -qE "${NOSONAR}[[:space:]]*[-:(][[:space:]]*[^[:space:]]" ||
      reasoned=0
  fi
  [ "$found" -eq 1 ] || return 0
  if [ "$reasoned" -eq 1 ]; then echo justified; else echo unjustified; fi
}

bad=""
good=""
forbidden=""
while IFS= read -r f; do
  [ -n "$f" ] && [ -f "$repo/$f" ] || continue
  found=$(KEEP="$SUPPRESSION_WORDS" new_lines "$f") || audit_failed "$f"
  while IFS=$'\t' read -r n text; do
    [ -n "$n" ] || continue
    text="${text#"${text%%[![:space:]]*}"}"
    verdict=$(suppression_verdict "$f" "$text")
    entry="  $f:$n: $text"$'\n'
    case "$verdict" in
      justified) good="${good}${entry}" ;;
      unjustified) bad="${bad}${entry}" ;;
      forbidden) forbidden="${forbidden}${entry}" ;;
    esac
  done < <(printf '%s\n' "$found")
done < <(printf '%s\n' "$suppressing")

# The line audit reads text and sonar-java reads Java: a Unicode escape, an identifier-ignorable
# character, a comment or a line break inside an annotation hides it from the first and not from
# the second. So javac's own parser lists every @SuppressWarnings and @Generated of the changed
# Java files, and each must be one the line audit read as written: on one line, in printable
# ASCII, with string literals for values, and never @Generated or "all". An entry the line audit
# already made for that line is not repeated.
add_once() { # $1 name of the list, $2 path:line, $3 entry
  case "${!1}" in
    *"  $2: "*) ;;
    *) printf -v "$1" '%s  %s: %s\n' "${!1}" "$2" "$3" ;;
  esac
}
java_changed=$(printf '%s\n' "$changed" | LC_ALL=C grep -E '[.]java$' || true)
java_audited=""
[ -z "$java_changed" ] || java_audited=$(not_excluded "$java_changed")
if [ -n "$java_audited" ]; then
  annotations=$(cd "$repo" && printf '%s\n' "$java_audited" | while IFS= read -r f; do
    [ -f "$f" ] && printf '%s\0' "$f"
  done | xargs -0 env -u JAVA_TOOL_OPTIONS -u JDK_JAVA_OPTIONS -u _JAVA_OPTIONS java "$JAVA_ANNOTATIONS") ||
    audit_failed "the changed Java files (javac's parser, $JAVA_ANNOTATIONS)"
  while IFS=$'\t' read -r f n kind values shown; do
    [ -n "$f" ] || continue
    case "$kind" in
      generated) add_once forbidden "$f:$n" "$shown" ;;
      plain)
        case ",$values," in
          *,all,*) add_once bad "$f:$n" "$shown" ;;
        esac
        ;;
      *) add_once bad "$f:$n" "$shown (javac reads this @SuppressWarnings, the line audit cannot: write it on one line, in plain ASCII, with string literals)" ;;
    esac
  done < <(printf '%s\n' "$annotations")
fi

# Every changed source file must be analysed. Java under src/main/java or src/test/java, a pom,
# and the JS project's code, by the suffixes SonarJS and its CSS analyzer index by default (a
# .d.ts holds declarations only, and SonarJS leaves it out by default), go to the gate, which
# refuses one its latest analysis holds no component for. Java under the base's root-pom
# exclusions is not analysed by design, so it must carry a generator's header in its first lines.
indexed=""
in_analysis=$(not_excluded "$changed")
while IFS= read -r f; do
  [ -n "$f" ] && [ -f "$repo/$f" ] || continue
  if [ -n "$js_dir" ] && [ "${f#"$js_dir"/}" != "$f" ]; then
    printf '%s\n' "$f" | LC_ALL=C grep -qE "$JS_CODE" && ! printf '%s\n' "$f" | LC_ALL=C grep -qE '[.]d[.]ts$' &&
      indexed="${indexed}${f}"$'\n'
    continue
  fi
  case "$f" in
    pom.xml | */pom.xml) indexed="${indexed}${f}"$'\n' ;;
    *.java)
      if ! printf '%s\n' "$in_analysis" | LC_ALL=C grep -qxF -- "$f"; then
        header=$(head -n 20 "$repo/$f" | LC_ALL=C grep -m 1 -iE 'generated by' | LC_ALL=C sed 's/^[[:space:]]*//')
        if [ -n "$header" ]; then
          good="${good}  $f: kept out of analysis by the root pom's sonar.exclusions (header: $header)"$'\n'
        else
          forbidden="${forbidden}  $f: kept out of analysis by the root pom's sonar.exclusions, with no generator's header"$'\n'
        fi
      elif printf '%s\n' "$f" | LC_ALL=C grep -qE '(^|/)src/(main|test)/java/'; then
        indexed="${indexed}${f}"$'\n'
      fi
      ;;
  esac
done < <(printf '%s\n' "$changed")

refuse_unjustified() {
  if [ -n "$forbidden" ]; then
    printf 'SONAR GATE: what Sonar honours for every rule, which the gate never accepts:\n%s' "$forbidden" >&2
    printf '@Generated (javax or jakarta annotation[.processing]) hides every issue of its class or method\n' >&2
    printf 'from sonar-java: it belongs on generated code alone, which the root pom'"'"'s sonar.exclusions keeps\n' >&2
    printf 'out of analysis, and code there carries its generator'"'"'s header. In Java, a \\u escape for a\n' >&2
    printf 'printable ASCII character can spell @Generated or @SuppressWarnings: write the character itself. javac\n' >&2
    printf 'drops identifier-ignorable characters (U+200B, controls) from a name: the source text shown\n' >&2
    printf 'escapes every character outside printable ASCII.\n' >&2
  fi
  if [ -n "$bad" ]; then
    printf 'SONAR GATE: unjustified suppression(s) in the changed files:\n%s' "$bad" >&2
    printf 'Suppressing is allowed when Sonar is wrong, but the reason goes on the same line:\n' >&2
    printf '  // NOSONAR: <why this rule does not apply here>\n' >&2
    printf '  @SuppressWarnings("java:S1234") // <why>     (string literals only, on one line)\n' >&2
    printf '  // eslint-disable-next-line <rule> -- <why>    (stylelint the same)\n' >&2
    printf '@SuppressWarnings("all") is never accepted. Fix the finding or justify it.\n' >&2
  fi
  if [ -n "$pom_bad" ]; then
    printf 'SONAR GATE: Sonar properties that exclude, skip or narrow analysis, added without a reason:\n%s' "$pom_bad" >&2
    printf 'They hide findings the way NOSONAR does. Give each its reason in a comment: in a pom, an XML\n' >&2
    printf 'comment on its own lines or ending just above its block of adjacent suppression properties; in\n' >&2
    printf 'sonar-project.properties, a # line just above it or its block. The gate accepts them only there:\n' >&2
    printf 'move any from .mvn/maven.config or .mvn/jvm.config into a pom. A rule or value taken out of the\n' >&2
    printf 'rules file, or a .sonar-gate setting narrowed, needs a new # line there naming it and saying\n' >&2
    printf 'why; that is the owner'"'"'s call.\n' >&2
  fi
  exit 2
}

[ -z "${forbidden}${bad}${pom_bad}" ] || refuse_unjustified

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
  tell_user "Sonar gate: this change adds Sonar suppressions or changes code kept out of analysis, each with its reason:"$'\n'"$all" &&
    printf '%s\n' "$key" >"$reported_file"
}

# With scope = project a commit alone can bring a finding into view, so an unchanged diff still
# scans whenever the fingerprint, which holds the base commit, has moved.
if [ -z "$changed" ] && [ "$scope" != project ]; then
  report_suppressions
  exit 0
fi

if [ ! -x "$GATE" ]; then
  tell_user "Sonar gate: $GATE is missing or not executable; Sonar checks are OFF."
  exit 0
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
idx=$(mktemp "${TMPDIR:-/tmp}/claude-sonar-indexed.XXXXXX")
trap 'rm -f "$out" "$err" "$pat" "$idx" "$out.timeout"' EXIT
printf '%s\n' "$changed" >"$pat"
printf '%s' "$indexed" >"$idx"

gate_args=(--project-dir "$repo" --no-boot)
[ "$scope" = project ] || gate_args+=(--files "$pat")
[ -z "$indexed" ] || gate_args+=(--indexed "$idx")
timed_out="${out}.timeout"

# Claude Code cancels a Stop hook at its timeout (400 s in settings.json) and discards its
# output, which would end the turn in silence. The watchdog stops the gate first, whole process
# group, Maven included, and the timeout is reported like any other failure.
set -m
"$GATE" "${gate_args[@]}" >"$out" 2>"$err" &
gate_pid=$!
set +m
(
  trap 'kill "$nap" 2>/dev/null; exit 0' TERM
  sleep "$GATE_TIMEOUT" &
  nap=$!
  wait "$nap"
  : >"$timed_out"
  kill -TERM -- "-$gate_pid" 2>/dev/null
) &
watchdog=$!
trap 'kill -TERM -- "-$gate_pid" 2>/dev/null' TERM INT HUP
wait "$gate_pid"
status=$?
trap - TERM INT HUP
kill -TERM "$watchdog" 2>/dev/null
wait "$watchdog" 2>/dev/null
if [ -e "$timed_out" ]; then
  rm -f "$timed_out"
  tell_user "Sonar gate stopped after ${GATE_TIMEOUT}s, before Claude Code's own hook timeout; Sonar checks are OFF for this turn. Run ~/.claude/scripts/sonar-gate.sh --project-dir $repo by hand to see how long it takes."
  exit 0
fi

# A Stop hook's exit 1 shows the user only the first line of its stderr, and Claude none of it,
# so a gate that cannot run reports through a systemMessage, whole.
if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then
  tell_user "Sonar gate could not run (exit $status); Sonar checks are OFF for this turn:"$'\n'"$(tail -20 "$err")"
  exit 0
fi

gate_failed=0
grep -q '^QUALITY GATE: FAILED' "$out" && gate_failed=1
mine=$(grep -E '^[[:space:]]+[^[:space:]]+:[0-9]+ \[' "$out" || true)
more=$(grep -E '^[[:space:]]+[.][.][.] and [0-9]+ more' "$out" || true)
count=$(printf '%s' "$mine" | grep -c . || true)

if [ "$status" -eq 0 ]; then
  [ -n "$fp" ] && printf '%s\n' "$fp" >"$fp_file"
  clean
fi

rounds=$((rounds + 1))
printf '%s' "$rounds" >"$counter"

if [ "$rounds" -ge "$MAX_ROUNDS" ]; then
  rm -f "$counter"
  outstanding="$mine"
  [ -z "$more" ] || outstanding="$outstanding"$'\n'"$more"
  [ "$gate_failed" -eq 0 ] || outstanding="$(grep -A20 '^QUALITY GATE: FAILED' "$out")"$'\n'"$outstanding"
  tell_user "Sonar gate: still red after $MAX_ROUNDS attempts, so it stops blocking this turn. Outstanding:"$'\n'"$outstanding"
  exit 0
fi

printf 'SONAR GATE: new Sonar findings (attempt %s of %s)\n' "$rounds" "$MAX_ROUNDS" >&2
[ "$gate_failed" -eq 1 ] && grep -A20 '^QUALITY GATE: FAILED' "$out" >&2
[ "$count" -gt 0 ] && printf '%s\n' "$mine" >&2
[ -z "$more" ] || printf '%s\n' "$more" >&2
[ -n "${good}${pom_good}" ] &&
  printf 'Justified suppression(s) already present, report these:\n%s' "${good}${pom_good}" >&2
printf 'Fix these, or justify a suppression inline. Do not end the turn dirty.\n' >&2
exit 2
