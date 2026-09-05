#!/usr/bin/env bash
# Run the real SonarQube analyzers over a Maven project and report findings, locally.
#
# Why this exists: an agent that writes Java has a deterministic oracle for correctness
# (`mvn verify`) and none for Sonar-cleanliness, so the second property is the one that
# drifts. This is that oracle. It runs the actual Sonar ruleset — not a proxy built from
# Error Prone / SpotBugs / PMD, which between them cover almost none of the rules that
# actually fire on agent-written Java (measured: 0 of the top 5).
#
# It targets a local SonarQube container, never SonarCloud: no outward writes, no PR
# decoration, no plan limits, and analysing a feature branch cannot clobber main's record.
#
# Default mode compiles main and test sources but runs no tests. --with-coverage runs the
# full build and evaluates the quality gate, which is the only mode that sees coverage
# conditions.
#
# Usage:
#     sonar-gate.sh [--project-dir DIR] [--with-coverage] [--facets]
#                   [--max-findings N] [--no-boot] [--dry-run] [-h|--help]
#
#     --no-boot   fail instead of starting the container. For non-interactive callers,
#                 which should not have infrastructure appear underneath them.
#
# Environment:
#     SONAR_HOST_URL                  default http://localhost:9000
#     SONAR_TOKEN                     analysis token; overrides the Keychain lookup
#     SONAR_TOKEN_KEYCHAIN_SERVICE    default sonar-local-token
#     SONAR_CONTAINER                 default sonar-local
#     SONAR_IMAGE                     default sonarqube:26.8.0.126808-community
#
# Exit status: 0 clean, 1 could not run, 2 findings or a failed quality gate. The
# distinction matters — the SubagentStop hook blocks on 2 and reports "gate is OFF" on 1.

set -euo pipefail

HOST_URL="${SONAR_HOST_URL:-http://localhost:9000}"
CONTAINER="${SONAR_CONTAINER:-sonar-local}"
IMAGE="${SONAR_IMAGE:-sonarqube:26.8.0.126808-community}"
KEYCHAIN_SERVICE="${SONAR_TOKEN_KEYCHAIN_SERVICE:-sonar-local-token}"
SCANNER="org.sonarsource.scanner.maven:sonar-maven-plugin:5.7.0.6970:sonar"

PROJECT_DIR=""
WITH_COVERAGE=0
SHOW_FACETS=0
MAX_FINDINGS=30
DRY_RUN=0
NO_BOOT=0

EXIT_CLEAN=0
EXIT_CANNOT_RUN=1
EXIT_FINDINGS=2

usage() {
  sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

die() {
  printf 'sonar-gate: %s\n' "$1" >&2
  exit "${2:-$EXIT_CANNOT_RUN}"
}

log() { printf 'sonar-gate: %s\n' "$1" >&2; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)      usage; exit 0 ;;
    --project-dir)  PROJECT_DIR="${2:-}"; shift 2 ;;
    --with-coverage) WITH_COVERAGE=1; shift ;;
    --facets)       SHOW_FACETS=1; shift ;;
    --max-findings) MAX_FINDINGS="${2:-30}"; shift 2 ;;
    --no-boot)      NO_BOOT=1; shift ;;
    --dry-run)      DRY_RUN=1; shift ;;
    *)              printf 'sonar-gate: unknown argument: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v /usr/bin/jq >/dev/null 2>&1 || die "jq not found at /usr/bin/jq"

[ -n "$PROJECT_DIR" ] || PROJECT_DIR="$PWD"
[ -d "$PROJECT_DIR" ] || die "not a directory: $PROJECT_DIR"
ROOT=$(cd "$PROJECT_DIR" && git rev-parse --show-toplevel 2>/dev/null || echo "$PROJECT_DIR")

if [ ! -f "$ROOT/pom.xml" ]; then
  if [ -f "$ROOT/build.gradle" ] || [ -f "$ROOT/build.gradle.kts" ]; then
    die "Gradle projects are not supported yet (Maven only): $ROOT"
  fi
  die "no pom.xml at $ROOT"
