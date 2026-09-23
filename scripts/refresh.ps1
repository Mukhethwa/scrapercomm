# Reload the operators' timetables, and say so loudly when it does not work.
#
#   powershell -ExecutionPolicy Bypass -File scripts\refresh.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\refresh.ps1 -Operators gabs
#
# Nothing refreshed on its own until this existed. Golden Arrow reissues weekly, we
# loaded when somebody remembered, and on 23 September 2026 the data was 18 days old with
# a third of its timetables already ended - while every screen in the app looked exactly
# as confident as it does with fresh data.
#
# Schedule it fortnightly (see README, "Keeping the data fresh"):
#
#   schtasks /create /tn "Commuttr refresh" /sc weekly /mo 2 /d SUN /st 03:00 ^
#     /tr "powershell -ExecutionPolicy Bypass -File C:\path\to\scrapercomm\scripts\refresh.ps1"
#
# It is safe to run at any time: each loader upserts, and the API reads whatever is
# committed. It writes a log per run and exits non-zero if the data is still stale
# afterwards, so a task that silently stopped working shows up as a failed task.

param(
    [string[]] $Operators = @("gabs", "myciti", "metrorail"),
    [string] $LogDir = "data/refresh-logs",
    # Where the API is, and its dashboard token, so this can tell it to re-read what it
    # holds in memory. Without them the load still works; the API keeps answering place
    # searches from before the load until somebody restarts it.
    [string] $ApiUrl = $env:COMMUTTR_API_URL,
    [string] $AdminToken = $env:COMMUTTR_ADMIN_TOKEN
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONPATH = "src"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$log = Join-Path $LogDir ("refresh-" + (Get-Date -Format "yyyy-MM-dd-HHmm") + ".log")
$failed = @()

function Step($name, [scriptblock] $work) {
    "=== $name ===" | Tee-Object -FilePath $log -Append
    try {
        & $work 2>&1 | Tee-Object -FilePath $log -Append
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "exit $LASTEXITCODE" }
    } catch {
        "FAILED: $name - $_" | Tee-Object -FilePath $log -Append
        $script:failed += $name
    }
}

# Where the database is. On a development machine it is the docker container; in
# production it is whatever DATABASE_URL points at, which is usually managed Postgres with
# no container to exec into. Use psql directly when there is a URL and a psql to give it
# to, and fall back to the container otherwise, so a developer's machine needs no change.
#
# The loaders read DATABASE_URL themselves (gabs_scraper.config), so setting that one
# variable moves this whole script onto the production database.
$container = if ($env:CONTAINER) { $env:CONTAINER } else { "gabs_pg" }
$direct = $env:DATABASE_URL -and (Get-Command psql -ErrorAction SilentlyContinue)
$dbWhere = if ($direct) { "DATABASE_URL" } else { "container $container" }

function Sql($statement) {
    if ($direct) { psql $env:DATABASE_URL -At -c $statement }
    else { docker exec $container psql -U gabs -d gabs -At -c $statement }
}

# The database has to be up before anything else is worth trying.
Step "database" { Sql "SELECT 1" }
if ($failed.Count -gt 0) {
    "No database answering at $dbWhere." | Tee-Object -FilePath $log -Append
    "Locally: docker compose up -d. On a server: set DATABASE_URL and install psql." | Tee-Object -FilePath $log -Append
    exit 1
}
"database: $dbWhere" | Tee-Object -FilePath $log -Append

# The run goes on the record before it starts, so the dashboard can show one in progress
# and, if this machine dies mid-load, an unfinished row rather than silence.
$runId = (Sql "INSERT INTO refresh_run (operators) VALUES ('$($Operators -join " ")') RETURNING id") | Select-Object -First 1
"run $runId" | Tee-Object -FilePath $log -Append

