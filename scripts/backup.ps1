# A copy of the database you could actually restore from.
#
#   powershell -ExecutionPolicy Bypass -File scripts\backup.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\backup.ps1 -KeepDays 30 -Out D:\backups
#
# The database is weeks of scraping: 1.17 million departures parsed out of PDFs that the
# operators delete when they reissue them. Losing it does not mean re-running a script for
# an afternoon - the old PDFs are gone, so the history is gone with them.
#
# Schedule it daily, and keep a copy somewhere that is not this machine:
#
#   schtasks /create /tn "Commuttr backup" /sc daily /st 02:00 ^
#     /tr "powershell -ExecutionPolicy Bypass -File C:\path\to\scrapercomm\scripts\backup.ps1"
#
# It verifies each dump by reading it back before it deletes any older one, so a run that
# quietly produced a broken file cannot be the run that clears the last good copy.
#
# This one dumps from a local docker container, which is what a development machine has.
# The production database has no container to exec into: back that up with scripts/backup.sh
# on the server, which uses DATABASE_URL when it is set.

param(
    [string] $Out = "data/backups",
    [int] $KeepDays = 14,
    [string] $Container = "gabs_pg"
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
New-Item -ItemType Directory -Force -Path $Out | Out-Null

$stamp = Get-Date -Format "yyyy-MM-dd-HHmm"
$file = Join-Path $Out "commuttr-$stamp.sql.gz"
$inside = "/tmp/commuttr-backup.sql.gz"

# Dumped, compressed AND checked inside the container, then copied out.
#
# Piping a dump through PowerShell corrupts it: the pipeline carries strings, so a gzip
# stream comes out re-encoded and unreadable, and Set-Content -Encoding Byte refuses it
# outright. Keeping the bytes inside the container avoids the question, and copying one
# finished file is faster than streaming a gigabyte through two processes.
# One line, deliberately: a backtick continuation inside the quoted string is read by
# PowerShell but not by sh, which then saw the --exclude flags as commands of their own,
# dumped everything and wrote it to the screen instead of the file.
$excludes = "--exclude-table=search_analytics --exclude-table=search_analytics_option --exclude-table=place_search --exclude-table=app_error"
docker exec $Container sh -c "pg_dump -U gabs -d gabs --no-owner --no-privileges $excludes | gzip -9 > $inside"
if ($LASTEXITCODE -ne 0) { Write-Error "pg_dump failed - nothing was written."; exit 1 }

# Readable and complete, or it is not a backup. pg_dump ends a good file with this line.
# 20 lines, not 5: this Postgres writes an unrestrict line after the completion
# marker, so a five-line tail misses the very thing it is checking for.
$tail = docker exec $Container sh -c "gzip -dc $inside | tail -20"
# Joined first: -notmatch against an ARRAY returns the lines that do not match, which is
# nearly all of them, so the test passed as "not complete" on a perfectly good dump.
if (($tail -join "`n") -notmatch "PostgreSQL database dump complete") {
    docker exec $Container rm -f $inside
    Write-Error "The dump does not end cleanly - nothing was kept."
    exit 1
}

docker cp "${Container}:$inside" $file
docker exec $Container rm -f $inside
if (-not (Test-Path $file) -or (Get-Item $file).Length -lt 1MB) {
    Write-Error "The copied file is missing or far too small - not replacing anything."
    exit 1
}

$size = "{0:N1} MB" -f ((Get-Item $file).Length / 1MB)
Write-Host "wrote $file ($size)"

# Only now, with a verified new copy on disk, is an old one safe to remove.
Get-ChildItem $Out -Filter "commuttr-*.sql.gz" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
    ForEach-Object { Write-Host "removing $($_.Name)"; Remove-Item $_.FullName -Force }

Write-Host ""
Write-Host "To restore into an empty database:"
Write-Host "  gzip -dc <this file> | docker exec -i $Container psql -U gabs -d gabs"