fi

PROJECT_KEY="local-$(basename "$ROOT" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_.-' '-' | sed 's/-*$//')"

if [ -x "$ROOT/mvnw" ]; then MVN="$ROOT/mvnw"; else
  command -v mvn >/dev/null 2>&1 || die "neither ./mvnw nor mvn found"
  MVN="mvn"
fi

if [ "$WITH_COVERAGE" -eq 1 ]; then
  BUILD_GOAL="verify"
  GATE_ARGS=(-Dsonar.qualitygate.wait=true -Dsonar.qualitygate.timeout=300)
else
  # test-compile, not compile: most findings on agent-written Java are in test sources, and
  # the Java analyzer needs compiled test classes to see them. `compile` reports a quiet green.
  BUILD_GOAL="test-compile"
  GATE_ARGS=()
fi

if [ "$DRY_RUN" -eq 1 ]; then
  cat <<EOF
would analyse : $ROOT
project key   : $PROJECT_KEY
sonar host    : $HOST_URL
container     : $CONTAINER (image $IMAGE, volumes ${CONTAINER}-data / ${CONTAINER}-ext)
build         : $MVN -B -q clean $BUILD_GOAL
scan          : $MVN -B $SCANNER -Dsonar.projectKey=$PROJECT_KEY -Dsonar.host.url=$HOST_URL${GATE_ARGS:+ ${GATE_ARGS[*]}}
EOF
  exit "$EXIT_CLEAN"
fi

sonar_status() {
  curl -s --max-time 5 "$HOST_URL/api/system/status" 2>/dev/null \
    | /usr/bin/jq -r '.status // empty' 2>/dev/null
}

ensure_sonar_up() {
  [ "$(sonar_status)" = "UP" ] && return 0

  # Booting is a foreground act with a ~20s cost and a container left running afterwards.
  # Callers that are not a person at a terminal (the SubagentStop hook) pass --no-boot and
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
    [ "$(sonar_status)" = "UP" ] && { log "up after ~${i}s"; return 0; }
    sleep 1
  done
  die "SonarQube did not come up within 120s"
}

resolve_token() {
  if [ -n "${SONAR_TOKEN:-}" ]; then printf '%s' "$SONAR_TOKEN"; return 0; fi
  security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null && return 0
  die "no analysis token. Set SONAR_TOKEN, or store one:
    security add-generic-password -s $KEYCHAIN_SERVICE -a \"\$USER\" -w
  Mint it at $HOST_URL/account/security (type: Global Analysis Token)."
}

ensure_sonar_up
TOKEN=$(resolve_token)

# `clean` is not optional: without it the compiler plugin skips recompilation, the analyzers
# see nothing, and the scan reports green on code it never read.
log "building ($BUILD_GOAL) and scanning $PROJECT_KEY"
build_log=$(mktemp)
trap 'rm -f "$build_log"' EXIT

if ! "$MVN" -B -q -f "$ROOT/pom.xml" clean "$BUILD_GOAL" >"$build_log" 2>&1; then
  tail -30 "$build_log" >&2
  die "build failed before analysis could run"
fi

# sonar.organization is blanked because the project pom may set it for SonarCloud, where it is
# required and here it is rejected.
if ! "$MVN" -B -f "$ROOT/pom.xml" "$SCANNER" \
      -Dsonar.token="$TOKEN" \
      -Dsonar.host.url="$HOST_URL" \
      -Dsonar.projectKey="$PROJECT_KEY" \
      -Dsonar.projectName="$(basename "$ROOT")" \
      -Dsonar.organization= \
      ${GATE_ARGS[@]+"${GATE_ARGS[@]}"} >"$build_log" 2>&1; then
  if grep -q 'QUALITY GATE STATUS: FAILED' "$build_log"; then
    log "quality gate FAILED"
  else
    tail -30 "$build_log" >&2
    die "scanner failed"
  fi
