#!/usr/bin/env bash
# Run the real SonarQube analyzers over a repository and report findings, locally.
#
# Why this exists: an agent that writes code has a deterministic oracle for correctness
# (`mvn verify`, the test runner) and none for Sonar-cleanliness, so the second property is the
# one that drifts. This is that oracle. It runs the actual Sonar ruleset — not a proxy built from
# Error Prone / SpotBugs / PMD, which between them cover almost none of the rules that actually
# fire on agent-written Java (measured: 0 of the top 5).
#
# It targets a local SonarQube container, never SonarCloud: no outward writes, no PR
# decoration, no plan limits, and analysing a feature branch cannot clobber main's record.
#
# What it analyses: the Maven project at the repository root, and the JavaScript/TypeScript
# project that `.sonar-gate` names with `js-project = DIR`, scanned with @sonar/scan from
# DIR/sonar-project.properties. Each has its own project key. A project whose inputs match its
# last analysis from here is not scanned again: its findings are read from that analysis.
#
# What counts: every issue, the ones marked accepted or false positive on the server included,
# every duplicated block in main code, and every open security hotspot, reviewed or not.
# Duplication is a measure and hotspots have their own API, so a gate that counted issues alone
# saw neither; the IDE shows hotspots.
#
# Which rules: Sonar way plus the rules listed in the file `.sonar-gate` names with
# `rules = FILE`, one `repo:key [param=value;param=value]` per line, `#` for comments.
# --provision makes the server match the repository: a profile "<repo> way" per language, a
# child of Sonar way, assigned to every project key, and on the first key (the one the IDE binds
# to in connected mode, which reads only the server's exclusions) the IDE's exclusions from
# `ide-exclusions = PATTERN, …`. Every run checks the server still matches and exits 1 when it
# does not: every listed rule active with the listed values and the defaults elsewhere, no other
# rule activated, every Sonar way rule still active, the built-in Sonar way for every other
# language, no other setting of a project key's own, and nothing that narrows analysis set at
# instance level. A green therefore never comes from another rule set than the one committed.
#
# Default mode compiles main and test sources but runs no tests. --with-coverage runs the
# full Maven build and evaluates the Maven project's quality gate, the only mode that sees
# coverage conditions.
#
# Usage:
#     sonar-gate.sh [--project-dir DIR] [--with-coverage] [--facets]
#                   [--max-findings N] [--files PATH] [--no-boot] [--dry-run] [-h|--help]
#     sonar-gate.sh --provision [--project-dir DIR] [--no-boot] [--dry-run]
#
#     --files      restrict findings to the repo-relative paths listed in PATH, one per line,
#                  and scan only the projects that hold one. The count and the exit status
#                  follow the filtered set, so a project with issues elsewhere still exits clean
#                  when the listed files are clean. Past the 10000 open issues the API serves,
#                  the set cannot be counted: exit 1.
#     --no-boot    fail instead of starting the container. For non-interactive callers,
#                  which should not have infrastructure appear underneath them.
#     --provision  make the server's profiles and project keys match the rules file, with an
#                  administrator's user token; with --dry-run, print what would change and
#                  change nothing.
#
# Environment:
#     SONAR_HOST_URL                       default http://localhost:9000
#     SONAR_TOKEN                          analysis token; overrides the Keychain lookup
#     SONAR_TOKEN_KEYCHAIN_SERVICE         default sonar-local-token
#     SONAR_ADMIN_TOKEN                    administrator's user token, for --provision and for
#                                          reading results, which an analysis token may not do
#     SONAR_ADMIN_TOKEN_KEYCHAIN_SERVICE   default sonar-local-admin-token
#     SONAR_CONTAINER                      default sonar-local
#     SONAR_IMAGE                          default sonarqube:26.8.0.126808-community
#
# Exit status: 0 clean, 1 could not run, 2 findings or a failed quality gate. The
# distinction matters — the Stop hook blocks on 2 and reports "Sonar checks are OFF" on 1.

# shellcheck disable=SC2016  # every single-quoted $name below is a jq variable (--arg, --argjson, as), not a shell one
set -euo pipefail

HOST_URL="${SONAR_HOST_URL:-http://localhost:9000}"
CONTAINER="${SONAR_CONTAINER:-sonar-local}"
IMAGE="${SONAR_IMAGE:-sonarqube:26.8.0.126808-community}"
KEYCHAIN_SERVICE="${SONAR_TOKEN_KEYCHAIN_SERVICE:-sonar-local-token}"
ADMIN_KEYCHAIN_SERVICE="${SONAR_ADMIN_TOKEN_KEYCHAIN_SERVICE:-sonar-local-admin-token}"
MAVEN_SCANNER="org.sonarsource.scanner.maven:sonar-maven-plugin:5.7.0.6970:sonar"
JS_SCANNER="@sonar/scan@5.0.1"
PARENT_PROFILE="Sonar way"
JQ=/usr/bin/jq

PROJECT_DIR=""
WITH_COVERAGE=0
SHOW_FACETS=0
MAX_FINDINGS=30
DRY_RUN=0
NO_BOOT=0
PROVISION=0
FILES_LIST=""

EXIT_CLEAN=0
EXIT_CANNOT_RUN=1
EXIT_FINDINGS=2

usage() {
  sed -n '2,/^$/{/^#/p;}' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

die() {
  printf 'sonar-gate: %s\n' "$1" >&2
  exit "${2:-$EXIT_CANNOT_RUN}"
}

log() { printf 'sonar-gate: %s\n' "$1" >&2; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help)
      usage
      exit 0
      ;;
    --project-dir)
      PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --with-coverage)
      WITH_COVERAGE=1
      shift
      ;;
    --facets)
      SHOW_FACETS=1
      shift
      ;;
    --max-findings)
      MAX_FINDINGS="${2:-30}"
      shift 2
      ;;
    --files)
      FILES_LIST="${2:-}"
      shift 2
      ;;
    --no-boot)
      NO_BOOT=1
      shift
      ;;
    --provision)
      PROVISION=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      printf 'sonar-gate: unknown argument: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$MAX_FINDINGS" in
  '' | *[!0-9]*)
    printf 'sonar-gate: --max-findings needs a whole number, not %s\n' "$MAX_FINDINGS" >&2
    exit 2
    ;;
esac

command -v "$JQ" >/dev/null 2>&1 || die "jq not found at $JQ"

FILES_JSON="null"
if [ -n "$FILES_LIST" ]; then
  [ -r "$FILES_LIST" ] || die "--files: cannot read $FILES_LIST"
  FILES_JSON=$("$JQ" -R -s -c 'split("\n") | map(select(length > 0))' <"$FILES_LIST")
fi

[ -n "$PROJECT_DIR" ] || PROJECT_DIR="$PWD"
[ -d "$PROJECT_DIR" ] || die "not a directory: $PROJECT_DIR"
ROOT=$(cd "$PROJECT_DIR" && git rev-parse --show-toplevel 2>/dev/null || echo "$PROJECT_DIR")

# ── configuration from .sonar-gate ───────────────────────────────────────────

# Prints the value of the last `KEY = value` line of .sonar-gate. A line starting with # is a
# comment, and so is any line that sets no key.
gate_setting() {
  [ -f "$ROOT/.sonar-gate" ] || return 0
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
  ' "$ROOT/.sonar-gate"
}

