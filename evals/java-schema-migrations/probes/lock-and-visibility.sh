#!/usr/bin/env bash
# Reproduces the facts the 2026-10-24 cleanup pass added to the java-schema-migrations
# skill:
#   1. a concurrent index build's lock_timeout bounds each wait, not the build, and which
#      sessions delay the build;
#   2. a plain CREATE INDEX keeps writes waiting until its transaction ends;
#   3. max(id) sees its own transaction's uncommitted insert and not another session's.
#
# It runs against a PostgreSQL 18 container that is already running, for instance:
#   docker run -d --name pg-probe -e POSTGRES_PASSWORD="$(openssl rand -hex 16)" postgres:18.6
# It creates a database named probe_lv_<pid> there, loads the rows, and drops it on exit.
# Results go to stdout, one line per case; progress goes to stderr.
set -euo pipefail

readonly LOCK_TIMEOUT='1s'
readonly BLOCKER_SECONDS=7

usage() {
  cat <<'EOF'
Usage: lock-and-visibility.sh [--container NAME] [--rows N] (--dry-run | --yes)

Runs the cleanup-pass probes of the java-schema-migrations skill in a running PostgreSQL 18
container, inside a throwaway database it creates and drops.

Options:
  --container NAME  the container to use (default: $PG_PROBE_CONTAINER, else pg-probe)
  --rows N          rows in the probe table (default 10000000; the build must outlast
                    the 1 s lock_timeout for case 1a to mean anything)
  --dry-run         print what would run, and change nothing
  --yes             run it: creates a database, loads N rows, and drops the database
  -h, --help        show this help

Exit status: 0 success, 1 runtime failure, 2 usage error.
EOF
}

container=${PG_PROBE_CONTAINER:-pg-probe}
rows=10000000
mode=''

