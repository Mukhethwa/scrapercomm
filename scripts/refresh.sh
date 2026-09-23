#!/usr/bin/env bash
# The same refresh as scripts/refresh.ps1, for a Linux server.
#
#   ./scripts/refresh.sh            # every operator
#   ./scripts/refresh.sh gabs       # one of them
#
# Weekly, in crontab, with the output kept:
#
#   0 3 * * 0 cd /srv/scrapercomm && ./scripts/refresh.sh >> data/refresh-logs/cron.log 2>&1
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

if ! docker exec gabs_pg psql -U gabs -d gabs -c "SELECT 1" >/dev/null 2>&1; then
  echo "The database container is not running. Start it with: docker compose up -d" | tee -a "$log"
  exit 1
fi

sql() { docker exec gabs_pg psql -U gabs -d gabs -At -c "$1"; }

# On the record before it starts, so the dashboard shows a run in progress and an
# interrupted load leaves an unfinished row rather than silence.
run_id=$(sql "INSERT INTO refresh_run (operators) VALUES ('${operators[*]}') RETURNING id")
echo "run $run_id" | tee -a "$log"

case " ${operators[*]} " in *" gabs "*)
  step "golden arrow" python -m gabs_scraper.pipeline
  # Golden Arrow deletes a PDF the day it reissues, so links rot faster than the data.
  step "golden arrow pdf links" python -m gabs_scraper.relink --fix
;; esac
case " ${operators[*]} " in *" myciti "*)    step "myciti"    python -m myciti_scraper.pipeline ;; esac
case " ${operators[*]} " in *" metrorail "*) step "metrorail" python -m prasa_scraper.pipeline ;; esac

# Built FROM the stops a load creates, so they come after it.
step "stop positions" python -m gabs_scraper.repair_positions
step "station positions" python -m prasa_scraper.repair_positions --fix
step "areas" python -m gabs_scraper.areas --from-stops

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

sql "UPDATE refresh_run SET finished_at = now(), ok = $ok, detail = nullif('${detail//'/''}', ''), log_path = '$log' WHERE id = $run_id" >/dev/null
# Whatever the outcome, a request from the dashboard has been acted on; the run row says how.
sql "UPDATE refresh_request SET done_at = now(), run_id = $run_id WHERE done_at IS NULL" >/dev/null

if [ ${#failed[@]} -gt 0 ]; then
  echo "Steps that failed: ${failed[*]}. Log: $log" | tee -a "$log"
  exit 1
fi
[ "$stale" -ne 0 ] && { echo "Every step ran, but the data is still stale. Log: $log" | tee -a "$log"; exit 2; }
echo "Done. Log: $log" | tee -a "$log"
