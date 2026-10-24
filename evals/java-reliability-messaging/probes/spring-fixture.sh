#!/usr/bin/env bash
# Runs the Maven project in spring-fixture/ against a throwaway PostgreSQL 18.6 container and
# prints its FACT lines: the Spring Boot 4.1.2, jOOQ 3.21.9, Spring Data JDBC and ShedLock
# 7.10.1 facts that java-reliability-messaging's concurrency-control.md and scheduled-jobs.md
# cite, and the @Email length check behind a graded false positive of the review eval. The
# project is built in a temporary copy, so the repo gains no target/ directory. The
# container is labelled probe.owner=probe-spring-<pid>, publishes its port on 127.0.0.1 only,
# and is removed on exit. FACT lines go to stdout; the build log's tail goes to stderr on
# failure.
set -euo pipefail

readonly IMAGE='postgres:18.6-trixie'

usage() {
  cat <<'EOF'
Usage: spring-fixture.sh (--dry-run | --yes)

Runs the java-reliability-messaging Spring fixture's tests against a throwaway PostgreSQL
18.6 container and prints the facts they observe. Needs docker, JDK 25 and Maven.

Options:
  --dry-run   print what would run, and change nothing
  --yes       run it: starts a container labelled probe.owner=probe-spring-<pid>, runs
              mvn test in a temporary copy of spring-fixture/, and removes both on exit
  -h, --help  show this help

Exit status: 0 success, 1 runtime failure, 2 usage error.
EOF
}

mode=''
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run | --yes)
      [[ -z $mode ]] || {
        printf 'spring-fixture: choose one of --dry-run and --yes\n' >&2
        exit 2
      }
      mode=$1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done
if [[ -z $mode ]]; then
  printf 'spring-fixture: pass --dry-run to see the plan, or --yes to run it\n' >&2
  exit 2
fi

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project="$here/spring-fixture"
prefix="probe-spring-$$"

if [[ $mode == --dry-run ]]; then
  cat <<EOF
container: $prefix ($IMAGE, trust auth, port published on 127.0.0.1 only)
schema:    $project/src/main/resources/schema.sql into database probe_java
tests:     mvn test in a temporary copy of $project (jOOQ codegen from schema.sql, then the probe tests)
removed on exit: the container and the copy
EOF
  exit 0
fi

for tool in docker mvn; do
  command -v "$tool" >/dev/null || {
    printf 'spring-fixture: %s is not on PATH\n' "$tool" >&2
    exit 1
  }
done

work=''
cleanup() {
  local ids
  ids=$(docker ps -aq --filter "label=probe.owner=$prefix" 2>/dev/null || true)
  if [[ -n $ids ]]; then
    # shellcheck disable=SC2086 # one container id per word is the intent
    docker rm -f $ids >/dev/null 2>&1 || true
  fi
  if [[ -n $work && -d $work && $work == "${TMPDIR:-/tmp}"/* ]]; then
    rm -rf -- "$work"
  fi
}
trap cleanup EXIT

docker run -d --name "$prefix" --label "probe.owner=$prefix" -p 127.0.0.1::5432 \
  -e POSTGRES_HOST_AUTH_METHOD=trust "$IMAGE" >/dev/null
tries=0
until docker exec "$prefix" pg_isready -q -h 127.0.0.1 2>/dev/null; do
  tries=$((tries + 1))
  if ((tries > 60)); then
    printf 'spring-fixture: the server did not start\n' >&2
    exit 1
  fi
  sleep 1
done
port=$(docker port "$prefix" 5432/tcp | head -1 | sed 's/.*://')
docker exec -i "$prefix" psql -U postgres -qAtX -v ON_ERROR_STOP=1 -c 'CREATE DATABASE probe_java' >/dev/null
docker exec -i "$prefix" psql -U postgres -d probe_java -qAtX -v ON_ERROR_STOP=1 \
  <"$project/src/main/resources/schema.sql" >/dev/null

work=$(mktemp -d "${TMPDIR:-/tmp}/spring-fixture.XXXXXX")
cp -R "$project/pom.xml" "$project/src" "$work/"
log="$work/mvn.log"
printf 'running mvn test against 127.0.0.1:%s\n' "$port" >&2
status=0
(cd "$work" && PROBE_JDBC_URL="jdbc:postgresql://127.0.0.1:$port/probe_java" mvn -B test) >"$log" 2>&1 || status=$?
grep '^FACT' "$log" || true
grep -E '^\[(INFO|ERROR|WARNING)\] Tests run:' "$log" | tail -1 >&2 || true
if ((status != 0)); then
  printf 'spring-fixture: mvn test failed with exit %s; the log ends with:\n' "$status" >&2
  tail -40 "$log" >&2
  exit 1
fi