fi

CE=$(grep '^ceTaskId=' "$ROOT/target/sonar/report-task.txt" 2>/dev/null | cut -d= -f2 || true)
if [ -n "$CE" ]; then
  for _ in $(seq 1 150); do
    st=$(curl -s -u "$TOKEN:" "$HOST_URL/api/ce/task?id=$CE" | /usr/bin/jq -r '.task.status // empty')
    case "$st" in
      SUCCESS) break ;;
      FAILED|CANCELED) die "server-side processing $st" ;;
    esac
    sleep 2
  done
fi

api_issues() {
  curl -s -u "$TOKEN:" -G "$HOST_URL/api/issues/search" \
    --data-urlencode "components=$PROJECT_KEY" \
    --data-urlencode "issueStatuses=OPEN,CONFIRMED" \
    "$@"
}

TOTAL=$(api_issues --data-urlencode "ps=1" | /usr/bin/jq -r '.total // 0')

if [ "$SHOW_FACETS" -eq 1 ]; then
  api_issues --data-urlencode "facets=rules,impactSeverities,impactSoftwareQualities" \
             --data-urlencode "ps=1" \
    | /usr/bin/jq -r '.facets[]? | "-- \(.property) --",
                      (.values[]? | select(.count > 0) | "  \(.count)\t\(.val)")'
fi

# A gate can fail on conditions no issue represents — coverage and duplication are metrics,
# not findings — so issue count alone is not a verdict. Only evaluated with --with-coverage:
# without a test run the coverage condition is 0% and would fail every default-mode scan.
GATE_FAILED=0
if [ "$WITH_COVERAGE" -eq 1 ]; then
  gate=$(curl -s -u "$TOKEN:" -G "$HOST_URL/api/qualitygates/project_status" \
           --data-urlencode "projectKey=$PROJECT_KEY")
  if [ "$(printf '%s' "$gate" | /usr/bin/jq -r '.projectStatus.status // empty')" = "ERROR" ]; then
    GATE_FAILED=1
    echo "QUALITY GATE: FAILED"
    printf '%s' "$gate" | /usr/bin/jq -r '.projectStatus.conditions[]?
      | select(.status == "ERROR")
      | "  \(.metricKey) is \(.actualValue), needs \(.comparator | ascii_downcase) \(.errorThreshold)"'
  fi
fi

if [ "$TOTAL" -eq 0 ] && [ "$GATE_FAILED" -eq 0 ]; then
  log "clean: 0 issues on $PROJECT_KEY"
  exit "$EXIT_CLEAN"
fi

if [ "$TOTAL" -eq 0 ]; then
  log "0 issues, but the quality gate failed on $PROJECT_KEY"
  exit "$EXIT_FINDINGS"
fi

if [ "$SHOW_FACETS" -eq 0 ]; then
  api_issues --data-urlencode "ps=500" \
    | /usr/bin/jq -r --argjson n "$MAX_FINDINGS" '
        [ .issues[]
          | . + {rank: ((.impacts[0].severity // "MEDIUM") as $s
              | if   $s == "BLOCKER" then 0 elif $s == "HIGH"   then 1
                elif $s == "MEDIUM"  then 2 elif $s == "LOW"    then 3 else 4 end)} ]
        | sort_by(.rank)[:$n][]
        | "  \(.component | split(":") | last):\(.line // 0) [\(.rule)] \(.message)"'
  if [ "$TOTAL" -gt "$MAX_FINDINGS" ]; then
    printf '  ... and %s more. Full list: %s/project/issues?id=%s\n' \
      "$((TOTAL - MAX_FINDINGS))" "$HOST_URL" "$PROJECT_KEY"
  fi
fi

log "$TOTAL issue(s) on $PROJECT_KEY"
exit "$EXIT_FINDINGS"