if ($Operators -contains "gabs") {
    Step "golden arrow" { python -m gabs_scraper.pipeline --all }
    # The PDF links rot faster than anything else: Golden Arrow deletes a file the day it
    # reissues, so a link loaded last week is a 404 this week.
    Step "golden arrow pdf links" { python -m gabs_scraper.relink --fix }
}
if ($Operators -contains "myciti") {
    Step "myciti" { python -m myciti_scraper.pipeline }
    # The City publishes every MyCiTi stop with its coordinates, so none of them has to
    # be guessed at: this places the ones OpenStreetMap does not have.
    Step "myciti positions" { python -m myciti_scraper.official_positions --fix }
}
# prasa_scraper.sheets, not prasa_scraper.pipeline. PRASA publishes every Cape Town
# timetable as a spreadsheet, where the times are real values; the pipeline beside it reads
# the PDFs by OCR and is the fallback for services published only as images. The sheets
# give all 16 timetables both ways including Saturdays, the OCR path 6 inbound-only ones -
# so a refresh that ran the OCR path would quietly take away every homeward train.
if ($Operators -contains "metrorail") { Step "metrorail" { python -m prasa_scraper.sheets } }

# The planner's precomputed floors and ceilings are a pure function of the departures any
# of the three loaders just wrote, so they are rebuilt once here rather than recomputed on
# every search. Stale, it would answer with the last load's times - so it runs every time,
# whichever operator ran. It reports and does nothing if the view has not been created.
Step "planner context" { python -m gabs_scraper.context --fix }

# Positions and areas are built FROM the stops a load creates, so they come after it.
Step "stop positions" { python -m gabs_scraper.repair_positions }
Step "stops with no position" { python -m gabs_scraper.place_missing --fix }
Step "station positions" { python -m prasa_scraper.repair_positions --fix }
Step "areas" { python -m gabs_scraper.areas --from-stops }
# The privacy policy promises the anonymous id is cleared after twelve months. This is
# the job that keeps that sentence true.
Step "forget old ids" { python -m gabs_scraper.retention --fix }
# Repairs delete the road paths they invalidate, so this redraws them.
Step "road paths" { python -m gabs_scraper.geometry }

# The API caches place searches and the operator list for the life of the process, which
# is right until a load changes them underneath it.
if ($ApiUrl -and $AdminToken) {
    Step "api caches" {
        Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/admin/caches/clear" `
            -Headers @{ Authorization = "Bearer $AdminToken" } | Out-Null
        "told the API to re-read places and operators"
    }
} else {
    "skipping the API cache clear: set COMMUTTR_API_URL and COMMUTTR_ADMIN_TOKEN to enable it" |
        Tee-Object -FilePath $log -Append
}

"=== freshness ===" | Tee-Object -FilePath $log -Append
python -m gabs_scraper.freshness --check 2>&1 | Tee-Object -FilePath $log -Append
$stale = $LASTEXITCODE -ne 0

$detail = ""
if ($failed.Count -gt 0) { $detail = "failed: $($failed -join ', ')" }
elseif ($stale)          { $detail = "ran, but the data is still older than its limits" }
$ok = if ($failed.Count -eq 0 -and -not $stale) { "true" } else { "false" }

Sql "UPDATE refresh_run SET finished_at = now(), ok = $ok, detail = nullif('$($detail -replace "'", "''")', ''), log_path = '$($log -replace "'", "''")' WHERE id = $runId" | Out-Null
# Anything asked for from the dashboard has now been done, whatever the outcome: the
# request was for a reload attempt, and the row above says how it went.
Sql "UPDATE refresh_request SET done_at = now(), run_id = $runId WHERE done_at IS NULL" | Out-Null

if ($failed.Count -gt 0) {
    "`nSteps that failed: $($failed -join ', '). Log: $log" | Tee-Object -FilePath $log -Append
    exit 1
}
if ($stale) {
    "`nEvery step ran, but the data is still older than its limits. Log: $log" | Tee-Object -FilePath $log -Append
    exit 2
}
"`nDone. Log: $log" | Tee-Object -FilePath $log -Append
