# GABS Timetable Scraper

Scrapes every Golden Arrow Bus Services (GABS) timetable PDF from
<https://www.gabs.co.za/Timetable.aspx>, parses each into structured records, and
loads them into a local PostgreSQL database. The schema is designed to back a
read API.

Pipeline: **harvest → download → parse → load**, each stage idempotent.

- **harvest** — replays the site's ASP.NET letter-filter postbacks (a browser
  User-Agent is enough; no headless browser) and writes `data/manifest.json`
  (~1,868 PDFs across letters A–W, regular + Public-Holiday).
- **download** — fetches the static PDFs (not Cloudflare-protected) into
  `data/pdfs/` concurrently, with a SHA-256 per file.
- **parse** — `pdfplumber` reads each PDF's pipe-delimited grid into
  directions → day-types → stops × trips → individual departure times.
- **load** — upserts into Postgres, keyed on the unique PDF filename, replacing a
  timetable's child rows transactionally so re-runs never duplicate.

## Requirements

- Python 3.11+ (developed on 3.14)
- Docker Desktop (for the bundled PostgreSQL 16) — **must be running**

You do **not** need a separate PostgreSQL install: `docker compose` provides one.

## Quickstart on a shared copy (restore the prebuilt database)

If you received this as a zipped folder, it may include `data/gabs_dump.sql.gz`
— a full snapshot of the loaded database. This is the fastest path (seconds, no
re-parsing, no internet):

```bash
docker compose up -d                 # starts Postgres (host port 5433) + pgAdmin (http://localhost:5050)

# Restore the prebuilt database (works on Windows, macOS, Linux):
docker cp data/gabs_dump.sql.gz gabs_pg:/tmp/dump.sql.gz
docker exec gabs_pg sh -c "gunzip -f /tmp/dump.sql.gz && psql -U gabs -d gabs -f /tmp/dump.sql"
```

(`pip install -r requirements.txt` is only needed if they also want to run the
scraper or tests — not to view the restored data.)

Then browse it in pgAdmin at <http://localhost:5050> (server *GABS (local)*,
database password `gabs`) or connect any client to
`postgresql://gabs:gabs@localhost:5433/gabs`.

If the dump is **not** present, populate the database from the bundled PDFs
instead (parses ~1,868 PDFs, takes roughly 45–60 min):

```bash
PYTHONPATH=src python -m gabs_scraper.pipeline --load
```

> If host port **5433** is already in use on your machine, change `"5433:5432"`
> in `docker-compose.yml` to a free port (and update `DATABASE_URL`).

## Setup

```bash
# 1. Python deps
pip install -r requirements.txt

# 2. Start PostgreSQL (published on host port 5433 to avoid clashing with a
#    local 5432). Schema is applied automatically on first start.
docker compose up -d

# 3. (optional) copy env defaults
cp .env.example .env
```

The default connection string is `postgresql://gabs:gabs@localhost:5433/gabs`
(override via `DATABASE_URL`).

## Running

`src/` is the import root. On Windows PowerShell use `$env:PYTHONPATH="src"`.

```bash
# Everything: harvest + download + load + prune
PYTHONPATH=src python -m gabs_scraper.pipeline --all

# Smoke test on the first 20 PDFs (never prunes -- see below)
PYTHONPATH=src python -m gabs_scraper.pipeline --load --limit 20

# Individual stages
PYTHONPATH=src python -m gabs_scraper.pipeline --harvest
PYTHONPATH=src python -m gabs_scraper.pipeline --download
PYTHONPATH=src python -m gabs_scraper.pipeline --load

# Keep timetables GABS no longer publishes (not recommended)
PYTHONPATH=src python -m gabs_scraper.pipeline --all --no-prune
```

Re-running is safe and cheap: downloads skip existing files, and loads upsert on
the PDF filename. To refresh from the site, run `--all` again.

### Pruning: why a full load also deletes

GABS republishes timetables constantly — in one August 2026 check, only **366 of
1,868** stored versions were still published, while the site had moved on to 1,878.
Loading alone is upsert-only, so without a reconciliation step the database only ever
grows: the new versions get added and every superseded one stays, and the app keeps
serving departure times the operator has already withdrawn. That is worse than being
out of date, because a stale row looks exactly as authoritative as a current one.

So after a **full** load, the pipeline deletes any timetable whose PDF is absent from
the fresh manifest, plus any route left with no timetables. Deleting a timetable
cascades to its schedules, trips, stop_times and notes. Stops are deliberately kept:
they are shared across routes, carry geocoding, and are referenced by `leg_geometry`.

The download cache in `data/pdfs` is reconciled the same way, or it would grow by the
whole delta on every refresh. Superseded PDFs cannot be re-fetched — GABS removes them —
so the copies committed to git history are the archive; the working directory only holds
what is currently published.

Two guards, because this removes data:

- it **refuses to run against an empty manifest** — that is a harvest failure, not GABS
  withdrawing everything it publishes;
- it is **skipped whenever `--limit` is used**, since a sample would delete nearly the
  whole database. `--no-prune` opts out entirely.

Because the site churns this fast, treat the pipeline as a scheduled job rather than a
one-off. New routes also need `gabs_scraper.geocode` (stop coordinates) and
`gabs_scraper.geometry` (road paths for pin planning) afterwards — neither runs as part
of the pipeline.

## Web UI (route browser + map)

A small FastAPI server + React app with two views:

- **Plan a trip** (default): pick any boarding stop → see every stop reachable on a
  **single bus** (trip-level, so it never suggests a connection no bus actually makes) →
  pick a destination → get the buses, board→arrive times, and the journey drawn on a map.
  From/To can also be a **pin or place** (an *unofficial* stop a bus merely passes, e.g.
  Woodstock): each leg's real road path is precomputed via Google Directions
  (`gabs_scraper.geometry`, stored in `leg_geometry`), a pin is matched to legs whose road
  passes within ~700 m, and the boarding/arrival time is interpolated (shown as `≈`
  approximate). Pin geocoding at runtime uses OpenStreetMap (no key).
