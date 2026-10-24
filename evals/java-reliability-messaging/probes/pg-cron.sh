#!/usr/bin/env bash
# Reproduces the pg_cron facts that java-reliability-messaging's scheduled-jobs.md cites:
#   F1. the zone a schedule is read in by default;
#   F2. a run that outlasts its interval: runs never overlap;
#   F3. a failed run in cron.job_run_details, and the last success read from it;
#   F4. a daily schedule read in cron.timezone;
#   F5. runs missed while the server was down are not made up after it starts.
#
# It starts its own network and two PostgreSQL containers with pg_cron, runs every client in a
# container of its own, labels them all probe.owner=probe-cron-<pid>, and removes them on
# exit. F5 stops and starts its own server container. A run takes about seven minutes.
# Results go to stdout, one line per case; progress goes to stderr.
set -euo pipefail

readonly IMAGE_TAG='probe-pg18-reliability:18.6'
readonly ZONE='Europe/Zurich'

usage() {
  cat <<'EOF'
Usage: pg-cron.sh (--dry-run | --yes)

Runs the pg_cron probes of the java-reliability-messaging skill against two throwaway
PostgreSQL 18.6 containers. Builds the image from the Dockerfile beside this script when it
is missing. Takes about seven minutes.

Options:
  --dry-run   print what would run, and change nothing
  --yes       run it: creates a docker network and containers labelled
              probe.owner=probe-cron-<pid>, stops and starts one of them, and removes them
              all on exit
  -h, --help  show this help

Exit status: 0 success, 1 runtime failure, 2 usage error.
EOF
}

