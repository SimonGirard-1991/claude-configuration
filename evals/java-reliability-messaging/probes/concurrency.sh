#!/usr/bin/env bash
# Reproduces the PostgreSQL 18 facts that java-reliability-messaging's concurrency-control.md
# cites:
#   A. which row locks a foreign key check waits for;
#   B. NOWAIT and SKIP LOCKED;
#   C. a read-modify-write of one row under READ COMMITTED and REPEATABLE READ;
#   D. write skew under REPEATABLE READ and SERIALIZABLE;
#   E. session and transaction advisory locks, directly and through PgBouncer in
#      transaction pooling.
#
# It starts its own network, PostgreSQL container and PgBouncer container, runs every client
# in a container of its own, labels them all probe.owner=probe-cc-<pid>, and removes them on
# exit. Results go to stdout, one line per case; progress goes to stderr.
set -euo pipefail

readonly IMAGE_TAG='probe-pg18-reliability:18.6'

usage() {
  cat <<'EOF'
Usage: concurrency.sh (--dry-run | --yes)

Runs the concurrency-control probes of the java-reliability-messaging skill against a
throwaway PostgreSQL 18.6 container and a PgBouncer container in front of it. Builds the
image from the Dockerfile beside this script when it is missing.

Options:
  --dry-run   print what would run, and change nothing
  --yes       run it: creates a docker network and containers labelled
              probe.owner=probe-cc-<pid>, and removes them on exit
  -h, --help  show this help

Exit status: 0 success, 1 runtime failure, 2 usage error.
EOF
}