- **Browse routes**: search routes, view the stop × trip departure grid per
  direction/day-type, and see the route's stops on a map.

Stop coordinates are geocoded (**Google Geocoding primary, OpenStreetMap fallback**)
into the `stop` table.

Run it (needs only Python — the built UI ships in `web/dist`):

```bash
PYTHONPATH=src python -m uvicorn gabs_scraper.api:app --port 8000
# then open http://localhost:8000
```

Or run the **Java / Spring Boot** port of the same API, which listens on the same port
and serves the same UI (see [backend/README.md](backend/README.md)):

```bash
mvn -f backend/pom.xml spring-boot:run
```

API endpoints: `GET /api/routes?q=`, `GET /api/routes/{id}`, `GET /api/timetables/{id}`,
`GET /api/stops?q=`, `GET /api/stops/{id}/reachable`, `GET /api/journeys?from=&to=`.

Re-geocode stops (the Google key is read only from the environment — never stored):

```bash
# Google primary + OSM fallback:
GOOGLE_MAPS_API_KEY=your_key PYTHONPATH=src python -m gabs_scraper.geocode --force
# OSM only (no key):
PYTHONPATH=src python -m gabs_scraper.geocode --force
```

Develop / rebuild the UI (needs Node):

```bash
cd web && npm install
npm run dev     # http://localhost:5173 (proxies /api to :8000)
npm run build   # rebuilds web/dist that FastAPI serves
```

## Tests

```bash
python -m pytest -q
```

For the Java backend:

```bash
mvn -f backend/pom.xml test
```

The parser tests run against real sample PDFs committed under `tests/samples/`.
The loader tests require the Postgres container to be up (they skip otherwise).

## Web UI (route browser + map)

A small FastAPI server + React UI to browse routes, view the stop × trip departure
grid, and see stops on a map (geocoded via OpenStreetMap, no API key).

Prerequisites: data loaded (restore the dump or run the pipeline) and stop
coordinates geocoded. The bundled dump already includes coordinates; if you
populated from scratch, geocode once (~5 min, adds lat/lon to `stop`):

```bash
PYTHONPATH=src python -m gabs_scraper.geocode
```

Run it — the UI is prebuilt into `web/dist`, so only Python is needed:

```bash
PYTHONPATH=src python -m uvicorn gabs_scraper.api:app --port 8000
```

Open <http://localhost:8000>. API endpoints: `/api/health`, `/api/routes?q=`,
`/api/routes/{id}`, `/api/timetables/{id}`.

Rebuilding / developing the UI needs Node 18+:

```bash
cd web && npm install && npm run build      # rebuild the static bundle
# or, hot-reload dev (Vite :5173 proxying /api to the :8000 server):
cd web && npm run dev
```

## Data model

| Table | What it holds |
|---|---|
| `route` | Origin–destination pair (`AIRPORT IND-BELLVILLE`), letter group |
| `timetable` | One PDF version: number, PH flag, effective dates, URL, sha256, `raw_text`, `parse_status` |
| `stop` | Distinct stop / timing-point names |
| `schedule` | A (direction, day-type) block: direction label, `day_type`, `day_label`, per-page number, `no_service` |
| `schedule_stop` | Ordered stops of a schedule (`stop_sequence`) |
| `trip` | One bus run (a grid column), with footnote `note_codes` |
| `stop_time` | A cell: `cell_type` (TIME/VIA/NONE), `departure_time`, `note_code`, `raw_value` |
| `timetable_note` | Footnote codes (`a` → "Mondays,Tuesdays,…") |

`day_type` is a coarse bucket (`WEEKDAY`/`SATURDAY`/`SUNDAY`/`PUBLIC_HOLIDAY`/`OTHER`);
`day_label` preserves the exact PDF header (e.g. `MONDAYS TO FRIDAYS`). Public-holiday
PDFs occasionally bundle multiple routes across pages, so each `schedule` keeps its
own `direction_label` and `section_timetable_number`.

## Example queries (API-shaped)

```sql
-- All routes, alphabetically
SELECT name, letter_group FROM route ORDER BY name;

-- Every weekday departure from NYANGA TERM, earliest first
SELECT r.name, sc.direction_label, st.departure_time
FROM stop_time st
JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
JOIN stop s           ON s.id  = ss.stop_id
JOIN schedule sc      ON sc.id = ss.schedule_id
JOIN timetable t      ON t.id  = sc.timetable_id
JOIN route r          ON r.id  = t.route_id
WHERE s.name = 'NYANGA TERM'
  AND sc.day_type = 'WEEKDAY'
  AND st.cell_type = 'TIME'
ORDER BY st.departure_time;

-- One timetable, one direction, as a stop × trip grid (weekday)
SELECT ss.stop_sequence, s.name AS stop, tr.trip_index, st.raw_value
FROM stop_time st
JOIN trip tr          ON tr.id = st.trip_id
JOIN schedule sc      ON sc.id = tr.schedule_id
JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
JOIN stop s           ON s.id  = ss.stop_id
WHERE sc.timetable_id = (SELECT id FROM timetable
                         WHERE pdf_filename LIKE 'NYANGA%' LIMIT 1)
  AND sc.day_type = 'WEEKDAY'
ORDER BY tr.trip_index, ss.stop_sequence;

-- Which timetables failed to parse (kept with raw_text for re-parsing)?
SELECT pdf_filename, parse_error FROM timetable WHERE parse_status = 'failed';
```