mode=''
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run | --yes)
      [[ -z $mode ]] || {
        printf 'pg-cron: choose one of --dry-run and --yes\n' >&2
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
  printf 'pg-cron: pass --dry-run to see the plan, or --yes to run it\n' >&2
  exit 2
fi

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
prefix="probe-cron-$$"
gmt="$prefix-gmt"
zoned="$prefix-zoned"

steps() {
  cat <<EOF
image:    $IMAGE_TAG (built from $here/Dockerfile if missing)
network:  $prefix
servers:  $gmt (pg_cron defaults), $zoned (cron.timezone = $ZONE)
F1  SHOW cron.timezone on both
F2  a job every 2 seconds whose run takes 5 s, for 15 s: overlaps and gaps between runs
F3  a job every 2 seconds that divides by zero: its rows, and the last success of F2's job
F4  the same daily schedule, the next whole minute but one in $ZONE's local time, on both servers
F5  a job every minute; $gmt stopped for 130 s, then started: which minutes ran
everything labelled probe.owner=$prefix is removed on exit
EOF
}

if [[ $mode == --dry-run ]]; then
  steps
  exit 0
fi

command -v docker >/dev/null || {
  printf 'pg-cron: docker is not on PATH\n' >&2
  exit 1
}

cleanup() {
  local ids
  ids=$(docker ps -aq --filter "label=probe.owner=$prefix" 2>/dev/null || true)
  if [[ -n $ids ]]; then
    # shellcheck disable=SC2086 # one container id per word is the intent
    docker rm -f $ids >/dev/null 2>&1 || true
  fi
  if [[ $prefix =~ ^probe-cron-[0-9]+$ ]]; then
    docker network rm "$prefix" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

progress() { printf '%s\n' "$*" >&2; }

if ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
  progress "building $IMAGE_TAG"
  docker build -q -t "$IMAGE_TAG" "$here" >/dev/null
fi

docker network create --label "probe.owner=$prefix" "$prefix" >/dev/null
docker run -d --name "$gmt" --label "probe.owner=$prefix" --network "$prefix" \
  -e POSTGRES_HOST_AUTH_METHOD=trust "$IMAGE_TAG" \
  -c shared_preload_libraries=pg_cron -c cron.database_name=postgres >/dev/null
docker run -d --name "$zoned" --label "probe.owner=$prefix" --network "$prefix" \
  -e POSTGRES_HOST_AUTH_METHOD=trust "$IMAGE_TAG" \
  -c shared_preload_libraries=pg_cron -c cron.database_name=postgres -c "cron.timezone=$ZONE" >/dev/null

# Runs psql in a container of its own against server $1, reading SQL from stdin.
psql_on() {
  docker run --rm -i --label "probe.owner=$prefix" --network "$prefix" "$IMAGE_TAG" \
    psql -h "$1" -U postgres -d postgres -qAtX -v ON_ERROR_STOP=0
}
sql() { printf '%s\n' "$2" | psql_on "$1" 2>&1; }

wait_ready() {
  local tries=0
  until docker run --rm --label "probe.owner=$prefix" --network "$prefix" "$IMAGE_TAG" \
    pg_isready -q -h "$1" 2>/dev/null && [[ $(sql "$1" 'SELECT 1') == 1 ]]; do
    tries=$((tries + 1))
    if ((tries > 90)); then
      printf 'pg-cron: %s did not start\n' "$1" >&2
      exit 1
    fi
    sleep 1
  done
}

wait_ready "$gmt"
wait_ready "$zoned"
sql "$gmt" 'CREATE EXTENSION pg_cron;' >/dev/null
sql "$zoned" 'CREATE EXTENSION pg_cron;' >/dev/null
progress "server $(sql "$gmt" 'SHOW server_version'), pg_cron $(sql "$gmt" "SELECT extversion FROM pg_extension WHERE extname = 'pg_cron'")"

printf 'F1 | cron.timezone by default | %s; with -c cron.timezone=%s: %s\n' \
  "$(sql "$gmt" 'SHOW cron.timezone')" "$ZONE" "$(sql "$zoned" 'SHOW cron.timezone')"

progress "F2 and F3: 15 s"
slow=$(sql "$gmt" "SELECT cron.schedule('slow', '2 seconds', 'SELECT pg_sleep(5)')")
fails=$(sql "$gmt" "SELECT cron.schedule('fails', '2 seconds', 'SELECT 1/0')")
if [[ ! $slow =~ ^[0-9]+$ || ! $fails =~ ^[0-9]+$ ]]; then
  printf 'pg-cron: cron.schedule failed: %s %s\n' "$slow" "$fails" >&2
  exit 1
fi
sleep 15
sql "$gmt" "SELECT cron.unschedule($slow); SELECT cron.unschedule($fails);" >/dev/null
sleep 6
printf 'F2 | every 2 seconds, each run 5 s, over 15 s | %s\n' "$(sql "$gmt" "
WITH runs AS (
  SELECT start_time, end_time, lag(end_time) OVER (ORDER BY start_time) AS previous_end
  FROM cron.job_run_details WHERE jobid = $slow AND status = 'succeeded')
SELECT count(*) || ' runs, ' || count(*) FILTER (WHERE start_time < previous_end)
  || ' started before the previous one ended, gaps between runs (s): '
  || coalesce(string_agg(round(extract(epoch FROM start_time - previous_end)::numeric, 2)::text, ', '
     ORDER BY start_time) FILTER (WHERE previous_end IS NOT NULL), 'none')
FROM runs")"
printf 'F3 | a failing job | %s\n' "$(sql "$gmt" "
SELECT count(*) || ' rows with status ' || string_agg(DISTINCT status, ',') || ', message: '
  || min(return_message)
FROM cron.job_run_details WHERE jobid = $fails")"
printf 'F3 | last success of the slow job | %s\n' "$(sql "$gmt" "
SELECT 'max(end_time) of succeeded runs is ' || round(extract(epoch FROM now() - max(end_time))::numeric)
  || ' s ago'
FROM cron.job_run_details WHERE jobid = $slow AND status = 'succeeded'")"

progress "F4: up to two minutes"
target=$(sql "$gmt" "SELECT to_char(date_trunc('minute', now() AT TIME ZONE '$ZONE') + interval '2 minutes', 'MI HH24')")
schedule="$target * * *"
for server in "$gmt" "$zoned"; do
  sql "$server" "CREATE TABLE fired (at timestamptz NOT NULL);
SELECT cron.schedule('daily', '$schedule', 'INSERT INTO fired VALUES (now())');" >/dev/null
done
# The target is at most 3 minutes away; 40 polls of 5 s cover it with a margin.
polls=0
until [[ $(sql "$zoned" 'SELECT count(*) FROM fired') == 1 ]] || ((polls >= 40)); do
  polls=$((polls + 1))
  sleep 5
done
sleep 5
printf "F4 | schedule '%s', the next whole minute but one in %s local time | %s server ran it at: %s; GMT server ran it: %s time(s) by then\n" \
  "$schedule" "$ZONE" "$ZONE" \
  "$(sql "$zoned" "SELECT coalesce(string_agg(to_char(at AT TIME ZONE '$ZONE', 'HH24:MI:SS') || ' $ZONE', ', '), 'never') FROM fired")" \
  "$(sql "$gmt" 'SELECT count(*) FROM fired')"

progress "F5: about four minutes"
sql "$gmt" "CREATE TABLE ticks (at timestamptz NOT NULL);
SELECT cron.schedule('tick', '* * * * *', 'INSERT INTO ticks VALUES (now())');" >/dev/null
polls=0
until [[ $(sql "$gmt" 'SELECT count(*) FROM ticks') == 1 ]]; do
  polls=$((polls + 1))
  if ((polls > 45)); then
    printf 'pg-cron: the every-minute job did not run within 90 s\n' >&2
    exit 1
  fi
  sleep 2
done
docker stop "$gmt" >/dev/null
stopped_at=$(date -u +%H:%M:%S)
sleep 130
docker start "$gmt" >/dev/null
started_at=$(date -u +%H:%M:%S)
wait_ready "$gmt"
sleep 75
printf 'F5 | every minute; server stopped %sZ, started %sZ | runs at: %s\n' "$stopped_at" "$started_at" \
  "$(sql "$gmt" "SELECT string_agg(to_char(at AT TIME ZONE 'UTC', 'HH24:MI:SS') || 'Z', ', ' ORDER BY at) FROM ticks")"