mode=''
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run | --yes)
      [[ -z $mode ]] || {
        printf 'concurrency: choose one of --dry-run and --yes\n' >&2
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
  printf 'concurrency: pass --dry-run to see the plan, or --yes to run it\n' >&2
  exit 2
fi

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
prefix="probe-cc-$$"
db='probe'

steps() {
  cat <<EOF
image:    $IMAGE_TAG (built from $here/Dockerfile if missing)
network:  $prefix
server:   $prefix-pg, PostgreSQL 18.6, trust auth, no published port
pooler:   $prefix-bouncer, PgBouncer in transaction pooling: pool1 (1 server connection), pool2 (2)
A1-A7  a holder's lock on projects(1) against a task insert that references it, and the
       reverse, under lock_timeout 1s; the row locks pgrowlocks shows for an insert and an update
B1-B5  work item 1 locked FOR UPDATE: SKIP LOCKED, NOWAIT, a count through SKIP LOCKED;
       two claims by UPDATE ... SKIP LOCKED, and the same claim from an older
       REPEATABLE READ snapshot
C1-C10 session A reads quotas(1), writes 4 s later and commits 5 s after that; session B reads
       while A is open and writes while A's write is uncommitted. READ COMMITTED and
       REPEATABLE READ; computed value, conditional decrement, SELECT FOR UPDATE, version
       check, SELECT FOR NO KEY UPDATE
D1-D2  two on-call doctors each go off duty after counting two on duty: REPEATABLE READ,
       SERIALIZABLE
E1-E4  advisory locks: session lock and rollback, transaction lock and commit, and both
       through PgBouncer's transaction pooling
everything labelled probe.owner=$prefix is removed on exit
EOF
}

if [[ $mode == --dry-run ]]; then
  steps
  exit 0
fi

command -v docker >/dev/null || {
  printf 'concurrency: docker is not on PATH\n' >&2
  exit 1
}

work=''
cleanup() {
  local ids
  ids=$(docker ps -aq --filter "label=probe.owner=$prefix" 2>/dev/null || true)
  if [[ -n $ids ]]; then
    # shellcheck disable=SC2086 # one container id per word is the intent
    docker rm -f $ids >/dev/null 2>&1 || true
  fi
  if [[ $prefix =~ ^probe-cc-[0-9]+$ ]]; then
    docker network rm "$prefix" >/dev/null 2>&1 || true
  fi
  if [[ -n $work && -d $work && $work == "${TMPDIR:-/tmp}"/* ]]; then
    rm -rf -- "$work"
  fi
}
trap cleanup EXIT

work=$(mktemp -d "${TMPDIR:-/tmp}/concurrency.XXXXXX")
progress() { printf '%s\n' "$*" >&2; }

if ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
  progress "building $IMAGE_TAG"
  docker build -q -t "$IMAGE_TAG" "$here" >/dev/null
fi

docker network create --label "probe.owner=$prefix" "$prefix" >/dev/null
docker run -d --name "$prefix-pg" --label "probe.owner=$prefix" --network "$prefix" \
  -e POSTGRES_HOST_AUTH_METHOD=trust "$IMAGE_TAG" >/dev/null

# Runs psql in a container of its own, reading SQL from stdin.
client_to() {
  local host=$1 port=$2 database=$3
  docker run --rm -i --label "probe.owner=$prefix" --network "$prefix" "$IMAGE_TAG" \
    psql -h "$host" -p "$port" -U postgres -d "$database" -qAtX -v ON_ERROR_STOP=0
}
direct() { client_to "$prefix-pg" 5432 "$db"; }
bounced() { client_to "$prefix-bouncer" 6432 "$1"; }
sql() { printf '%s\n' "$1" | direct 2>&1; }

tries=0
until docker run --rm --label "probe.owner=$prefix" --network "$prefix" "$IMAGE_TAG" \
  pg_isready -q -h "$prefix-pg" 2>/dev/null; do
  tries=$((tries + 1))
  if ((tries > 60)); then
    printf 'concurrency: the server did not start\n' >&2
    exit 1
  fi
  sleep 1
done
printf 'CREATE DATABASE %s;\n' "$db" | client_to "$prefix-pg" 5432 postgres >/dev/null

cat >"$work/pgbouncer.ini" <<EOF
[databases]
pool1 = host=$prefix-pg dbname=$db pool_size=1
pool2 = host=$prefix-pg dbname=$db pool_size=2

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = trust
auth_file = /probe/userlist.txt
pool_mode = transaction
EOF
printf '"postgres" ""\n' >"$work/userlist.txt"
chmod 0644 "$work/pgbouncer.ini" "$work/userlist.txt"
docker run -d --name "$prefix-bouncer" --label "probe.owner=$prefix" --network "$prefix" \
  --user postgres -v "$work:/probe:ro" "$IMAGE_TAG" pgbouncer /probe/pgbouncer.ini >/dev/null

progress "server $(sql 'SHOW server_version'), $(docker run --rm --label "probe.owner=$prefix" "$IMAGE_TAG" pgbouncer --version | head -1)"

reset_tables() {
  sql "DROP TABLE IF EXISTS tasks, projects, work_items, quotas, on_call;
CREATE TABLE projects (id bigint PRIMARY KEY, name text NOT NULL);
CREATE TABLE tasks (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id bigint NOT NULL REFERENCES projects (id));
INSERT INTO projects VALUES (1, 'p');
CREATE TABLE work_items (id bigint PRIMARY KEY, state text NOT NULL);
INSERT INTO work_items SELECT g, 'pending' FROM generate_series(1, 5) g;
CREATE TABLE quotas (id bigint PRIMARY KEY, remaining integer NOT NULL, version bigint NOT NULL);
INSERT INTO quotas VALUES (1, 10, 0);
CREATE TABLE on_call (name text PRIMARY KEY, on_duty boolean NOT NULL);
INSERT INTO on_call VALUES ('alice', true), ('bob', true);" >/dev/null
}

# Polls the server until the query in $1 returns 1, for at most 30 s.
wait_until() {
  local query=$1 polls=0
  until [[ $(sql "$query") == 1 ]]; do
    polls=$((polls + 1))
    if ((polls > 60)); then
      printf 'concurrency: timed out waiting for: %s\n' "$query" >&2
      exit 1
    fi
    sleep 0.5
  done
}
wait_state() {
  wait_until "SELECT count(*) FROM pg_stat_activity WHERE application_name = '$1' AND state = '$2'"
}

# A session that sends $3, sleeps $4 s, sends $5, sleeps $6 s, then sends $7. The sleeps are
# the client's, so an idle session runs no statement and holds no snapshot of a running query.
session() {
  local label=$1 out=$2 opening=$3 pause=$4 middle=$5 pause2=$6 closing=$7
  {
    printf '%s\n' "SET application_name = '$label';" "$opening"
    sleep "$pause"
    printf '%s\n' "$middle"
    sleep "$pause2"
    printf '%s\n' "$closing"
  } | direct >"$out" 2>&1 &
  session_pid=$!
}

outcome() {
  if grep -q 'lock timeout' <<<"$1"; then
    printf 'waited, cancelled by lock_timeout 1s'
  elif grep -q 'could not obtain lock' <<<"$1"; then
    printf 'error at once: %s' "$(grep -o 'could not obtain lock.*' <<<"$1" | head -1)"
  elif grep -q 'ERROR' <<<"$1"; then
    printf 'error: %s' "$(grep -m1 'ERROR' <<<"$1")"
  else
    printf 'ran without waiting, returned: %s' "$(tr '\n' ' ' <<<"$1")"
  fi
}

lock_case() {
  local id=$1 label=$2 holder=$3 waiter=$4 out
  reset_tables
  session holder "$work/holder.out" "BEGIN; $holder" 4 'SELECT 1;' 0 'COMMIT;'
  wait_state holder 'idle in transaction'
  out=$(sql "SET lock_timeout = '1s'; $waiter")
  printf '%s | %s | %s\n' "$id" "$label" "$(outcome "$out")"
  wait "$session_pid" || true
}

progress "A: row locks and foreign keys"
lock_case A1 'holder SELECT FOR UPDATE on the project; waiter inserts a task referencing it' \
  'SELECT id FROM projects WHERE id = 1 FOR UPDATE;' 'INSERT INTO tasks (project_id) VALUES (1);'
lock_case A2 'holder SELECT FOR NO KEY UPDATE on the project; waiter inserts a task referencing it' \
  'SELECT id FROM projects WHERE id = 1 FOR NO KEY UPDATE;' 'INSERT INTO tasks (project_id) VALUES (1);'
lock_case A3 'holder UPDATE of a non-key column of the project; waiter inserts a task referencing it' \
  "UPDATE projects SET name = 'q' WHERE id = 1;" 'INSERT INTO tasks (project_id) VALUES (1);'
lock_case A4 'holder inserts a task, uncommitted; waiter SELECT FOR UPDATE on the project' \
  'INSERT INTO tasks (project_id) VALUES (1);' 'SELECT id FROM projects WHERE id = 1 FOR UPDATE;'
lock_case A5 'holder inserts a task, uncommitted; waiter SELECT FOR NO KEY UPDATE on the project' \
  'INSERT INTO tasks (project_id) VALUES (1);' 'SELECT id FROM projects WHERE id = 1 FOR NO KEY UPDATE;'

sql 'CREATE EXTENSION IF NOT EXISTS pgrowlocks;' >/dev/null
rowlock_case() {
  local id=$1 label=$2 holder=$3
  reset_tables
  session holder "$work/holder.out" "BEGIN; $holder" 3 'SELECT 1;' 0 'COMMIT;'
  wait_state holder 'idle in transaction'
  printf '%s | %s | pgrowlocks on projects: %s\n' "$id" "$label" \
    "$(sql "SELECT coalesce(string_agg(array_to_string(modes, ','), ';'), 'none') FROM pgrowlocks('projects')")"
  wait "$session_pid" || true
}
rowlock_case A6 'holder inserts a task referencing the project, uncommitted' 'INSERT INTO tasks (project_id) VALUES (1);'
rowlock_case A7 'holder UPDATE of a non-key column of the project, uncommitted' "UPDATE projects SET name = 'q' WHERE id = 1;"

progress "B: NOWAIT and SKIP LOCKED"
lock_case B1 'work item 1 locked; waiter claims two with SKIP LOCKED' \
  'SELECT id FROM work_items WHERE id = 1 FOR UPDATE;' \
  'SELECT string_agg(id::text, $$,$$) FROM (SELECT id FROM work_items ORDER BY id LIMIT 2 FOR UPDATE SKIP LOCKED) s;'
lock_case B2 'work item 1 locked; waiter locks it with NOWAIT' \
  'SELECT id FROM work_items WHERE id = 1 FOR UPDATE;' \
  'SELECT id FROM work_items WHERE id = 1 FOR UPDATE NOWAIT;'
lock_case B3 'work item 1 locked; waiter counts the 5 pending items through SKIP LOCKED' \
  'SELECT id FROM work_items WHERE id = 1 FOR UPDATE;' \
  "SELECT count(*) FROM (SELECT id FROM work_items WHERE state = 'pending' FOR UPDATE SKIP LOCKED) s;"
claim="UPDATE work_items SET state = 'claimed' WHERE id IN (SELECT id FROM work_items
  WHERE state = 'pending' ORDER BY id LIMIT 2 FOR UPDATE SKIP LOCKED) RETURNING id;"
lock_case B4 'holder claims two pending items with UPDATE ... SKIP LOCKED, uncommitted; waiter runs the same claim' \
  "$claim" "$claim"
reset_tables
session waiter "$work/waiter.out" 'BEGIN ISOLATION LEVEL REPEATABLE READ; SELECT 1;' 4 "$claim" 0 'COMMIT;'
wait_state waiter 'idle in transaction'
first_claim=$(sql "$claim" | tr '\n' ' ')
wait "$session_pid" || true
printf 'B5 | REPEATABLE READ waiter takes its snapshot, another session claims %sand commits, then the waiter runs the same claim | %s\n' \
  "$first_claim" "$(outcome "$(grep -v '^SET$' "$work/waiter.out")")"

# Session A reads, writes 4 s later and commits 5 s after its write. Session B starts once A is
# open, so it reads before A writes, and writes 4 s after its read, while A's write is still
# uncommitted. B's read and write are timed.
pair_case() {
  local id=$1 isolation=$2 read=$3 write=$4 label=$5 pid_a result times
  reset_tables
  session sess_a "$work/a.out" "BEGIN ISOLATION LEVEL $isolation;
$read" 4 "$write" 5 'COMMIT;'
  pid_a=$session_pid
  wait_until "SELECT count(*) FROM pg_stat_activity WHERE application_name = 'sess_a' AND state = 'idle in transaction'"
  session sess_b "$work/b.out" "\\timing on
BEGIN ISOLATION LEVEL $isolation;
$read" 4 "$write
\\echo rows :ROW_COUNT" 0 'COMMIT;'
  wait "$pid_a" || true
  wait "$session_pid" || true
  result=$(sql 'SELECT remaining || $$ remaining, version $$ || version FROM quotas WHERE id = 1')
  times=$(grep -oE 'Time: [0-9.]+ ms' "$work/b.out" | sed -n '2p;3p' | cut -d' ' -f2 | paste -sd/ - || true)
  if grep -q 'could not serialize' "$work/b.out"; then
    result="$result; B failed: $(grep -o 'could not serialize.*' "$work/b.out" | head -1)"
  elif grep -q '^rows 0$' "$work/b.out"; then
    result="$result; B updated 0 rows"
  fi
  printf '%s | %s, %s | from 10: %s (B read/write ms: %s)\n' "$id" "$isolation" "$label" "$result" "${times:-none}"
}

progress "C: read-modify-write"
read_value='SELECT remaining FROM quotas WHERE id = 1 \gset'
read_locked='SELECT remaining FROM quotas WHERE id = 1 FOR UPDATE \gset'
read_versioned='SELECT remaining, version FROM quotas WHERE id = 1 \gset'
write_value='UPDATE quotas SET remaining = :remaining - 1 WHERE id = 1;'
decrement='UPDATE quotas SET remaining = remaining - 1 WHERE id = 1 AND remaining >= 1;'
write_versioned='UPDATE quotas SET remaining = :remaining - 1, version = version + 1 WHERE id = 1 AND version = :version;'
pair_case C1 'READ COMMITTED' "$read_value" "$write_value" 'read, then write the value the client computed'
pair_case C2 'READ COMMITTED' 'SELECT 1;' "$decrement" 'one conditional UPDATE that decrements'
pair_case C3 'READ COMMITTED' "$read_locked" "$write_value" 'SELECT FOR UPDATE, then write the computed value'
pair_case C4 'REPEATABLE READ' "$read_value" "$write_value" 'read, then write the value the client computed'
pair_case C5 'REPEATABLE READ' "$read_locked" "$write_value" 'SELECT FOR UPDATE, then write the computed value'
pair_case C6 'REPEATABLE READ' 'SELECT 1;' "$decrement" 'one conditional UPDATE that decrements'
pair_case C7 'READ COMMITTED' "$read_versioned" "$write_versioned" 'read the version, then UPDATE ... WHERE version = it'
pair_case C8 'REPEATABLE READ' "$read_versioned" "$write_versioned" 'read the version, then UPDATE ... WHERE version = it'
read_no_key='SELECT remaining FROM quotas WHERE id = 1 FOR NO KEY UPDATE \gset'
pair_case C9 'READ COMMITTED' "$read_no_key" "$write_value" 'SELECT FOR NO KEY UPDATE, then write the computed value'
pair_case C10 'REPEATABLE READ' "$read_no_key" "$write_value" 'SELECT FOR NO KEY UPDATE, then write the computed value'

skew_case() {
  local id=$1 isolation=$2 pid_a result failed
  reset_tables
  session sess_a "$work/a.out" "BEGIN ISOLATION LEVEL $isolation;
SELECT count(*) AS on_duty FROM on_call WHERE on_duty \\gset" 4 \
    "UPDATE on_call SET on_duty = false WHERE name = 'alice' AND :on_duty >= 2;" 0 'COMMIT;'
  pid_a=$session_pid
  wait_state sess_a 'idle in transaction'
  session sess_b "$work/b.out" "BEGIN ISOLATION LEVEL $isolation;
SELECT count(*) AS on_duty FROM on_call WHERE on_duty \\gset" 4 \
    "UPDATE on_call SET on_duty = false WHERE name = 'bob' AND :on_duty >= 2;" 0 'COMMIT;'
  wait "$pid_a" || true
  wait "$session_pid" || true
  result="$(sql 'SELECT count(*) FROM on_call WHERE on_duty') still on duty"
  failed=$(cat "$work/a.out" "$work/b.out" | grep -o 'could not serialize.*' | head -1 || true)
  if [[ -n $failed ]]; then
    result="$result; one transaction failed: $failed"
  fi
  printf '%s | %s, each doctor counts 2 on duty, then goes off duty | %s\n' "$id" "$isolation" "$result"
}

progress "D: write skew"
skew_case D1 'REPEATABLE READ'
skew_case D2 'SERIALIZABLE'

progress "E: advisory locks"
session holder "$work/holder.out" 'BEGIN; SELECT pg_advisory_lock(101); ROLLBACK;' 4 'SELECT 1;' 0 'SELECT 1;'
wait_state holder idle
printf 'E1 | session lock taken in a transaction that rolled back, its session still open | another session acquires it: %s\n' \
  "$(sql 'SELECT pg_try_advisory_lock(101)')"
wait "$session_pid" || true

session holder "$work/holder.out" 'BEGIN; SELECT pg_advisory_xact_lock(102);' 3 'SELECT 1;' 0 'COMMIT;'
wait_state holder 'idle in transaction'
during=$(sql 'SELECT pg_try_advisory_xact_lock(102)')
wait "$session_pid" || true
printf 'E2 | transaction lock | another session acquires it before the commit: %s, after it: %s\n' \
  "$during" "$(sql 'SELECT pg_try_advisory_xact_lock(102)')"

first=$(printf 'SELECT pg_try_advisory_lock(103);\n' | bounced pool1 2>&1)
held=$(sql "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = 103 AND granted")
second=$(printf 'SELECT pg_try_advisory_lock(103);\n' | bounced pool1 2>&1)
printf 'E3 | PgBouncer transaction pooling, session lock | client 1 acquires: %s; after it disconnects the server still holds it: %s; client 2 acquires: %s; a direct session acquires: %s\n' \
  "$first" "$held" "$second" "$(sql 'SELECT pg_try_advisory_lock(103)')"

{
  printf '%s\n' 'BEGIN;' 'SELECT pg_try_advisory_xact_lock(104);'
  sleep 4
  printf '%s\n' 'COMMIT;'
} | bounced pool2 >"$work/bounced.out" 2>&1 &
pid_a=$!
wait_until "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = 104 AND granted"
during=$(printf '%s\n' 'BEGIN;' 'SELECT pg_try_advisory_xact_lock(104);' 'COMMIT;' | bounced pool2 2>&1)
wait "$pid_a" || true
after=$(printf '%s\n' 'BEGIN;' 'SELECT pg_try_advisory_xact_lock(104);' 'COMMIT;' | bounced pool2 2>&1)
printf 'E4 | PgBouncer transaction pooling, transaction lock | client 1 acquires: %s; client 2 during that transaction: %s; after its commit: %s\n' \
  "$(head -1 "$work/bounced.out")" "$during" "$after"
