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

echo "=== freshness ===" | tee -a "$log"
python -m gabs_scraper.freshness --check 2>&1 | tee -a "$log"
stale=$?

if [ ${#failed[@]} -gt 0 ]; then
  echo "Steps that failed: ${failed[*]}. Log: $log" | tee -a "$log"
  exit 1
fi
[ "$stale" -ne 0 ] && { echo "Every step ran, but the data is still stale. Log: $log" | tee -a "$log"; exit 2; }
echo "Done. Log: $log" | tee -a "$log"
