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

# The analytics tables are excluded: they are large, they rebuild from use, and a backup
# that carries them spreads anonymous ids to every copy of the file.
docker exec $Container pg_dump -U gabs -d gabs --no-owner --no-privileges `
    --exclude-table=search_analytics --exclude-table=search_analytics_option `
    --exclude-table=place_search |
    Set-Content -Path "$file.tmp" -Encoding Byte -ErrorAction Stop

if (-not (Test-Path "$file.tmp") -or (Get-Item "$file.tmp").Length -lt 1MB) {
    Write-Error "The dump is missing or far too small - not replacing anything."
    exit 1
}

# Readable and complete, or it is not a backup. pg_dump ends a good file with this line.
$tail = Get-Content "$file.tmp" -Tail 5 -ErrorAction SilentlyContinue
if ($tail -notmatch "PostgreSQL database dump complete") {
    Write-Error "The dump does not end cleanly - keeping it as $file.bad and stopping."
    Move-Item "$file.tmp" "$file.bad" -Force
    exit 1
}

Move-Item "$file.tmp" $file -Force
$size = "{0:N1} MB" -f ((Get-Item $file).Length / 1MB)
Write-Host "wrote $file ($size)"

# Only now, with a verified new copy on disk, is an old one safe to remove.
Get-ChildItem $Out -Filter "commuttr-*.sql.gz" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
    ForEach-Object { Write-Host "removing $($_.Name)"; Remove-Item $_.FullName -Force }

Write-Host ""
Write-Host "To restore into an empty database:"
Write-Host "  docker exec -i $Container psql -U gabs -d gabs < <this file, ungzipped>"
