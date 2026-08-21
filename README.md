# Commuttr — Cape Town bus journey planner

Commuttr tells a commuter which Golden Arrow bus to catch, from where, and at what time.

Golden Arrow publishes its timetables as roughly 1,900 PDF files on
<https://www.gabs.co.za/Timetable.aspx> — readable by a person, useless to software. This
project downloads every one of them, reads the departure grids out of them, stores the
result in a database, and serves it through an API that a React app turns into a trip
planner.

**New here? Jump to [Getting it running](#getting-it-running).**
**Just want a command? Jump to [Command reference](#command-reference).**

---

## Contents

- [What's in the box](#whats-in-the-box)
- [Before you start](#before-you-start)
- [Getting it running](#getting-it-running) — start to finish, six steps
- [Command reference](#command-reference) — every command, what it does, when you need it
- [Looking inside the database](#looking-inside-the-database)
- [Reading the search analytics](#reading-the-search-analytics)
- [Refreshing the timetables](#refreshing-the-timetables)
- [How the pieces fit together](#how-the-pieces-fit-together)
- [Data model](#data-model)
- [Example queries](#example-queries)
- [Troubleshooting](#troubleshooting)

---

## What's in the box

Four separate pieces. You can run them independently.

| Piece | What it is | Lives in |
| --- | --- | --- |
| **The database** | PostgreSQL, running inside Docker. Holds every route, timetable and departure time. | `docker-compose.yml` |
| **The scraper** | Python. Fetches PDFs from the Golden Arrow site and loads them into the database. Run occasionally, not continuously. | `src/gabs_scraper/` |
| **The API** | Serves the data over HTTP. **Two versions exist** — a Java/Spring Boot one and the original Python one. They behave identically; run either. | `backend/` (Java), `src/gabs_scraper/api.py` (Python) |
| **The web app** | React. What a commuter actually sees — search, map, departure times. | `web/` |

### Which ports things use

| Port | What's there |
| --- | --- |
| **5433** | PostgreSQL (the database itself) |
| **5050** | pgAdmin — click around the database in a browser |
| **8000** | The API (Java *or* Python — they use the same port, so run one at a time) |
| **5173** | The React app in development mode |

Port 5433 rather than the usual 5432, so this doesn't clash with any PostgreSQL you
already have installed.

---

## Before you start

| You need | Why | Check it works |
| --- | --- | --- |
| **Docker Desktop**, running | Provides the database. Nothing works without it. | `docker version` |
| **Java 21+** and **Maven** | Only if running the Java API | `java -version` and `mvn -v` |
| **Python 3.11+** | Only if running the scraper, the Python API, or the tests | `python --version` |
| **Node 18+** | To build the web app (`web/dist` is not committed, so you build it once) | `node --version` |

You do **not** need to install PostgreSQL. Docker provides it.

---

## Getting it running

Six steps, in order. Steps 1–5 get you a working app; step 6 is only for frontend work.

### Step 1 — Start the database

This starts two containers: PostgreSQL, and pgAdmin for browsing it.

```bash
docker compose up -d
```

`-d` means "in the background". Check both started:

```bash
docker compose ps
```

You should see `gabs_pg` and `gabs_pgadmin`, both `Up`.

### Step 2 — Put the timetable data in

The repository ships a snapshot of the fully-loaded database, so you don't have to
download and parse 1,900 PDFs yourself. **This takes seconds.**

```bash
docker cp data/gabs_dump.sql.gz gabs_pg:/tmp/dump.sql.gz
docker exec gabs_pg sh -c "gunzip -f /tmp/dump.sql.gz && psql -U gabs -d gabs -f /tmp/dump.sql"
```

Confirm it worked:

```bash
docker exec gabs_pg psql -U gabs -d gabs -c "SELECT count(*) FROM timetable"
```

Around **1,878** is right.

> No snapshot in your copy? See [Refreshing the timetables](#refreshing-the-timetables) to
> build the database from the live site instead. That takes about 90 minutes.

### Step 3 — Start the API

Pick **one**. Both serve identical responses on port 8000.

**Java / Spring Boot** — the current backend:

```bash
mvn -f backend/pom.xml spring-boot:run
```

**Python / FastAPI** — the original, still maintained:

```bash
PYTHONPATH=src python -m uvicorn gabs_scraper.api:app --port 8000
```

On Windows PowerShell, set the path separately first: `$env:PYTHONPATH="src"`.

Check it's alive:

```bash
curl http://localhost:8000/api/health
```

### Step 4 — Build the web app, once

The built app is **not** stored in the repository, so build it before the first run.
After that you only repeat this when the frontend changes.

```bash
cd web
npm install     # first time only
npm run build
```

That writes `web/dist`, which the API serves. **Restart the API afterwards** — it only
looks for the built app at startup, so a running one will not pick it up.

### Step 5 — Open the app

**Open <http://localhost:8000>.** That's the whole app.

If you see `{"detail":"Not Found"}` instead, the API started before `web/dist` existed.
Restart it and reload.

### Step 6 — Only if you're changing the React code

Skip this unless you're editing the frontend. It gives you hot reload, so you don't have
to rebuild after every change.

```bash
cd web && npm run dev
```

Now use **<http://localhost:5173>** instead. It forwards API calls to port 8000, so
**leave the API from Step 3 running**.

---

## Command reference

Every command, what it does, and when you'd reach for it.

### `docker compose up -d`

**Starts the database.** Run this first, every time. Safe to run when it's already up.

```bash
docker compose up -d
```

### `docker compose ps`

**Shows whether the database is running.** First thing to check when something won't
connect.

```bash
docker compose ps
```

### `docker compose stop`

**Pauses the database, keeping all data.** Use at the end of the day.

```bash
docker compose stop
```

### `docker compose down`

**Stops and removes the containers — but keeps the data.** The data lives in a Docker
volume that survives this. Use `docker compose up -d` to bring everything back.

```bash
docker compose down
```

> **Careful:** `docker compose down -v` adds `-v` for *volumes* and **erases the database
> permanently.** Only use it when you deliberately want to start over.

### `mvn -f backend/pom.xml spring-boot:run`

**Starts the Java API on port 8000.** This is the main backend. Leave it running; stop it
with `Ctrl+C`.

```bash
mvn -f backend/pom.xml spring-boot:run
```

### `PYTHONPATH=src python -m uvicorn gabs_scraper.api:app --port 8000`

**Starts the Python API on port 8000.** The original backend. Same responses as the Java
one — run one or the other, not both.

```bash
PYTHONPATH=src python -m uvicorn gabs_scraper.api:app --port 8000
```

### `npm run dev`

**Starts the React app with hot reload on port 5173.** Only for frontend work. Needs an
API running on port 8000.

```bash
cd web && npm run dev
```

### `npm run build`

**Builds the React app** into `web/dist`, which the API serves at port 8000. Required
once before the first run, since `web/dist` is not committed, and again after any
frontend change. Restart the API afterwards — it looks for the built app only at startup.

```bash
cd web && npm run build
```

### `python -m gabs_scraper.pipeline --all`

**Downloads the latest timetables from Golden Arrow and loads them.** Takes roughly
90 minutes. See [Refreshing the timetables](#refreshing-the-timetables) before running it —
it also *deletes* withdrawn timetables.

```bash
PYTHONPATH=src python -m gabs_scraper.pipeline --all
```

### `python -m gabs_scraper.geocode`

**Puts new stops on the map.** After a refresh, new stops have names but no coordinates.
This looks each one up. Uses Google if `GOOGLE_MAPS_API_KEY` is set, otherwise
OpenStreetMap for free.

```bash
PYTHONPATH=src python -m gabs_scraper.geocode
```

### `python -m gabs_scraper.geometry`

**Works out the roads each bus actually drives.** Needed for custom-stop planning ("I'm
not at a bus stop, which bus passes me?"). **Requires `GOOGLE_MAPS_API_KEY`** — there is no
free alternative for this one.

```bash
PYTHONPATH=src python -m gabs_scraper.geometry
```

### `python -m pytest -q`

**Runs the Python tests.**

```bash
python -m pytest -q
```

### `mvn -f backend/pom.xml test`

**Runs the Java tests.**

```bash
mvn -f backend/pom.xml test
```

### `python backend/parity_check.py`

**Checks the Java and Python APIs still return identical answers.** Both must be running,
on different ports. Used before switching production from one to the other.

```bash
python backend/parity_check.py --legacy http://localhost:8001 --java http://localhost:8000
```

---

## Looking inside the database

### Where the data actually lives

The database runs inside a Docker **container** called `gabs_pg`. The container is
disposable — the data is not. PostgreSQL writes into a Docker **volume** named
`scrapercomm_gabs_pgdata`, which lives on your machine independently of the container.

That means:

- Restarting or rebuilding the container **keeps** your data.
- `docker compose down` **keeps** your data.
- Only `docker compose down -v` deletes it.

See the volumes:

```bash
docker volume ls --filter name=scrapercomm
```

### Option A — pgAdmin, by clicking

Easiest if you'd rather not type SQL.

1. Make sure the database is running (`docker compose up -d`)
2. Open **<http://localhost:5050>**
3. The server **GABS (local)** is already set up — click it
4. Password: `gabs`
5. Expand **Databases → gabs → Schemas → public → Tables**
6. Right-click any table → **View/Edit Data → All Rows**

### Option B — psql, by typing

Opens a SQL prompt inside the container:

```bash
docker exec -it gabs_pg psql -U gabs -d gabs
```

Useful once you're there:

| Type this | It shows |
| --- | --- |
| `\dt` | every table |
| `\d timetable` | the columns of the `timetable` table |
| `SELECT count(*) FROM route;` | how many routes exist |
| `\q` | quit |

Or run a single query without going in:

```bash
docker exec gabs_pg psql -U gabs -d gabs -c "SELECT count(*) FROM route"
```

### A quick health check

```bash
docker exec gabs_pg psql -U gabs -d gabs -c "
SELECT (SELECT count(*) FROM route)     AS routes,
       (SELECT count(*) FROM timetable) AS timetables,
       (SELECT count(*) FROM stop)      AS stops"
```

Roughly 793 routes, 1,878 timetables and 527 stops as of August 2026. These grow as
Golden Arrow adds services.

### Connecting any other tool

```
Host: localhost      Port: 5433
Database: gabs       User: gabs       Password: gabs
```

---

## Reading the search analytics

Every journey search is recorded, so you can see what commuters are actually looking for.
Recording happens in the background and never slows a search down.

### What gets recorded

Two tables:

| Table | One row per | Tells you |
| --- | --- | --- |
| `search_analytics` | search | where they searched from and to, how many results came back, how long it took |
| `search_analytics_option` | route offered | **which** routes came back, and how many departures each had |

The second table is what makes "which routes are people searching for?" answerable. The
first only counts results; it doesn't say which.

> Nothing is recorded about *who* searched — no names, no accounts, no session tracking.
> These are counts of searches, not of people.

### Which routes are commuters searching for?

The headline question.

```sql
SELECT o.route_label,
       o.timetable_number,
       o.day_type,
       count(DISTINCT o.search_id) AS searches,
       sum(o.departure_count)      AS departures_offered
FROM search_analytics_option o
GROUP BY 1, 2, 3
ORDER BY searches DESC
LIMIT 20;
```

### Which journeys are most popular?

Origin and destination, with real stop names instead of ID numbers.

```sql
SELECT COALESCE(so.name, 'dropped pin') AS origin,
       COALESCE(sd.name, 'dropped pin') AS destination,
       count(*) AS searches,
       round(avg(sa.option_count), 1) AS avg_results
FROM search_analytics sa
LEFT JOIN stop so ON so.id = sa.from_stop_id
LEFT JOIN stop sd ON sd.id = sa.to_stop_id
GROUP BY 1, 2
ORDER BY searches DESC
LIMIT 20;
```

### Where are we letting people down?

**The most valuable query here.** Every row is someone who searched for a journey and got
nothing back — a route Golden Arrow doesn't run, or one we don't have data for.

```sql
SELECT COALESCE(so.name, 'dropped pin') AS origin,
       COALESCE(sd.name, 'dropped pin') AS destination,
       count(*) AS failed_searches
FROM search_analytics sa
LEFT JOIN stop so ON so.id = sa.from_stop_id
LEFT JOIN stop sd ON sd.id = sa.to_stop_id
WHERE sa.option_count = 0
GROUP BY 1, 2
ORDER BY failed_searches DESC
LIMIT 20;
```

### When do people search?

```sql
SELECT date_trunc('hour', searched_at) AS hour, count(*) AS searches
FROM search_analytics
GROUP BY 1 ORDER BY 1 DESC LIMIT 24;
```

### Bus stops versus dropped pins

Shows how many people search from a real stop versus a point on the map, and what each
costs in response time.

```sql
SELECT endpoint,
       from_kind AS searched_from,
       count(*) AS searches,
       round(avg(option_count), 1) AS avg_results,
       round(avg(duration_ms))     AS avg_milliseconds
FROM search_analytics
GROUP BY 1, 2 ORDER BY 1, 2;
```

### Turning analytics off

Start the Java API with `ANALYTICS_ENABLED=false`. Searches keep working; nothing is
recorded.

---

## Refreshing the timetables

Golden Arrow republishes timetables constantly — 16 changed during a single afternoon in
August 2026, and many files expire within days. **Data goes stale fast.** This should
eventually run on a schedule rather than by hand.

### The full cycle

Three commands, in this order:

```bash
# 1. Download and load the latest timetables (~90 minutes)
PYTHONPATH=src python -m gabs_scraper.pipeline --all

# 2. Put any new stops on the map (~5 minutes)
PYTHONPATH=src python -m gabs_scraper.geocode

# 3. Work out the roads for any new routes (needs a Google key)
PYTHONPATH=src python -m gabs_scraper.geometry
```

Steps 2 and 3 are **not** part of step 1. Skip them and new routes will work for
stop-to-stop journeys but not for custom-stop planning.

### Why a refresh also deletes things

This surprises people, so it's worth understanding.

The pipeline used to only ever *add*. That sounds safe, but it isn't: when Golden Arrow
replaces a timetable, the old one stayed in our database forever and the app kept showing
withdrawn departure times. In one check, only **366 of 1,868** stored timetables were
still published — the other 1,502 were showing times no bus was running.

A stale timetable looks exactly as trustworthy as a current one. That's worse than having
no data.

So a **full** refresh now deletes any timetable Golden Arrow no longer publishes, along
with the downloaded PDF. Two safety nets:

- If the download from the site returns nothing, it **refuses to delete anything** — that's
  a failed download, not Golden Arrow withdrawing every route.
- If you're testing with `--limit`, **nothing is deleted**, because you only fetched a
  sample.

Add `--no-prune` to keep the old data anyway. Not recommended.

### Other pipeline options

```bash
# Just check the download works, on 20 PDFs. Never deletes anything.
PYTHONPATH=src python -m gabs_scraper.pipeline --load --limit 20

# Individual stages
PYTHONPATH=src python -m gabs_scraper.pipeline --harvest    # find what's published
PYTHONPATH=src python -m gabs_scraper.pipeline --download   # fetch the PDFs
PYTHONPATH=src python -m gabs_scraper.pipeline --load       # read them into the database
```

---

## How the pieces fit together

```
   Golden Arrow website
   (~1,900 timetable PDFs)
            │
            │  the scraper: harvest → download → parse → load
            ▼
   ┌────────────────────────┐
   │  PostgreSQL in Docker  │   port 5433   ← pgAdmin on 5050 looks in here
   │  routes, timetables,   │
   │  stops, departures     │
   └────────────────────────┘
            │
            │  the API reads it (Java on Spring Boot, or Python on FastAPI)
            ▼
      http://localhost:8000
            │
            │  serves both the JSON API and the built React app
            ▼
        A commuter's browser
```

Searches flow the other way too: each one writes a row into the analytics tables, in the
background, without delaying the answer.

### Why there are two APIs

The backend is being migrated from Python to Java. Both exist, both work, both return
byte-identical responses — `backend/parity_check.py` verifies that automatically. The
Python one is the fallback until the migration is signed off.

Technical detail on the Java service is in [backend/README.md](backend/README.md).

---

## Data model

| Table | What it holds |
|---|---|
| `route` | Origin–destination pair (`AIRPORT IND-BELLVILLE`), letter group |
| `timetable` | One PDF version: number, public-holiday flag, effective dates, URL, sha256, `raw_text`, `parse_status` |
| `stop` | Distinct stop / timing-point names, plus coordinates once geocoded |
| `schedule` | A (direction, day-type) block: direction label, `day_type`, `day_label`, per-page number, `no_service` |
| `schedule_stop` | Ordered stops of a schedule (`stop_sequence`) |
| `trip` | One bus run (a column in the printed grid), with footnote `note_codes` |
| `stop_time` | A single cell: `cell_type` (TIME/VIA/NONE), `departure_time`, `note_code`, `raw_value` |
| `timetable_note` | Footnote codes (`a` → "Mondays, Tuesdays, …") |
| `leg_geometry` | The real road path between two consecutive stops, for map drawing and custom-stop matching |
| `search_analytics` | One row per journey search |
| `search_analytics_option` | One row per route a search returned |

`day_type` is a coarse bucket (`WEEKDAY`/`SATURDAY`/`SUNDAY`/`PUBLIC_HOLIDAY`/`OTHER`);
`day_label` preserves the exact PDF header, e.g. `MONDAYS TO FRIDAYS`. Public-holiday PDFs
occasionally bundle several routes across pages, so each `schedule` keeps its own
`direction_label` and `section_timetable_number`.

---

## Example queries

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

-- One timetable, one direction, as the printed stop × trip grid
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

-- Did anything fail to parse? (raw text is kept so it can be re-parsed)
SELECT pdf_filename, parse_error FROM timetable WHERE parse_status = 'failed';
```

---

## Troubleshooting

### "Connection refused" on port 5433

The database isn't running.

```bash
docker compose up -d && docker compose ps
```

### "docker: command not found" while Docker Desktop is clearly open

Docker's command-line tool isn't on your PATH. It's usually at
`C:\Program Files\Docker\Docker\resources\bin` — or, if Docker Desktop was installed
without administrator rights, at
`%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`.

### "Docker Desktop is unable to start" on Windows

Docker needs WSL 2. Install it from an **administrator** PowerShell, then reboot:

```bash
wsl --install
```

### Port 8000 is already in use

Another API is already running. Stop it, or start yours elsewhere with `--port 8001`
(Python) or `PORT=8001` (Java).

### Opening localhost:8000 shows `{"detail":"Not Found"}`

Either the web app has not been built, or the API started before it was.

```bash
cd web && npm install && npm run build
```

Then restart the API. It checks for `web/dist` only at startup.

### The web app loads but shows no data

The API can't reach the database, or the database is empty. Check in order:

```bash
docker compose ps
curl http://localhost:8000/api/health
```

`/api/health` reports the timetable count — if it's `0`, redo
[Step 2](#step-2--put-the-timetable-data-in).

### Stops are missing from the map

They haven't been geocoded. Run `python -m gabs_scraper.geocode`.

### Custom-stop ("drop a pin") planning finds nothing on some routes

Those routes have no road geometry yet. Run `python -m gabs_scraper.geometry` — it needs
`GOOGLE_MAPS_API_KEY`.

### `GOOGLE_MAPS_API_KEY is not set`

Put it in a `.env` file at the project root:

```
GOOGLE_MAPS_API_KEY=your-key-here
```

Only `geometry` truly requires it. `geocode` falls back to OpenStreetMap for free.
