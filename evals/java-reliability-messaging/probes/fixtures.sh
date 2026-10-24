#!/usr/bin/env bash
# Reproduces the rubric claims of java-reliability-messaging's review cases on the fixtures
# themselves: it writes the tickets and boxoffice fixtures from ../cases.json into a temporary
# directory, builds each, runs it against a throwaway PostgreSQL 18.6 container, and then
#   - sends 300 concurrent one-ticket purchases to a 100-seat event in each;
#   - sends tickets' and boxoffice's PUT /events/1 with a current, a stale, a weak and no
#     If-Match.
# The container is labelled probe.owner=probe-fixtures-<pid> and publishes its port on
# 127.0.0.1 only. The applications listen on 127.0.0.1. Everything is removed or stopped on
# exit. Results go to stdout, one line per check; progress goes to stderr.
set -euo pipefail

readonly IMAGE='postgres:18.6-trixie'

usage() {
  cat <<'EOF'
Usage: fixtures.sh [--port N] (--dry-run | --yes)

Builds the tickets and boxoffice fixtures of the java-reliability-messaging review cases,
runs them against a throwaway PostgreSQL 18.6 container, and prints what the seeded
defects and the correct code do. Needs docker, JDK 25, Maven, curl and python3.

Options:
  --port N    first of the two local ports the applications listen on (default
              $FIXTURES_PORT, else 18081)
  --dry-run   print what would run, and change nothing
  --yes       run it: starts a container labelled probe.owner=probe-fixtures-<pid> and two
              Java processes, and stops and removes them on exit
  -h, --help  show this help

Exit status: 0 success, 1 runtime failure, 2 usage error.
EOF
}