while [[ $# -gt 0 ]]; do
  case $1 in
    --container)
      [[ $# -ge 2 ]] || {
        usage >&2
        exit 2
      }
      container=$2
      shift 2
      ;;
    --rows)
      [[ $# -ge 2 && $2 =~ ^[1-9][0-9]*$ ]] || {
        printf 'lock-and-visibility: --rows needs a positive integer\n' >&2
        exit 2
      }
      rows=$2
      shift 2
      ;;
    --dry-run | --yes)
      [[ -z $mode ]] || {
        printf 'lock-and-visibility: choose one of --dry-run and --yes\n' >&2
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
  printf 'lock-and-visibility: pass --dry-run to see the plan, or --yes to run it\n' >&2
  exit 2
fi

db="probe_lv_$$"
work=''

steps() {
  cat <<EOF
container: $container
database:  $db (created, then dropped with FORCE on exit)
rows:      $rows
1a  concurrent build under lock_timeout $LOCK_TIMEOUT, no blocker
1b  the same build behind each blocker, held ${BLOCKER_SECONDS} s:
      READ COMMITTED, read this table, then idle in transaction
      READ COMMITTED, read another table, then idle in transaction
      REPEATABLE READ, read another table, then idle in transaction
      BEGIN only, idle in transaction
      uncommitted insert into this table, then idle in transaction
      idle session outside any transaction
      a query still running on another table
2   plain CREATE INDEX, then more work in its transaction: an insert sent after the build
3   max(id) inside the inserting transaction and from another session
EOF
}

if [[ $mode == --dry-run ]]; then
  steps
  exit 0
fi

command -v docker >/dev/null || {
  printf 'lock-and-visibility: docker is not on PATH\n' >&2
  exit 1
}
if [[ $(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true) != true ]]; then
  printf 'lock-and-visibility: container %s is not running\n' "$container" >&2
  exit 1
fi

psql_in() {
  local database=$1
  shift
  docker exec -i "$container" psql -U postgres -d "$database" -qAtX -v ON_ERROR_STOP=0 "$@"
}
psql_db() { psql_in "$db" "$@"; }

cleanup() {
  local pids
  pids=$(jobs -p)
  if [[ -n $pids ]]; then
    # shellcheck disable=SC2086 # one PID per word is the intent
    kill $pids 2>/dev/null || true
  fi
  if [[ $db =~ ^probe_lv_[0-9]+$ ]]; then
    psql_in postgres -c "DROP DATABASE IF EXISTS $db WITH (FORCE)" >/dev/null 2>&1 || true
  fi
  if [[ -n $work && -d $work && $work == "${TMPDIR:-/tmp}"/* ]]; then
    rm -rf -- "$work"
  fi
}
trap cleanup EXIT

work=$(mktemp -d "${TMPDIR:-/tmp}/lock-and-visibility.XXXXXX")

version=$(psql_in postgres -c 'SHOW server_version_num')
if ((version < 180000)); then
  printf 'lock-and-visibility: the server is %s; the skill states PostgreSQL 18 facts\n' "$version" >&2
fi

progress() { printf '%s\n' "$*" >&2; }

progress "creating $db with $rows rows"
psql_in postgres -c "CREATE DATABASE $db" >/dev/null
psql_db -c "CREATE TABLE shipments (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, carrier_id bigint NOT NULL)"
psql_db -c "INSERT INTO shipments (carrier_id) SELECT (random() * 50000)::bigint FROM generate_series(1, $rows)"
psql_db -c "CREATE TABLE other (id int)"
psql_db -c "INSERT INTO other VALUES (1)"
psql_db -c "VACUUM ANALYZE shipments"

last_time_ms() { grep -oE 'Time: [0-9.]+' | tail -1 | cut -d' ' -f2; }

# Polls until the query in $1 returns 1, for at most 30 s.
wait_until() {
  local sql=$1 tries=0
  until [[ $(psql_db -c "$sql") == 1 ]]; do
    tries=$((tries + 1))
    if ((tries > 300)); then
      printf 'lock-and-visibility: timed out waiting for: %s\n' "$sql" >&2
      exit 1
    fi
    sleep 0.1
  done
}

wait_for_session() {
  wait_until "SELECT count(*) FROM pg_stat_activity WHERE application_name = '$1' AND state = '$2'"
}

build_once() {
  local out ms valid
  out=$(printf '%s\n' '\timing on' "SET lock_timeout = '$LOCK_TIMEOUT';" \
    "CREATE INDEX CONCURRENTLY shipments_carrier_id_idx ON shipments (carrier_id);" | psql_db 2>&1 || true)
  ms=$(last_time_ms <<<"$out")
  valid=$(psql_db -c "SELECT coalesce((SELECT indisvalid::text FROM pg_index WHERE indexrelid = to_regclass('shipments_carrier_id_idx')), 'absent')")
  psql_db -c "DROP INDEX IF EXISTS shipments_carrier_id_idx" >/dev/null
  if grep -q 'lock timeout' <<<"$out"; then
    printf 'cancelled by lock_timeout after %s ms, index valid=%s' "$ms" "$valid"
  else
    printf 'finished in %s ms, index valid=%s' "$ms" "$valid"
  fi
}

# Holds a session open while the build runs. The client sleeps between statements, so an
# idle blocker runs no statement and holds no snapshot of a running query.
blocker() {
  local label=$1 state=$2 opening=$3 closing=$4 pid
  {
    printf '%s\n' "SET application_name = 'lv_blocker';" "$opening"
    sleep "$BLOCKER_SECONDS"
    printf '%s\n' "$closing"
  } | psql_db >/dev/null 2>&1 &
  pid=$!
  wait_for_session lv_blocker "$state"
  printf '1b | %s | %s\n' "$label" "$(build_once)"
  wait "$pid" || true
}

progress "case 1"
printf '1a | no blocker | %s\n' "$(build_once)"
blocker "READ COMMITTED, read this table, then idle in transaction" 'idle in transaction' \
  "BEGIN; SELECT count(*) FROM shipments WHERE id = 1;" "COMMIT;"
blocker "READ COMMITTED, read another table, then idle in transaction" 'idle in transaction' \
  "BEGIN; SELECT count(*) FROM other;" "COMMIT;"
blocker "REPEATABLE READ, read another table, then idle in transaction" 'idle in transaction' \
  "BEGIN ISOLATION LEVEL REPEATABLE READ; SELECT count(*) FROM other;" "COMMIT;"
blocker "BEGIN only, idle in transaction" 'idle in transaction' "BEGIN;" "COMMIT;"
blocker "uncommitted insert into this table, then idle in transaction" 'idle in transaction' \
  "BEGIN; INSERT INTO shipments (carrier_id) VALUES (1);" "COMMIT;"
blocker "idle session outside any transaction" idle "SELECT 1;" "SELECT 1;"
blocker "a query still running on another table" active \
  "SELECT pg_sleep($BLOCKER_SECONDS), count(*) FROM other;" "SELECT 1;"

progress "case 2"
printf '%s\n' "SET application_name = 'lv_ddl';" "BEGIN;" \
  "CREATE INDEX shipments_carrier_id_plain_idx ON shipments (carrier_id);" \
  "SELECT pg_sleep(3);" "COMMIT;" | psql_db >/dev/null 2>&1 &
ddl_pid=$!
wait_until "SELECT count(*) FROM pg_stat_activity WHERE application_name = 'lv_ddl' AND query LIKE 'SELECT pg_sleep%'"
insert_ms=$(printf '%s\n' '\timing on' "INSERT INTO shipments (carrier_id) VALUES (2);" | psql_db 2>&1 | last_time_ms)
wait "$ddl_pid" || true
printf '2  | insert sent after the plain build had finished, its transaction still open | waited %s ms\n' "$insert_ms"
psql_db -c "DROP INDEX IF EXISTS shipments_carrier_id_plain_idx" >/dev/null

progress "case 3"
probe_id=$((rows + 1000000))
{
  printf '%s\n' "SET application_name = 'lv_vis';" "BEGIN;" \
    "INSERT INTO shipments (id, carrier_id) OVERRIDING SYSTEM VALUE VALUES ($probe_id, 3);" \
    "SELECT max(id) FROM shipments;"
  sleep 3
  printf 'ROLLBACK;\n'
} | psql_db >"$work/own.txt" 2>&1 &
vis_pid=$!
wait_for_session lv_vis 'idle in transaction'
other_max=$(psql_db -c "SELECT max(id) FROM shipments")
wait "$vis_pid" || true
own_max=$(grep -E '^[0-9]+$' "$work/own.txt" | tail -1)
printf '3  | max(id) inside the inserting transaction | %s (inserted id %s)\n' "$own_max" "$probe_id"
printf '3  | max(id) from another session meanwhile | %s\n' "$other_max"
