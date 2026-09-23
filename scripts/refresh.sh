#!/usr/bin/env bash
# The same refresh as scripts/refresh.ps1, for a Linux server.
#
#   ./scripts/refresh.sh            # every operator
#   ./scripts/refresh.sh gabs       # one of them
#
# Fortnightly, in crontab, with the output kept. The 1st and the 15th rather than an
# interval, because cron has no fortnight and */14 on the day of the month restarts every
# month; these two dates are predictable and never drift:
#
#   0 3 1,15 * * cd /srv/scrapercomm && ./scripts/refresh.sh >> data/refresh-logs/cron.log 2>&1
#
# Exits 1 if a step failed and 2 if everything ran but the data is still stale, so a
# scheduler that reports failures reports this one.
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src

operators=("${@:-gabs myciti metrorail}")
log_dir=data/refresh-logs
mkdir -p "$log_dir"
log="$log_dir/refresh-$(date +%Y-%m-%d-%H%M).log"
failed=()

step() {
  local name="$1"; shift
  echo "=== $name ===" | tee -a "$log"
  if ! "$@" 2>&1 | tee -a "$log"; then
    echo "FAILED: $name" | tee -a "$log"
    failed+=("$name")
  fi
}

# Where the database is. On a development machine it is the docker container; in
# production it is whatever DATABASE_URL points at, which is usually managed Postgres with
# no container to exec into. Use psql directly when there is a URL and a psql to give it
# to, and fall back to the container otherwise, so a developer's machine needs no change.
#
# The loaders read DATABASE_URL themselves (gabs_scraper.config), so setting that one
# variable moves this whole script onto the production database.
if [ -n "${DATABASE_URL:-}" ] && command -v psql >/dev/null 2>&1; then
  sql() { psql "$DATABASE_URL" -At -c "$1"; }
  where="DATABASE_URL"
else
  sql() { docker exec "${CONTAINER:-gabs_pg}" psql -U gabs -d gabs -At -c "$1"; }
  where="container ${CONTAINER:-gabs_pg}"
fi

if ! sql "SELECT 1" >/dev/null 2>&1; then
  echo "No database answering at $where." | tee -a "$log"
  echo "Locally: docker compose up -d. On a server: export DATABASE_URL and install psql." | tee -a "$log"
  exit 1
fi
echo "database: $where" | tee -a "$log"

# On the record before it starts, so the dashboard shows a run in progress and an
# interrupted load leaves an unfinished row rather than silence.
run_id=$(sql "INSERT INTO refresh_run (operators) VALUES ('${operators[*]}') RETURNING id" | head -1)
echo "run $run_id" | tee -a "$log"

case " ${operators[*]} " in *" gabs "*)
  step "golden arrow" python -m gabs_scraper.pipeline --all
  # Golden Arrow deletes a PDF the day it reissues, so links rot faster than the data.
  step "golden arrow pdf links" python -m gabs_scraper.relink --fix
;; esac
case " ${operators[*]} " in *" myciti "*)
  step "myciti" python -m myciti_scraper.pipeline
  # The City publishes every MyCiTi stop with its coordinates; none has to be guessed at.
  step "myciti positions" python -m myciti_scraper.official_positions --fix
;; esac
# prasa_scraper.sheets, not prasa_scraper.pipeline. PRASA publishes every Cape Town
# timetable as a spreadsheet, where the times are real values; the pipeline beside it reads
# the PDFs by OCR and is the fallback for services published only as images. The sheets
# give all 16 timetables both ways including Saturdays, the OCR path 6 inbound-only ones -
# so a refresh that ran the OCR path would quietly take away every homeward train.
case " ${operators[*]} " in *" metrorail "*)
  # PRASA publishes these as spreadsheets on a WordPress site. Until this existed nothing
  # fetched them, so a refresh re-read September's files forever while writing a new
  # scraped_at - the status page called train data fresh for as long as nobody checked.
  step "metrorail sheets" python -m prasa_scraper.fetch --download
  step "metrorail" python -m prasa_scraper.sheets
;; esac

# The planner's precomputed floors and ceilings are a pure function of the departures any
# of the three loaders just wrote, so they are rebuilt once here rather than recomputed on
# every search. Stale, it would answer with the last load's times - so it runs every time,
# whichever operator ran. It reports and does nothing if the view has not been created.
step "planner context" python -m gabs_scraper.context --fix

# Built FROM the stops a load creates, so they come after it.
step "stop positions" python -m gabs_scraper.repair_positions
step "stops with no position" python -m gabs_scraper.place_missing --fix
step "station positions" python -m prasa_scraper.repair_positions --fix
step "areas" python -m gabs_scraper.areas --from-stops
# The policy promises the anonymous id is cleared after twelve months; this keeps it true.
step "forget old ids" python -m gabs_scraper.retention --fix
# Repairs delete the road paths they invalidate, so this redraws them.
step "road paths" python -m gabs_scraper.geometry

# The API holds place searches and the operator list for the life of the process, which
# is right until a load changes them underneath it.
if [ -n "${COMMUTTR_API_URL:-}" ] && [ -n "${COMMUTTR_ADMIN_TOKEN:-}" ]; then
  step "api caches" curl -fsS -X POST "$COMMUTTR_API_URL/api/admin/caches/clear"     -H "Authorization: Bearer $COMMUTTR_ADMIN_TOKEN"
else
  echo "skipping the API cache clear: set COMMUTTR_API_URL and COMMUTTR_ADMIN_TOKEN to enable it" | tee -a "$log"
fi

echo "=== freshness ===" | tee -a "$log"
python -m gabs_scraper.freshness --check 2>&1 | tee -a "$log"
stale=$?

detail=""
[ ${#failed[@]} -gt 0 ] && detail="failed: ${failed[*]}"
[ -z "$detail" ] && [ "$stale" -ne 0 ] && detail="ran, but the data is still older than its limits"
ok=$([ ${#failed[@]} -eq 0 ] && [ "$stale" -eq 0 ] && echo true || echo false)

# Doubled quotes, so a step name with an apostrophe in it cannot end the SQL string.
detail_sql=$(printf '%s' "$detail" | sed "s/'/''/g")
sql "UPDATE refresh_run SET finished_at = now(), ok = $ok, detail = nullif('$detail_sql', ''), log_path = '$log' WHERE id = $run_id" >/dev/null
# Whatever the outcome, a request from the dashboard has been acted on; the run row says how.
sql "UPDATE refresh_request SET done_at = now(), run_id = $run_id WHERE done_at IS NULL" >/dev/null

if [ ${#failed[@]} -gt 0 ]; then
  echo "Steps that failed: ${failed[*]}. Log: $log" | tee -a "$log"
  exit 1
fi
[ "$stale" -ne 0 ] && { echo "Every step ran, but the data is still stale. Log: $log" | tee -a "$log"; exit 2; }
echo "Done. Log: $log" | tee -a "$log"