# A path setting names something inside the repository, in characters that a pathspec and a
# shell word both carry as they are.
check_repo_path() {
  case "$2" in
    /* | . | .. | ../* | */../* | */.. | ./*)
      die ".sonar-gate: $1 must be a path inside the repository, not $2"
      ;;
    *[!A-Za-z0-9._/-]*)
      die ".sonar-gate: $1 holds characters the gate does not accept: $2"
      ;;
  esac
}

RULES_FILE=$(gate_setting rules)
# The IDE's exclusions, comma-separated, as a JSON list.
IDE_EXCLUSIONS=$(gate_setting ide-exclusions |
  "$JQ" -R -c 'split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(. != ""))')
[ -n "$IDE_EXCLUSIONS" ] || IDE_EXCLUSIONS="[]"
JS_DIR=$(gate_setting js-project)
JS_DIR="${JS_DIR%/}"
if [ -n "$RULES_FILE" ]; then
  check_repo_path rules "$RULES_FILE"
  [ -f "$ROOT/$RULES_FILE" ] || die ".sonar-gate: rules file $RULES_FILE does not exist"
fi
if [ -n "$JS_DIR" ]; then
  check_repo_path js-project "$JS_DIR"
  [ -f "$ROOT/$JS_DIR/sonar-project.properties" ] ||
    die ".sonar-gate: js-project $JS_DIR has no sonar-project.properties"
fi

slug() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_.-' '-' | sed 's/-*$//'
}

REPO_NAME=$(basename "$ROOT")
BASE_KEY="local-$(slug "$REPO_NAME")"
PROFILE_NAME="$REPO_NAME way"

# The projects, as parallel arrays: macOS bash 3.2 has no associative arrays.
P_KIND=()
P_KEY=()
P_NAME=()
P_DIR=()
P_PREFIX=()
add_project() {
  P_KIND+=("$1")
  P_KEY+=("$2")
  P_NAME+=("$3")
  P_DIR+=("$4")
  P_PREFIX+=("$5")
}

MVN=""
if [ -f "$ROOT/pom.xml" ]; then
  add_project maven "$BASE_KEY" "$REPO_NAME" "$ROOT" ""
  if [ -x "$ROOT/mvnw" ]; then MVN="$ROOT/mvnw"; else
    command -v mvn >/dev/null 2>&1 || die "neither ./mvnw nor mvn found"
    MVN="mvn"
  fi
fi
if [ -n "$JS_DIR" ]; then
  add_project js "$BASE_KEY-$(slug "$(basename "$JS_DIR")")" "$REPO_NAME $(basename "$JS_DIR")" \
    "$ROOT/$JS_DIR" "$JS_DIR/"
fi
if [ "${#P_KIND[@]}" -eq 0 ]; then
  if [ -f "$ROOT/build.gradle" ] || [ -f "$ROOT/build.gradle.kts" ]; then
    die "Gradle projects are not supported yet (Maven only): $ROOT"
  fi
  die "no pom.xml at $ROOT and no js-project in its .sonar-gate"
fi
[ "$WITH_COVERAGE" -eq 0 ] || [ -n "$MVN" ] || die "--with-coverage needs a Maven project"

# {project key: path prefix}, to turn a component key back into a repo-relative path.
PREFIXES="{}"
i=0
while [ "$i" -lt "${#P_KIND[@]}" ]; do
  PREFIXES=$("$JQ" -c --arg k "${P_KEY[$i]}" --arg p "${P_PREFIX[$i]}" '. + {($k): $p}' <<<"$PREFIXES")
  i=$((i + 1))
done

# [{line, rule, lang, params: [{key, value}]}]; a parameter that does not parse carries `bad`.
RULES_JSON="[]"
LANGS=""
if [ -n "$RULES_FILE" ]; then
  RULES_JSON=$("$JQ" -R -s -c '
    [ split("\n") | to_entries[]
      | {line: (.key + 1), text: (.value | sub("#.*$"; "") | gsub("^\\s+|\\s+$"; ""))}
      | select(.text != "")
      | . as $e
      | (($e.text | capture("^(?<rule>\\S+)(\\s+(?<params>.*))?$")) // {rule: $e.text}) as $m
      | {line: $e.line, rule: $m.rule,
         lang: ({java: "java", typescript: "ts", javascript: "js"}[$m.rule | split(":")[0]]),
         params: (($m.params // "") | if . == "" then [] else split(";") | map(
           (capture("^(?<key>[^=]+)=(?<value>.*)$") | {key: (.key | gsub("^\\s+|\\s+$"; "")), value})
           // {bad: .}) end)} ]' "$ROOT/$RULES_FILE") || die "cannot read the rules file $RULES_FILE"
  bad=$("$JQ" -r '.[]
    | select((.rule | test("^[a-z]+:[A-Za-z0-9_]+$") | not) or .lang == null or any(.params[]; has("bad")))
    | "  line \(.line): \(.rule)"' <<<"$RULES_JSON")
  [ -z "$bad" ] || die "$RULES_FILE: lines that are not \`java:|typescript:|javascript:KEY [param=value;...]\`:
$bad"
  bad=$("$JQ" -r 'group_by(.rule)[] | select(length > 1) | "  \(.[0].rule) is listed \(length) times"' <<<"$RULES_JSON")
  [ -z "$bad" ] || die "$RULES_FILE: a rule listed twice:
$bad"
  LANGS=$("$JQ" -r '[.[].lang] | unique | .[]' <<<"$RULES_JSON")
fi
LANGS_JSON=$("$JQ" -c '[.[].lang] | unique' <<<"$RULES_JSON")

if [ "$WITH_COVERAGE" -eq 1 ]; then
  BUILD_GOAL="verify"
  GATE_ARGS=(-Dsonar.qualitygate.wait=true -Dsonar.qualitygate.timeout=300)
else
  # test-compile, not compile: most findings on agent-written Java are in test sources, and
  # the Java analyzer needs compiled test classes to see them. `compile` reports a quiet green.
  BUILD_GOAL="test-compile"
  GATE_ARGS=()
fi

if [ "$DRY_RUN" -eq 1 ] && [ "$PROVISION" -eq 0 ]; then
  printf 'would analyse : %s\n' "$ROOT"
  printf 'sonar host    : %s\n' "$HOST_URL"
  printf 'container     : %s (image %s, volumes %s-data / %s-ext)\n' "$CONTAINER" "$IMAGE" "$CONTAINER" "$CONTAINER"
  if [ -n "$RULES_FILE" ]; then
    printf 'rules         : "%s", Sonar way plus %s rules from %s\n' "$PROFILE_NAME" \
      "$("$JQ" length <<<"$RULES_JSON")" "$RULES_FILE"
  else
    printf 'rules         : whatever profiles the server assigns (no rules file)\n'
  fi
  i=0
  while [ "$i" -lt "${#P_KIND[@]}" ]; do
    case "${P_KIND[$i]}" in
      maven)
        printf 'project       : %s, Maven\n' "${P_KEY[$i]}"
        printf '  build       : %s -B -q clean %s\n' "$MVN" "$BUILD_GOAL"
        printf '  scan        : SONAR_TOKEN=… %s -B %s -Dsonar.projectKey=%s -Dsonar.host.url=%s%s\n' \
          "$MVN" "$MAVEN_SCANNER" "${P_KEY[$i]}" "$HOST_URL" "${GATE_ARGS:+ ${GATE_ARGS[*]}}"
        ;;
      js)
        printf 'project       : %s, %s/sonar-project.properties\n' "${P_KEY[$i]}" "$JS_DIR"
        printf '  scan        : (cd %s && SONAR_TOKEN=… npx --yes %s -Dsonar.projectKey=%s -Dsonar.host.url=%s)\n' \
          "${P_DIR[$i]}" "$JS_SCANNER" "${P_KEY[$i]}" "$HOST_URL"
        ;;
    esac
    i=$((i + 1))
  done
  exit "$EXIT_CLEAN"
fi

# ── the server ───────────────────────────────────────────────────────────────

sonar_status() {
  curl -s --max-time 5 "$HOST_URL/api/system/status" 2>/dev/null |
    "$JQ" -r '.status // empty' 2>/dev/null
}

ensure_sonar_up() {
  [ "$(sonar_status)" = "UP" ] && return 0

  # Booting is a foreground act with a ~20s cost and a container left running afterwards.
  # Callers that are not a person at a terminal (the Stop hook) pass --no-boot and
  # get told to run this by hand once, rather than having infrastructure appear mid-turn.
  [ "$NO_BOOT" -eq 0 ] || die "SonarQube is down at $HOST_URL, run sonar-gate.sh once to start it"

  command -v docker >/dev/null 2>&1 || die "SonarQube is not reachable at $HOST_URL and docker is not installed"
  docker info >/dev/null 2>&1 || die "SonarQube is not reachable at $HOST_URL and the docker daemon is not running"

  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    log "starting existing container $CONTAINER"
    docker start "$CONTAINER" >/dev/null
  else
    log "creating container $CONTAINER from $IMAGE"
    docker run -d --name "$CONTAINER" -p 9000:9000 \
      -v "${CONTAINER}-data:/opt/sonarqube/data" \
      -v "${CONTAINER}-ext:/opt/sonarqube/extensions" \
      "$IMAGE" >/dev/null
  fi

  log "waiting for SonarQube to come up"
  local i
  for i in $(seq 1 120); do
    [ "$(sonar_status)" = "UP" ] && {
      log "up after ~${i}s"
      return 0
    }
    sleep 1
  done
  die "SonarQube did not come up within 120s"
}

# Prints the token from $1 when set, else from the Keychain service $2.
read_token() {
  if [ -n "$1" ]; then
    printf '%s' "$1"
    return 0
  fi
  security find-generic-password -s "$2" -w 2>/dev/null
}

# The token reaches curl through a config on stdin, never through argv, which `ps` shows to
# every user. Every call is bounded, so a hung server fails the run rather than outlasting the
# Stop hook's own timeout.
api_get() { # $1 token, $2 API path, then curl arguments such as --data-urlencode k=v
  local token="$1" path="$2"
  shift 2
  printf 'user = "%s:"\n' "$token" | curl -s --max-time 60 -K - -G "$HOST_URL/$path" "$@"
}

# Fails on any answer but a 2xx, after logging the server's reason.
api_post() { # $1 token, $2 API path, then --data-urlencode k=v arguments
  local token="$1" path="$2" body code
  shift 2
  body="$SCRATCH/post-answer"
  code=$(printf 'user = "%s:"\n' "$token" |
    curl -s --max-time 60 -K - -o "$body" -w '%{http_code}' -X POST "$HOST_URL/$path" "$@") ||
    code="000"
  case "$code" in 2??) return 0 ;; esac
  log "POST $path answered $code: $("$JQ" -r '[.errors[]?.msg] | join("; ")' "$body" 2>/dev/null ||
    head -c 200 "$body")"
  return 1
}

# Prints the error messages of an API answer, or its start when it is not JSON.
server_errors() {
  "$JQ" -r '[.errors[]?.msg] | join("; ")' <<<"$1" 2>/dev/null || printf '%s' "${1:0:200}"
}

# ── the rule set ─────────────────────────────────────────────────────────────

# Prints the JSON of the profile named $3 (by default PROFILE_NAME) for language $2, `{}` when
# there is none.
profile_json() { # $1 token, $2 language, [$3 profile name]
  api_get "$1" api/qualityprofiles/search --data-urlencode "language=$2" \
    --data-urlencode "qualityProfile=${3:-$PROFILE_NAME}" |
    "$JQ" -c 'if (.profiles | type) == "array" then (.profiles[0] // {})
              else error("no profile list") end' 2>/dev/null
}

# Prints the key of the built-in parent profile for language $2. The search API answers a
# child's parent by key and leaves its name null, so parents are compared by key.
parent_key() { # $1 token, $2 language
  profile_json "$1" "$2" "$PARENT_PROFILE" | "$JQ" -r '.key // empty'
}

# Prints {rule: {inherit, params, defaults}} for every rule active in the profile $2: the values
# this profile gives its parameters, and the rule's own defaults.
active_rules() { # $1 token, $2 profile key
  local page=1 body total all="{}"
  while :; do
    body=$(api_get "$1" api/rules/search --data-urlencode "qprofile=$2" \
      --data-urlencode "activation=true" --data-urlencode "f=actives,params" \
      --data-urlencode "ps=500" --data-urlencode "p=$page") || return 1
    total=$(printf '%s' "$body" | "$JQ" -r \
      'if (.rules | type) == "array" then .total // .paging.total // "" else "" end' 2>/dev/null) ||
      total=""
    case "$total" in
      '' | *[!0-9]*)
        log "the rules API returned no rule list for profile $2"
        return 1
        ;;
    esac
    all=$(printf '%s\n%s' "$all" "$body" | "$JQ" -s -c --arg p "$2" '
      def values: map({(.key): (.value // .defaultValue // "")}) | add // {};
      (.[1].rules | map({key, value: ((.params // []) | values)}) | from_entries) as $defaults
      | .[0] + (
        [ (.[1].actives // {}) | to_entries[] | .key as $r | .value[] | select(.qProfile == $p)
          | {key: $r, value: {inherit, defaults: ($defaults[$r] // {}),
                              params: ((.params // []) | values)}} ]
        | from_entries)') || return 1
    [ $((page * 500)) -lt "$total" ] || break
    page=$((page + 1))
  done
  printf '%s' "$all"
}

# Prints, one per line and tab-separated, what keeps profile $2 from holding exactly what its
# parent $4 holds plus the rules file's rules of language $3:
#   activate <rule> <params>  a listed rule inactive, or a parameter of it off the file's value,
#                             or off the rule's default where the file names none
#   override <rule> <params>  the same for a rule Sonar way already activates: provisioning it
#                             gives that rule other parameters than Sonar way's
#   deactivate <rule>         a rule this profile activates that the file does not list
#   reset <rule>              an inherited rule whose parameters this profile overrides, unlisted
#   reactivate <rule>         a rule of the parent that this profile deactivated
profile_drift() { # $1 token, $2 profile key, $3 language, $4 parent profile key
  local active parent
  active=$(active_rules "$1" "$2") || return 1
  parent=$(active_rules "$1" "$4") || return 1
  printf '%s\n%s\n%s' "$RULES_JSON" "$active" "$parent" | "$JQ" -r -s --arg lang "$3" '
    def object: map({(.key): .value}) | add // {};
    .[1] as $active
    | .[2] as $parent
    | [.[0][] | select(.lang == $lang)] as $want
    | ($want | map(.rule)) as $listed
    | ( $want[]
        | . as $w
        | $active[$w.rule] as $a
        | select($a == null or ($a.defaults + ($w.params | object)) != ($a.defaults + $a.params))
        | "\(if $parent[$w.rule] != null then "override" else "activate" end)\t\($w.rule)\t\($w.params | map("\(.key)=\(.value)") | join(";"))" ),
      ( $active | to_entries[]
        | select(.value.inherit == "NONE" or .value.inherit == "OVERRIDES")
        | .key as $k
        | select($listed | any(. == $k) | not)
        | "\(if .value.inherit == "NONE" then "deactivate" else "reset" end)\t\(.key)\t" ),
      ( $parent | keys[]
        | . as $k
        | select($active[$k] == null and ($listed | any(. == $k) | not))
        | "reactivate\t\(.)\t" )'
}

# Prints the key of the profile project $2 uses for language $3, nothing when the project does
# not exist.
assigned_profile() { # $1 token, $2 project key, $3 language
  api_get "$1" api/qualityprofiles/search --data-urlencode "project=$2" \
    --data-urlencode "language=$3" |
    "$JQ" -r '.profiles[0].key // empty' 2>/dev/null || true
}

# The settings each project key carries, and nothing else: the first key, which the IDE binds to
# in connected mode, carries the IDE's exclusions from .sonar-gate as sonar.exclusions, and no
# key carries any other setting of its own. The root pom's sonar.exclusions overrides that value
# in the gate's Maven scan (check_ide_exclusions holds that true), so it shapes what the IDE
# shows, not the gate. sonar.test.exclusions is not given: the pom sets none, so the server's
# value would reach the gate's scan of the Java tests.
expected_settings() { # $1 project index
  if [ "$1" -eq 0 ] && [ "$IDE_EXCLUSIONS" != "[]" ]; then
    "$JQ" -n -c --argjson p "$IDE_EXCLUSIONS" '{"sonar.exclusions": $p}'
  else
    printf '{}'
  fi
}

# Settings that narrow what an analysis reads or reports, checked at instance level, where a
# value set there reaches every project and the forced sonar.global.* ones beat any scanner's.
NARROWING_KEY='^sonar[.](issue[.](ignore|enforce)[.].*|([A-Za-z0-9_-]+[.])*(exclusions|inclusions|skip|sources|tests|suffixes|maxFileSize|limit))$'

# Prints `set <key>` for each setting project $2 carries of its own off what it should, and
# `missing <key>` for each it should carry and does not. Any setting of its own counts: listing
# the narrowing ones would miss the next such key a SonarQube release adds.
settings_drift() { # $1 token, $2 project index
  local body
  body=$(api_get "$1" api/settings/values --data-urlencode "component=${P_KEY[$2]}") || return 1
  printf '%s' "$body" | "$JQ" -r --argjson want "$(expected_settings "$2")" '
    if (.settings | type) != "array" then error("no settings list") else . end
    | [ .settings[] | select(.inherited != true)
        | {key, value: (if .values then .values elif .fieldValues then .fieldValues
                        else [.value] end)} ] as $set
    | ( $set[] | select(.value != ($want[.key] // null)) | "set\t\(.key)" ),
      ( $want | keys[] | . as $k | select($set | any(.key == $k) | not) | "missing\t\(.)" )'
}

# Prints `instance <key>` for each setting that narrows analysis set at instance level.
instance_drift() { # $1 token
  api_get "$1" api/settings/values |
    "$JQ" -r --arg re "$NARROWING_KEY" '
      if (.settings | type) != "array" then error("no settings list") else . end
      | .settings[] | select(.inherited != true) | select(.key | test($re)) | "instance\t\(.key)"'
}

# The IDE's exclusions sit on the Maven project's key, where only the root pom's own
# sonar.exclusions keeps them out of the gate's scan. Without it they would narrow the gate.
check_ide_exclusions() {
  [ "$IDE_EXCLUSIONS" != "[]" ] && [ "${P_KIND[0]}" = maven ] || return 0
  command -v xmllint >/dev/null 2>&1 || die "xmllint not found; it reads the root pom's sonar.exclusions"
  [ -n "$(xmllint --xpath 'string(/*[local-name()="project"]/*[local-name()="properties"]/*[local-name()="sonar.exclusions"])' "$ROOT/pom.xml" 2>/dev/null)" ] ||
    die "the root pom sets no sonar.exclusions, so the IDE's exclusions from .sonar-gate would
  narrow the gate's Maven scan; set one in the pom, or take ide-exclusions out"
}

drift_refusal() { # $1 what differs, $2 the drift lines
  die "$1 differs from what the repository says (.sonar-gate, $RULES_FILE):
$(printf '%s\n' "$2" | tr '\t' ' ' | sed -e 's/ *$//' -e 's/^/  /')
--provision makes the server match the repository. When the repository lost a rule, a value or
an exclusion, or gives a Sonar way rule other parameters (override), that may narrow the gate:
the owner decides it before anyone provisions it."
}

# Fails unless every language of the rules file has its profile, a child of Sonar way holding its
# parent's rules plus exactly the listed ones; every project key uses those profiles, and the
# built-in Sonar way for every other language; no key carries a setting .sonar-gate does not
# give it; and the instance sets nothing that narrows analysis.
verify_profiles() { # $1 token
  [ -n "$RULES_FILE" ] || return 0
  local lang profile pkey parent drift i bad
  check_ide_exclusions
  drift=$(instance_drift "$1") || die "could not read the instance's settings"
  [ -z "$drift" ] || die "the instance sets what narrows every analysis on it:
$(printf '%s\n' "$drift" | cut -f2 | sed 's/^/  /')
An administrator set it in the server's settings; the gate does not undo it, the owner decides."
  for lang in $LANGS; do
    profile=$(profile_json "$1" "$lang") || die "could not read the $lang quality profiles"
    pkey=$("$JQ" -r '.key // empty' <<<"$profile")
    [ -n "$pkey" ] ||
      die "no $lang profile \"$PROFILE_NAME\" on the server; run: sonar-gate.sh --provision"
    parent=$(parent_key "$1" "$lang") || die "could not read the $lang quality profiles"
    [ -n "$parent" ] || die "the server has no built-in $lang profile named $PARENT_PROFILE"
    [ "$("$JQ" -r '.parentKey // empty' <<<"$profile")" = "$parent" ] ||
      die "the $lang profile \"$PROFILE_NAME\" is not a child of $PARENT_PROFILE; run: sonar-gate.sh --provision"
    drift=$(profile_drift "$1" "$pkey" "$lang" "$parent") ||
      die "could not read the rules of the $lang profile \"$PROFILE_NAME\""
    [ -z "$drift" ] || drift_refusal "the $lang profile \"$PROFILE_NAME\"" "$drift"
  done
  i=0
  while [ "$i" -lt "${#P_KIND[@]}" ]; do
    bad=$(api_get "$1" api/qualityprofiles/search --data-urlencode "project=${P_KEY[$i]}" |
      "$JQ" -r --arg name "$PROFILE_NAME" --arg parent "$PARENT_PROFILE" --argjson langs "$LANGS_JSON" '
        if (.profiles | type) != "array" then error("no profile list") else . end
        | .profiles[]
        | . as $p
        | select(if ($langs | any(. == $p.language)) then $p.name != $name
                 else ($p.isBuiltIn != true or $p.name != $parent) end)
        | "\(.language) uses \(.name)"' 2>/dev/null) ||
      die "could not read the profiles of ${P_KEY[$i]}"
    # A rules language the project falls back on a default for is assigned nothing at all.
    for lang in $LANGS; do
      [ "$(assigned_profile "$1" "${P_KEY[$i]}" "$lang")" = "$(profile_json "$1" "$lang" | "$JQ" -r '.key // empty')" ] ||
        bad="${bad:+$bad$'\n'}$lang does not use \"$PROFILE_NAME\""
    done
    [ -z "$bad" ] || die "${P_KEY[$i]} is not on the repository's profiles:
$(printf '%s\n' "$bad" | sed 's/^/  /')
run: sonar-gate.sh --provision"
    drift=$(settings_drift "$1" "$i") || die "could not read the settings of ${P_KEY[$i]}"
    [ -z "$drift" ] || drift_refusal "${P_KEY[$i]}'s settings" "$drift"
    i=$((i + 1))
  done
}

# Does what $1 says through POST $2 with the name=value pairs that follow, or with --dry-run
# says it would.
act() {
  local what="$1" path="$2" kv
  shift 2
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'would %s\n' "$what"
    return 0
  fi
  local args=()
  for kv in "$@"; do args+=(--data-urlencode "$kv"); done
  api_post "$ADMIN_TOKEN" "$path" "${args[@]}" || die "could not $what"
  printf 'did %s\n' "$what"
}

# Makes project $1's narrowing settings what expected_settings says.
provision_settings() { # $1 project index
  local drift action key k values
  drift=$(settings_drift "$ADMIN_TOKEN" "$1") || die "could not read the settings of ${P_KEY[$1]}"
  while IFS=$'\t' read -r action key; do
    [ -n "$key" ] || continue
    if [ "$("$JQ" -r --arg k "$key" 'has($k)' <<<"$(expected_settings "$1")")" = true ]; then
      values=()
      while IFS= read -r k; do values+=("values=$k"); done < <(
        "$JQ" -r --arg k "$key" '.[$k][]' <<<"$(expected_settings "$1")"
      )
      act "set $key on ${P_KEY[$1]} for the IDE" api/settings/set "key=$key" \
        "component=${P_KEY[$1]}" "${values[@]}"
    else
      act "reset $key on ${P_KEY[$1]}, which .sonar-gate does not give it" \
        api/settings/reset "keys=$key" "component=${P_KEY[$1]}"
    fi
  done < <(printf '%s\n' "$drift")
}

provision() {
  [ -n "$RULES_FILE" ] || die "--provision needs a rules file: add \`rules = FILE\` to .sonar-gate"
  ADMIN_TOKEN=$(read_token "${SONAR_ADMIN_TOKEN:-}" "$ADMIN_KEYCHAIN_SERVICE") ||
    die "no administrator token. Sign in at $HOST_URL as an administrator, mint a User token
  (not a Global Analysis Token, which cannot manage profiles) at $HOST_URL/account/security,
  and store it: security add-generic-password -s $ADMIN_KEYCHAIN_SERVICE -a \"\$USER\" -w"

  # Every listed rule and parameter exists here, so a rule's twin in another language is
  # checked against this server's catalogue rather than assumed.
  local rule keys k body missing="" lang profile pkey parent drift action params i
  while IFS=$'\t' read -r rule keys; do
    body=$(api_get "$ADMIN_TOKEN" api/rules/show --data-urlencode "key=$rule") ||
      die "could not read rule $rule"
    if ! "$JQ" -e '.rule.key' >/dev/null 2>&1 <<<"$body"; then
      missing="${missing}  $rule: no such rule on this server"$'\n'
      continue
    fi
    while IFS= read -r k; do
      [ -n "$k" ] || continue
      "$JQ" -e --arg k "$k" '(.rule.params // []) | any(.key == $k)' >/dev/null <<<"$body" ||
        missing="${missing}  $rule: no parameter \"$k\""$'\n'
    done < <(tr ';' '\n' <<<"$keys")
  done < <("$JQ" -r '.[] | "\(.rule)\t\(.params | map(.key) | join(";"))"' <<<"$RULES_JSON")
  [ -z "$missing" ] || die "$RULES_FILE lists what this server does not have:
$missing"

  for lang in $LANGS; do
    profile=$(profile_json "$ADMIN_TOKEN" "$lang") || die "could not read the $lang quality profiles"
    pkey=$("$JQ" -r '.key // empty' <<<"$profile")
    if [ -z "$pkey" ]; then
      act "create the $lang profile \"$PROFILE_NAME\"" api/qualityprofiles/create \
        "language=$lang" "name=$PROFILE_NAME"
      if [ "$DRY_RUN" -eq 1 ]; then
        printf 'would make it a child of %s and activate its %s listed rules\n' "$PARENT_PROFILE" \
          "$("$JQ" --arg l "$lang" '[.[] | select(.lang == $l)] | length' <<<"$RULES_JSON")"
        continue
      fi
      profile=$(profile_json "$ADMIN_TOKEN" "$lang") || die "could not read the $lang quality profiles"
      pkey=$("$JQ" -r '.key // empty' <<<"$profile")
      [ -n "$pkey" ] || die "the $lang profile \"$PROFILE_NAME\" was created but cannot be read back"
    fi
    parent=$(parent_key "$ADMIN_TOKEN" "$lang") || die "could not read the $lang quality profiles"
    [ -n "$parent" ] || die "the server has no built-in $lang profile named $PARENT_PROFILE"
    if [ "$("$JQ" -r '.parentKey // empty' <<<"$profile")" != "$parent" ]; then
      act "make the $lang profile \"$PROFILE_NAME\" a child of $PARENT_PROFILE" \
        api/qualityprofiles/change_parent "language=$lang" "qualityProfile=$PROFILE_NAME" \
        "parentQualityProfile=$PARENT_PROFILE"
    fi
    drift=$(profile_drift "$ADMIN_TOKEN" "$pkey" "$lang" "$parent") ||
      die "could not read the rules of the $lang profile \"$PROFILE_NAME\""
    while IFS=$'\t' read -r action rule params; do
      case "$action" in
        activate | override)
          if [ -n "$params" ]; then
            act "activate $rule ($params)" api/qualityprofiles/activate_rule "key=$pkey" \
              "rule=$rule" "params=$params"
          else
            act "activate $rule" api/qualityprofiles/activate_rule "key=$pkey" "rule=$rule"
          fi
          ;;
        deactivate)
          act "deactivate $rule, which $RULES_FILE does not list" \
            api/qualityprofiles/deactivate_rule "key=$pkey" "rule=$rule"
          ;;
        reset | reactivate)
          act "$action $rule as $PARENT_PROFILE has it" \
            api/qualityprofiles/activate_rule "key=$pkey" "rule=$rule" "reset=true"
          ;;
      esac
    done < <(printf '%s\n' "$drift" | grep -v '^$' || true)
  done

  i=0
  while [ "$i" -lt "${#P_KIND[@]}" ]; do
    body=$(api_get "$ADMIN_TOKEN" api/projects/search --data-urlencode "projects=${P_KEY[$i]}") ||
      die "could not look up project ${P_KEY[$i]}"
    case "$("$JQ" -r '.components | if type == "array" then length else "?" end' <<<"$body" 2>/dev/null)" in
      0)
        act "create the project ${P_KEY[$i]}" api/projects/create "project=${P_KEY[$i]}" \
          "name=${P_NAME[$i]}"
        ;;
      1) ;;
      *) die "the projects API returned no component list for ${P_KEY[$i]}" ;;
    esac
    for lang in $LANGS; do
      profile=$(profile_json "$ADMIN_TOKEN" "$lang") || die "could not read the $lang quality profiles"
      pkey=$("$JQ" -r '.key // empty' <<<"$profile")
      if [ -z "$pkey" ] || [ "$(assigned_profile "$ADMIN_TOKEN" "${P_KEY[$i]}" "$lang")" != "$pkey" ]; then
        act "assign the $lang profile \"$PROFILE_NAME\" to ${P_KEY[$i]}" \
          api/qualityprofiles/add_project "language=$lang" "qualityProfile=$PROFILE_NAME" \
          "project=${P_KEY[$i]}"
      fi
    done
    if [ "$DRY_RUN" -eq 0 ] || [ "$("$JQ" -r '.components | length' <<<"$body")" = 1 ]; then
      provision_settings "$i"
    fi
    i=$((i + 1))
  done

  if [ "$DRY_RUN" -eq 1 ]; then
    log "dry run: nothing changed on $HOST_URL"
  else
    verify_profiles "$ADMIN_TOKEN"
    log "the server matches .sonar-gate and $RULES_FILE"
  fi
}

# ── analysis ─────────────────────────────────────────────────────────────────

# Prints a hash of what an analysis of project $1 reads: the commit, the uncommitted and
# untracked changes under the project's paths, the rules file and .sonar-gate, this script, the
# build mode, the server's version and its stamp on the project's profiles. Fails outside git.
inputs_fp() {
  local spec=()
  if [ "${P_KIND[$1]}" = js ]; then spec=("$JS_DIR"); else
    spec=(.)
    [ -z "$JS_DIR" ] || spec+=(":(exclude)$JS_DIR")
  fi
  (
    set -o pipefail
    {
      if git -C "$ROOT" rev-parse --verify --quiet 'HEAD^{commit}'; then
        git -C "$ROOT" diff --no-ext-diff --no-textconv --binary HEAD -- "${spec[@]}"
      else
        echo unborn
      fi &&
        git -C "$ROOT" ls-files --others --exclude-standard -z -- "${spec[@]}" |
        while IFS= read -r -d '' f; do
          printf '%s ' "$f"
          git -C "$ROOT" hash-object -- "$f" || exit 1
        done &&
        { [ -z "$RULES_FILE" ] || cat "$ROOT/$RULES_FILE"; } &&
        { [ ! -f "$ROOT/.sonar-gate" ] || cat "$ROOT/.sonar-gate"; } &&
        cat "${BASH_SOURCE[0]}" &&
        printf '%s %s %s\n' "$BUILD_GOAL" "$MAVEN_SCANNER" "$JS_SCANNER" &&
        curl -s --max-time 5 "$HOST_URL/api/server/version" &&
        api_get "$READ_TOKEN" api/qualityprofiles/search --data-urlencode "project=${P_KEY[$1]}" |
        "$JQ" -c '[.profiles[] | [.key, .rulesUpdatedAt]]'
    } | shasum -a 256 | cut -d' ' -f1
  )
}

state_file() { printf '%s/sonar-gate-analysed-%s' "${TMPDIR:-/tmp}" "$1"; }

last_analysis() { # $1 project key; prints the key of its latest analysis, nothing when none
  api_get "$READ_TOKEN" api/project_analyses/search --data-urlencode "project=$1" \
    --data-urlencode "ps=1" | "$JQ" -r '.analyses[0].key // empty' 2>/dev/null || true
}

# Fresh: the server's latest analysis of project $1 is the one this script ran for the inputs
# fingerprinted $2, by its analysis key, so another run's analysis never passes for it.
is_fresh() {
  local file saved_fp saved_analysis
  file=$(state_file "${P_KEY[$1]}")
  [ -n "$2" ] && [ -f "$file" ] || return 1
  read -r saved_fp saved_analysis <"$file" || return 1
  [ "$saved_fp" = "$2" ] && [ -n "$saved_analysis" ] &&
    [ "$saved_analysis" = "$(last_analysis "${P_KEY[$1]}")" ]
}

record_analysis() { # $1 project index, $2 the fingerprint taken before its scan
  [ -n "$2" ] && [ -n "$LAST_ANALYSIS" ] || return 0
  printf '%s %s\n' "$2" "$LAST_ANALYSIS" >"$(state_file "${P_KEY[$1]}")"
}

# The issues API answers from the last *completed* analysis, so reading it before this one has
# finished reports the previous analysis's findings — and the Stop hook remembers a green
# answer. Both ways of not waiting therefore fail instead of falling through. Sets LAST_ANALYSIS
# to the analysis this task produced.
LAST_ANALYSIS=""
wait_for_analysis() { # $1 report-task.txt, $2 project key
  local ce st="" task
  LAST_ANALYSIS=""
  ce=$(grep '^ceTaskId=' "$1" 2>/dev/null | cut -d= -f2 || true)
  [ -n "$ce" ] || die "no ceTaskId in $1; cannot wait for the analysis of $2"
  for _ in $(seq 1 150); do
    task=$(api_get "$READ_TOKEN" api/ce/task --data-urlencode "id=$ce")
    st=$("$JQ" -r '.task.status // empty' <<<"$task")
    case "$st" in
      SUCCESS)
        LAST_ANALYSIS=$("$JQ" -r '.task.analysisId // empty' <<<"$task")
        return 0
        ;;
      FAILED | CANCELED) die "server-side processing $st for $2" ;;
    esac
    sleep 2
  done
  die "analysis $ce of $2 still ${st:-unknown} after 300s"
}

# Prints `-u NAME` for every exported variable a scanner would read analysis properties from.
scanner_env_unset() {
  local name
  for name in $(compgen -e); do
    case "$name" in
      SONAR* | npm_config_sonar* | MAVEN_OPTS | MAVEN_ARGS) printf '%s\n' -u "$name" ;;
    esac
  done
}

scan_maven() { # $1 project index
  # `clean` is not optional: without it the compiler plugin skips recompilation, the analyzers
  # see nothing, and the scan reports green on code it never read.
  log "building ($BUILD_GOAL) and scanning ${P_KEY[$1]}"
  local unset=()
  while IFS= read -r arg; do unset+=("$arg"); done < <(scanner_env_unset)
  if ! env ${unset[@]+"${unset[@]}"} "$MVN" -B -q -f "$ROOT/pom.xml" clean "$BUILD_GOAL" >"$SCRATCH/build.log" 2>&1; then
    tail -30 "$SCRATCH/build.log" >&2
    die "build failed before analysis could run"
  fi
  # sonar.organization is blanked because the project pom may set it for SonarCloud, where it
  # is required and here it is rejected.
  if ! env ${unset[@]+"${unset[@]}"} SONAR_TOKEN="$TOKEN" "$MVN" -B -f "$ROOT/pom.xml" "$MAVEN_SCANNER" \
    -Dsonar.host.url="$HOST_URL" \
    -Dsonar.projectKey="${P_KEY[$1]}" \
    -Dsonar.projectName="${P_NAME[$1]}" \
    -Dsonar.organization= \
    ${GATE_ARGS[@]+"${GATE_ARGS[@]}"} >"$SCRATCH/build.log" 2>&1; then
    if grep -q 'QUALITY GATE STATUS: FAILED' "$SCRATCH/build.log"; then
      log "quality gate FAILED"
    else
      tail -30 "$SCRATCH/build.log" >&2
      die "scanner failed on ${P_KEY[$1]}"
    fi
  fi
  wait_for_analysis "$ROOT/target/sonar/report-task.txt" "${P_KEY[$1]}"
}

scan_js() { # $1 project index
  command -v npx >/dev/null 2>&1 || die "npx not found; the JavaScript scanner runs through it"
  local work="$SCRATCH/js-work" unset=()
  while IFS= read -r arg; do unset+=("$arg"); done < <(scanner_env_unset)
  log "scanning ${P_KEY[$1]} with $JS_SCANNER"
  if ! (cd "$SCRATCH" && env ${unset[@]+"${unset[@]}"} SONAR_TOKEN="$TOKEN" npx --yes "$JS_SCANNER" \
    -Dsonar.projectBaseDir="${P_DIR[$1]}" \
    -Dsonar.host.url="$HOST_URL" \
    -Dsonar.projectKey="${P_KEY[$1]}" \
    -Dsonar.projectName="${P_NAME[$1]}" \
    -Dsonar.working.directory="$work") >"$SCRATCH/build.log" 2>&1; then
    tail -30 "$SCRATCH/build.log" >&2
    die "scanner failed on ${P_KEY[$1]}"
  fi
  wait_for_analysis "$work/report-task.txt" "${P_KEY[$1]}"
}

# Prints [{path, line, rule, message, rank}], one per block of a file in project $1 that Sonar
# found duplicated, limited to the --files list when there is one.
duplication_findings() {
  local page=1 body total out="[]" file answer
  while :; do
    body=$(api_get "$READ_TOKEN" api/measures/component_tree --data-urlencode "component=${P_KEY[$1]}" \
      --data-urlencode "metricKeys=duplicated_blocks" --data-urlencode "qualifiers=FIL" \
      --data-urlencode "ps=500" --data-urlencode "p=$page") ||
      die "could not read the duplications of ${P_KEY[$1]}"
    total=$(printf '%s' "$body" | "$JQ" -r \
      'if (.components | type) == "array" then .paging.total // "" else "" end' 2>/dev/null) ||
      total=""
    case "$total" in
      '' | *[!0-9]*)
        die "the measures API returned no component list for ${P_KEY[$1]}: $(server_errors "$body").
  Reading duplications needs Browse permission, which an analysis token lacks: store an
  administrator's user token as $ADMIN_KEYCHAIN_SERVICE (see --help)."
        ;;
    esac
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      answer=$(api_get "$READ_TOKEN" api/duplications/show --data-urlencode "key=$file") ||
        die "could not read the duplications of $file"
      out=$(printf '%s\n%s' "$out" "$answer" | "$JQ" -s -c --arg key "$file" --argjson pre "$PREFIXES" '
        def path: ($pre[split(":")[0]] // "") + sub("^[^:]*:"; "");
        .[1] as $d
        | if ($d.duplications | type) != "array" then error("no duplication list") else . end
        | .[0] + [ $d.duplications[].blocks as $blocks
                   | $blocks[] | select($d.files[._ref].key == $key) | . as $self
                   | ([$blocks[] | select(. != $self)][0]) as $other
                   | select($other != null)
                   | {path: ($key | path), line: $self.from, rule: "duplication", rank: 2,
                      message: "\($self.size) lines duplicated at \($d.files[$other._ref].key | path):\($other.from)"} ]') ||
        die "the duplications API returned no duplication list for $file"
    done < <(printf '%s' "$body" | "$JQ" -r --argjson files "$FILES_JSON" --argjson pre "$PREFIXES" '
      .components[]
      | select(((.measures[0].value // "0") | tonumber) > 0)
      | select($files == null
               or ((($pre[.key | split(":")[0]] // "") + (.key | sub("^[^:]*:"; ""))) as $p
                   | $files | index($p)) != null)
      | .key')
    [ $((page * 500)) -lt "$total" ] || break
    page=$((page + 1))
  done
  printf '%s' "$out"
}

# Prints [{path, line, rule, message, rank}], one per security hotspot of project $1 that is still
# open, limited to the --files list when there is one. A hotspot reviewed on the server still
# counts, as an accepted issue does: a reason belongs in the code, as a justified NOSONAR.
hotspot_findings() {
  local page=1 body total out="[]"
  while :; do
    body=$(api_get "$READ_TOKEN" api/hotspots/search --data-urlencode "projectKey=${P_KEY[$1]}" \
      --data-urlencode "ps=500" --data-urlencode "p=$page") ||
      die "could not read the security hotspots of ${P_KEY[$1]}"
    total=$(printf '%s' "$body" | "$JQ" -r \
      'if (.hotspots | type) == "array" then .paging.total // "" else "" end' 2>/dev/null) ||
      total=""
    case "$total" in
      '' | *[!0-9]*)
        die "the hotspots API returned no hotspot list for ${P_KEY[$1]}: $(server_errors "$body")"
        ;;
    esac
    out=$(printf '%s\n%s' "$out" "$body" | "$JQ" -s -c --argjson files "$FILES_JSON" --argjson pre "$PREFIXES" '
      .[0] + [ .[1].hotspots[]
        | . + {path: (($pre[.component | split(":")[0]] // "") + (.component | sub("^[^:]*:"; "")))}
        | select($files == null or (.path as $p | $files | index($p)) != null)
        | {path, line, rule: (.ruleKey // "hotspot"), rank: 1,
           message: ("security hotspot: " + .message
             + (if .status == "REVIEWED" then " (reviewed \(.resolution // "") on the server, which the gate does not accept)"
                else "" end))} ]')
    [ $((page * 500)) -lt "$total" ] || break
    page=$((page + 1))
  done
  printf '%s' "$out"
}

# ── main ─────────────────────────────────────────────────────────────────────

ensure_sonar_up

# Templated, because macOS mktemp ignores $TMPDIR and its default directory is closed under
# the Bash sandbox.
SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/sonar-gate.XXXXXX")
# shellcheck disable=SC2329  # invoked by the EXIT trap below
cleanup() {
  case "$SCRATCH" in
    "${TMPDIR:-/tmp}"/sonar-gate.* | "${TMPDIR%/}"/sonar-gate.*) rm -rf "$SCRATCH" ;;
  esac
}
trap cleanup EXIT

if [ "$PROVISION" -eq 1 ]; then
  provision
  exit "$EXIT_CLEAN"
fi

TOKEN=$(read_token "${SONAR_TOKEN:-}" "$KEYCHAIN_SERVICE") || die "no analysis token. Set SONAR_TOKEN, or store one:
    security add-generic-password -s $KEYCHAIN_SERVICE -a \"\$USER\" -w
  Mint it at $HOST_URL/account/security (type: Global Analysis Token)."

# The analysis token runs scans and nothing else: the measures and duplications APIs refuse it
# for want of Browse permission. Reads use the administrator's user token when the Keychain
# holds one, which --provision needs anyway.
READ_TOKEN=$(read_token "${SONAR_ADMIN_TOKEN:-}" "$ADMIN_KEYCHAIN_SERVICE") || READ_TOKEN="$TOKEN"

verify_profiles "$READ_TOKEN"

# With --files, only the projects holding a listed file matter.
RELEVANT=()
P_ANALYSIS=()
KEYS=""
MAVEN_KEY=""
i=0
while [ "$i" -lt "${#P_KIND[@]}" ]; do
  holds="true"
  if [ -n "$FILES_LIST" ]; then
    holds=$("$JQ" -r --arg p "${P_PREFIX[$i]}" --arg js "${JS_DIR:+$JS_DIR/}" --arg kind "${P_KIND[$i]}" '
      any(.[]; if $kind == "js" then startswith($p) else ($js == "" or (startswith($js) | not)) end)' \
      <<<"$FILES_JSON")
  fi
  if [ "$holds" = "true" ]; then
    RELEVANT+=("$i")
    KEYS="${KEYS:+$KEYS,}${P_KEY[$i]}"
    [ "${P_KIND[$i]}" != maven ] || MAVEN_KEY="${P_KEY[$i]}"
  fi
  i=$((i + 1))
done

if [ "${#RELEVANT[@]}" -eq 0 ]; then
  log "clean: no listed file belongs to a project here"
  exit "$EXIT_CLEAN"
fi

for i in "${RELEVANT[@]}"; do
  fp=$(inputs_fp "$i" 2>/dev/null) || fp=""
  if [ "${P_KIND[$i]}" != maven ] || [ "$WITH_COVERAGE" -eq 0 ]; then
    if is_fresh "$i" "$fp"; then
      log "${P_KEY[$i]} is unchanged since its last analysis from here; reading that one"
      P_ANALYSIS[i]=$(cut -d' ' -f2 <"$(state_file "${P_KEY[$i]}")")
      continue
    fi
  fi
  case "${P_KIND[$i]}" in
    maven) scan_maven "$i" ;;
    js) scan_js "$i" ;;
  esac
  record_analysis "$i" "$fp"
  P_ANALYSIS[i]="$LAST_ANALYSIS"
done

api_issues() {
  api_get "$READ_TOKEN" api/issues/search --data-urlencode "components=$KEYS" \
    --data-urlencode "issueStatuses=OPEN,CONFIRMED,ACCEPTED,FALSE_POSITIVE,IN_SANDBOX" "$@"
}

# A page holds 500 issues. With --files the count is taken after filtering, so a finding in a
# listed file on page 2 would be invisible: read every page, up to the 10000 issues the API
# serves, and refuse to count past that. Without --files, read as many pages as the listing
# shows. An answer with no issue list or no whole-number total is an error, not "0".
page=1
while :; do
  body=$(api_issues --data-urlencode "ps=500" --data-urlencode "p=$page")
  served=$(printf '%s' "$body" | "$JQ" -r \
    'if (.issues | type) == "array" then .paging.total // .total // "" else "" end' 2>/dev/null) ||
    served=""
  case "$served" in
    '' | *[!0-9]*) die "the issues API returned no issue list or total for $KEYS (page $page)" ;;
  esac
  printf '%s\n' "$body" >>"$SCRATCH/pages"
  if [ -n "$FILES_LIST" ]; then
    [ "$served" -le 10000 ] ||
      die "$served open issues on $KEYS and the API serves only 10000, so --files cannot be counted"
  else
    [ $((page * 500)) -lt "$MAX_FINDINGS" ] && [ "$page" -lt 20 ] || break
  fi
  [ $((page * 500)) -lt "$served" ] || break
  page=$((page + 1))
done

# Every finding as {path, line, rule, message, rank}, the path repo-relative so that --files and
# the listing agree. The select runs before sort_by and the cap: filtering after them drops a
# listed file's finding whenever more than MAX_FINDINGS issues outrank it, and reports clean.
"$JQ" -s --argjson files "$FILES_JSON" --argjson pre "$PREFIXES" '
  {total: (.[0].paging.total // .[0].total),
   findings: [ map(.issues) | add | .[]
     | . + {path: (($pre[.component | split(":")[0]] // "") + (.component | sub("^[^:]*:"; "")))}
     | select($files == null or (.path as $p | $files | index($p)) != null)
     | {path, line, rule,
        message: (.message + (if (.issueStatus // "") | test("^(ACCEPTED|FALSE_POSITIVE)$")
          then " (marked \(.issueStatus) on the server, which the gate does not accept)" else "" end)),
        rank: ((.impacts[0].severity // "MEDIUM") as $s
          | if   $s == "BLOCKER" then 0 elif $s == "HIGH" then 1
            elif $s == "MEDIUM"  then 2 elif $s == "LOW"  then 3 else 4 end)} ]}' \
  "$SCRATCH/pages" >"$SCRATCH/issues.json"

dups="[]"
for i in "${RELEVANT[@]}"; do
  more=$(duplication_findings "$i")
  dups=$(printf '%s\n%s' "$dups" "$more" | "$JQ" -s -c 'add')
done
DUP_COUNT=$("$JQ" length <<<"$dups")

hotspots="[]"
for i in "${RELEVANT[@]}"; do
  more=$(hotspot_findings "$i")
  hotspots=$(printf '%s\n%s' "$hotspots" "$more" | "$JQ" -s -c 'add')
done
HOTSPOT_COUNT=$("$JQ" length <<<"$hotspots")

# The reads above take a while, and another run's analysis of the same key could land in the
# meantime: the findings read would then be partly its.
for i in "${RELEVANT[@]}"; do
  [ -z "${P_ANALYSIS[i]:-}" ] || [ "$(last_analysis "${P_KEY[$i]}")" = "${P_ANALYSIS[i]}" ] ||
    die "another analysis of ${P_KEY[$i]} landed while its findings were read; run the gate again"
done

# With --files the count is of the listed files alone, so "0 findings in what you touched"
# exits clean even while the project carries findings elsewhere. Without it, the server's own
# issue total stands, which is not capped by the pages read.
if [ -n "$FILES_LIST" ]; then
  ISSUE_COUNT=$("$JQ" '.findings | length' "$SCRATCH/issues.json")
else
  ISSUE_COUNT=$("$JQ" -r '.total // 0' "$SCRATCH/issues.json")
fi
TOTAL=$((ISSUE_COUNT + DUP_COUNT + HOTSPOT_COUNT))

if [ "$SHOW_FACETS" -eq 1 ]; then
  api_issues --data-urlencode "facets=rules,impactSeverities,impactSoftwareQualities" \
    --data-urlencode "ps=1" |
    "$JQ" -r '.facets[]? | "-- \(.property) --",
                (.values[]? | select(.count > 0) | "  \(.count)\t\(.val)")'
  printf -- '-- duplications --\n  %s\tduplicated blocks\n' "$DUP_COUNT"
  printf -- '-- security hotspots --\n  %s\thotspots\n' "$HOTSPOT_COUNT"
fi

# A gate can fail on conditions no issue represents, such as coverage, so issue count alone is
# not a verdict. Only evaluated with --with-coverage: without a test run the coverage condition
# is 0% and would fail every default-mode scan.
GATE_FAILED=0
if [ "$WITH_COVERAGE" -eq 1 ] && [ -n "$MAVEN_KEY" ]; then
  gate=$(api_get "$READ_TOKEN" api/qualitygates/project_status --data-urlencode "projectKey=$MAVEN_KEY")
  if [ "$(printf '%s' "$gate" | "$JQ" -r '.projectStatus.status // empty')" = "ERROR" ]; then
    GATE_FAILED=1
    echo "QUALITY GATE: FAILED"
    printf '%s' "$gate" | "$JQ" -r '.projectStatus.conditions[]?
      | select(.status == "ERROR")
      | "  \(.metricKey) is \(.actualValue), needs \(.comparator | ascii_downcase) \(.errorThreshold)"'
  fi
fi

if [ "$TOTAL" -eq 0 ] && [ "$GATE_FAILED" -eq 0 ]; then
  log "clean: 0 findings on $KEYS"
  exit "$EXIT_CLEAN"
fi

if [ "$TOTAL" -eq 0 ]; then
  log "0 findings, but the quality gate failed on $MAVEN_KEY"
  exit "$EXIT_FINDINGS"
fi

if [ "$SHOW_FACETS" -eq 0 ]; then
  "$JQ" -r --argjson dups "$dups" --argjson hotspots "$hotspots" --argjson n "$MAX_FINDINGS" '
    (.findings + $dups + $hotspots) | sort_by(.rank)[:$n][]
    | "  \(.path):\(.line // 0) [\(.rule)] \(.message)"' "$SCRATCH/issues.json"
  if [ "$TOTAL" -gt "$MAX_FINDINGS" ]; then
    printf '  ... and %s more. Full list: %s/project/issues?id=%s\n' \
      "$((TOTAL - MAX_FINDINGS))" "$HOST_URL" "${KEYS%%,*}"
  fi
fi

log "$TOTAL finding(s) on $KEYS ($ISSUE_COUNT issue(s), $DUP_COUNT duplicated block(s), $HOTSPOT_COUNT security hotspot(s))"
exit "$EXIT_FINDINGS"