port=${FIXTURES_PORT:-18081}
mode=''
while [[ $# -gt 0 ]]; do
  case $1 in
    --port)
      if [[ $# -lt 2 || ! $2 =~ ^[1-9][0-9]{3,4}$ ]] || (($2 > 65534)); then
        printf 'fixtures: --port needs a port number from 1000 to 65534\n' >&2
        exit 2
      fi
      port=$2
      shift 2
      ;;
    --dry-run | --yes)
      [[ -z $mode ]] || {
        printf 'fixtures: choose one of --dry-run and --yes\n' >&2
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
  printf 'fixtures: pass --dry-run to see the plan, or --yes to run it\n' >&2
  exit 2
fi

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cases="$here/../cases.json"
prefix="probe-fixtures-$$"

if [[ $mode == --dry-run ]]; then
  cat <<EOF
fixtures:  tickets and boxoffice from $cases, written to a temporary directory
container: $prefix ($IMAGE, trust auth, port published on 127.0.0.1 only)
apps:      tickets on 127.0.0.1:$port, boxoffice on 127.0.0.1:$((port + 1))
checks:    300 concurrent one-ticket purchases on a 100-seat event in each;
           PUT /events/1 with no, a current, a stale and a weak If-Match in each
removed on exit: the container, the two Java processes and the temporary directory
EOF
  exit 0
fi

for tool in docker mvn java curl python3; do
  command -v "$tool" >/dev/null || {
    printf 'fixtures: %s is not on PATH\n' "$tool" >&2
    exit 1
  }
done
for p in "$port" $((port + 1)); do
  if curl -s -o /dev/null "http://127.0.0.1:$p/"; then
    printf 'fixtures: port %s is already in use\n' "$p" >&2
    exit 1
  fi
done

work=''
pids=''
cleanup() {
  local pid ids
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in $pids; do
    wait "$pid" 2>/dev/null || true
  done
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

progress() { printf '%s\n' "$*" >&2; }
work=$(mktemp -d "${TMPDIR:-/tmp}/fixtures.XXXXXX")

python3 -I - "$cases" "$work" <<'PY'
import json
import sys
from pathlib import Path

spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
root = Path(sys.argv[2]).resolve()
for name in ("tickets", "boxoffice"):
    for rel, text in spec["fixtures"][name].items():
        target = (root / name / rel).resolve()
        if root not in target.parents:
            raise SystemExit(f"fixture path escapes the directory: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
PY

docker run -d --name "$prefix" --label "probe.owner=$prefix" -p 127.0.0.1::5432 \
  -e POSTGRES_HOST_AUTH_METHOD=trust "$IMAGE" >/dev/null
tries=0
until docker exec "$prefix" pg_isready -q -h 127.0.0.1 2>/dev/null; do
  tries=$((tries + 1))
  if ((tries > 60)); then
    printf 'fixtures: the server did not start\n' >&2
    exit 1
  fi
  sleep 1
done
db_port=$(docker port "$prefix" 5432/tcp | head -1 | sed 's/.*://')
psql_db() { docker exec -i "$prefix" psql -U postgres -d "$1" -qAtX -v ON_ERROR_STOP=1; }
printf 'CREATE DATABASE tickets;\nCREATE DATABASE boxoffice;\n' | psql_db postgres >/dev/null

start_app() {
  local name=$1 app_port=$2 jar
  progress "building $name"
  (cd "$work/$name" && mvn -B -q -DskipTests package) >"$work/$name-build.log" 2>&1 || {
    tail -20 "$work/$name-build.log" >&2
    exit 1
  }
  jar=$(find "$work/$name/target" -maxdepth 1 -name '*.jar' ! -name '*.original' | head -1)
  DATABASE_URL="jdbc:postgresql://127.0.0.1:$db_port/$name" DATABASE_USER=postgres \
    SERVER_ADDRESS=127.0.0.1 SERVER_PORT="$app_port" java -jar "$jar" >"$work/$name-app.log" 2>&1 &
  pids="$pids $!"
  tries=0
  until curl -s -o /dev/null "http://127.0.0.1:$app_port/events/0"; do
    tries=$((tries + 1))
    if ((tries > 120)); then
      printf 'fixtures: %s did not start; its log ends with:\n' "$name" >&2
      tail -20 "$work/$name-app.log" >&2
      exit 1
    fi
    sleep 0.5
  done
  printf '%s\n' "INSERT INTO events (title, description, venue, starts_at) VALUES ('Show', 'd', 'Hall', '2026-11-20T19:00Z');" \
    'INSERT INTO event_inventory VALUES (1, 100, 100);' | psql_db "$name" >/dev/null
}

purchases() {
  local name=$1 app_port=$2 statuses
  statuses=$(seq 1 300 | xargs -P 60 -I{} curl -s -o /dev/null -w '%{http_code}\n' -X POST \
    "http://127.0.0.1:$app_port/events/1/orders" -H 'Content-Type: application/json' \
    -d '{"customerEmail":"c{}@example.com","quantity":1}' | sort | uniq -c | awk '{printf "%s x %s, ", $1, $2}')
  printf '%s | 300 concurrent one-ticket purchases on a 100-seat event | responses: %ssold %s, tickets_left %s\n' \
    "$name" "$statuses" \
    "$(printf 'SELECT coalesce(sum(quantity), 0) FROM orders WHERE event_id = 1;\n' | psql_db "$name")" \
    "$(printf 'SELECT tickets_left FROM event_inventory WHERE event_id = 1;\n' | psql_db "$name")"
}

put_status() {
  local app_port=$1 title=$2 if_match=$3
  local args=(-s -o /dev/null -w '%{http_code}' -X PUT "http://127.0.0.1:$app_port/events/1"
    -H 'Content-Type: application/json'
    -d "{\"title\":\"$title\",\"description\":\"d\",\"venue\":\"Hall\",\"startsAt\":\"2026-11-20T19:00:00Z\"}")
  if [[ -n $if_match ]]; then
    args+=(-H "If-Match: $if_match")
  fi
  curl "${args[@]}"
}

conditional_puts() {
  local name=$1 app_port=$2 etag no_header current stale weak
  etag=$(curl -s -D - -o /dev/null "http://127.0.0.1:$app_port/events/1" | tr -d '\r' | sed -n 's/^[Ee][Tt][Aa][Gg]: //p')
  no_header=$(put_status "$app_port" 'no header' '')
  current=$(curl -s -D - -o /dev/null "http://127.0.0.1:$app_port/events/1" | tr -d '\r' | sed -n 's/^[Ee][Tt][Aa][Gg]: //p')
  current=$(put_status "$app_port" 'first editor' "$current")
  stale=$(put_status "$app_port" 'second editor, stale' "$etag")
  weak=$(put_status "$app_port" 'weak tag' "W/$etag")
  printf '%s | PUT /events/1 after GET returned ETag %s | no If-Match: %s; the current ETag: %s; the first ETag again, now stale: %s; W/ of it: %s; title now: %s\n' \
    "$name" "$etag" "$no_header" "$current" "$stale" "$weak" \
    "$(printf 'SELECT title || $$ at version $$ || version FROM events WHERE id = 1;\n' | psql_db "$name")"
}

start_app tickets "$port"
start_app boxoffice $((port + 1))
purchases tickets "$port"
purchases boxoffice $((port + 1))
conditional_puts tickets "$port"
conditional_puts boxoffice $((port + 1))
