#!/usr/bin/env bash
# The same backup as scripts/backup.ps1, for a Linux server.
#
#   ./scripts/backup.sh                    # into data/backups, keeping 14 days
#   ./scripts/backup.sh /srv/backups 30
#
# Daily, and copied off this machine:
#   0 2 * * * cd /srv/scrapercomm && ./scripts/backup.sh >> data/backups/cron.log 2>&1
#
# Each dump is verified by reading it back before any older one is deleted, so a broken
# run cannot be the run that clears the last good copy.
set -euo pipefail
cd "$(dirname "$0")/.."

out="${1:-data/backups}"
keep_days="${2:-14}"
container="${CONTAINER:-gabs_pg}"
mkdir -p "$out"

file="$out/commuttr-$(date +%Y-%m-%d-%H%M).sql.gz"

# Analytics is excluded: large, rebuilt by use, and it would spread anonymous ids into
# every copy of the file.
excludes=(--exclude-table=search_analytics --exclude-table=search_analytics_option
          --exclude-table=place_search --exclude-table=app_error)

# In production the database is whatever DATABASE_URL points at and there is no container
# to exec into, so use pg_dump directly when there is one. The container is the fallback,
# which is what a development machine has.
if [ -n "${DATABASE_URL:-}" ] && command -v pg_dump >/dev/null 2>&1; then
  pg_dump "$DATABASE_URL" --no-owner --no-privileges "${excludes[@]}" | gzip -9 > "$file.tmp"
else
  docker exec "$container" pg_dump -U gabs -d gabs --no-owner --no-privileges \
    "${excludes[@]}" | gzip -9 > "$file.tmp"
fi

if [ ! -s "$file.tmp" ] || [ "$(stat -c%s "$file.tmp")" -lt 1000000 ]; then
  echo "The dump is missing or far too small - not replacing anything." >&2
  exit 1
fi
# 20 lines, not 5: this Postgres writes an unrestrict line after the completion marker.
if ! gzip -dc "$file.tmp" | tail -20 | grep -q "PostgreSQL database dump complete"; then
  echo "The dump does not end cleanly - keeping it as $file.bad and stopping." >&2
  mv "$file.tmp" "$file.bad"
  exit 1
fi

mv "$file.tmp" "$file"
echo "wrote $file ($(du -h "$file" | cut -f1))"

find "$out" -name 'commuttr-*.sql.gz' -mtime "+$keep_days" -print -delete

echo
echo "To restore into an empty database:"
echo "  gzip -dc $file | docker exec -i $container psql -U gabs -d gabs"
