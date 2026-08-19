# GABS Timetable Scraper — Design

**Date:** 2026-07-27
**Status:** Approved (design)
**Source:** https://www.gabs.co.za/Timetable.aspx

## Goal

Scrape every bus timetable PDF published by Golden Arrow Bus Services (GABS), parse
them into fully-structured records, and load them into a local PostgreSQL database.
The database schema is designed to back a read API that the user will build separately.

**In scope:** a re-runnable pipeline (harvest → download → parse → load) + the populated
Postgres database + schema + docs.
**Out of scope:** the HTTP API itself (the user's next step). The schema is designed to
make that API easy.

## Findings that shaped the design

- `Timetable.aspx` is an ASP.NET WebForms page behind **Cloudflare** (a plain HTTP GET
  returns 403). It has an **A–Z letter filter**; each letter loads a set of route cards
  via postback. Letters present: A B C D E F H K L M N O P R S T V W (no routes for
  G I J Q U X Y Z).
- Each card = a **route** (origin–destination, e.g. `AIRPORT IND-BELLVILLE`) + a
  **Timetable Number** (e.g. `004401`) + a download button whose `onclick` opens a
  **static PDF**.
- PDF path pattern (relative to site root):
  - Regular: `Pdf/{Letter}pdf/{ROUTE}_from_{YYYYMMDD}_to_{YYYYMMDD|99999999}_{TT#}.pdf`
  - Public Holiday: `Pdf/{Letter}pdf/{ROUTE}___PH_{YYYYMMDD}_{TT#}.pdf`
  - In the filename, spaces → `_` and the route hyphen `-` → `___`.
- **The static PDFs are NOT Cloudflare-blocked** — plain `curl`/`requests` fetch them
  (HTTP 200, `application/pdf`). Only the HTML page needs a real browser.

### PDF internal structure

- One PDF may contain **both directions** (outbound = page 1, return = page 2).
- Each direction page has a **title** (`NYANGA - AIRPORT IND - BELLVILLE`) and
  **day-type sections**: `MONDAYS TO FRIDAYS`, `SATURDAYS`, `SUNDAYS` (often
  `SUNDAYS - NO SERVICE`). Public-holiday schedules are separate `_PH_` PDFs.
- Each section header carries an `EFFECTIVE DATE:` and `TIMETABLE NUMBER:`.
- The section body is a **grid**: rows = stops / timing-points, columns = individual
  bus trips. Cells contain a departure time (`05:30`), optionally a note suffix
  (`05:30a`), or `via` (bus passes but no scheduled time), or `--` (not on that trip).
- The text layer is **pipe-delimited** (`| STOP NAME | 05:30a | -- | via | ... |`),
  which makes row/column extraction tractable.
- A footnote block maps note codes to meanings (`a - Mondays,Tuesdays,Wednesdays,Thursdays`).

## Architecture

Four stages, each independently runnable and **idempotent**:

1. **Harvest** (`harvest.py`) — headless **Playwright** loads `Timetable.aspx`, iterates
   every letter filter, and extracts each download button's PDF path + route name +
   timetable number → `data/manifest.json`. (The first manifest is also bootstrapped via
   the interactive browser during development, so work is never blocked on Playwright.)
2. **Download** (`download.py`) — reads the manifest, fetches each PDF with `requests`
   (retry + backoff) into `data/pdfs/`, computes a SHA-256, skips already-downloaded
   unchanged files.
3. **Parse** (`parse.py`) — `pdfplumber` text extraction → structured Python dataclasses
   (route, timetable, schedules, stops, trips, stop_times, notes). Built **test-first**
   against real sample PDFs. Pure function of a PDF file; no DB or network.
4. **Load** (`load.py`) — upserts parsed structures into Postgres. Keyed on the unique
   PDF filename (a "timetable version"); a re-run replaces that version's children
   atomically inside a transaction.

`pipeline.py` orchestrates the stages (each can be run alone via CLI flags).

### Error handling

- Per-PDF isolation. A parse failure sets `timetable.parse_status='failed'`, stores the
  `raw_text`, and the run continues. A final summary lists failures.
- Download failures retry with exponential backoff; persistent failures are logged and
  reported, not fatal.
- Keeping `raw_text` + the original PDF means we can re-parse without re-downloading and
  never silently lose data.

## Data model (PostgreSQL)

```
route(id, name UNIQUE, origin, destination, letter_group, created_at)

timetable(
  id, route_id -> route,
  timetable_number,            -- e.g. '004401'
  is_public_holiday bool,
  effective_from date, effective_to date NULL,   -- 99999999 -> NULL (open-ended)
  pdf_url text, pdf_filename text UNIQUE, pdf_sha256 text,
  page_count int, raw_text text,
  parse_status text,           -- pending | parsed | failed
  scraped_at, parsed_at
)

stop(id, name UNIQUE)          -- global dimension of stop / timing-point names

schedule(
  id, timetable_id -> timetable,
  page_number int, direction_index int,
  direction_label text,        -- 'NYANGA - AIRPORT IND - BELLVILLE'
  day_type text,               -- WEEKDAY | SATURDAY | SUNDAY | PUBLIC_HOLIDAY
  section_effective_date date NULL,
  no_service bool
)

schedule_stop(id, schedule_id -> schedule, stop_id -> stop, stop_sequence int)
  UNIQUE(schedule_id, stop_sequence)

trip(id, schedule_id -> schedule, trip_index int, note_codes text[] NULL)
  UNIQUE(schedule_id, trip_index)

stop_time(
  id, trip_id -> trip, schedule_stop_id -> schedule_stop,
  cell_type text,              -- TIME | VIA | NONE
  departure_time time NULL,    -- set when cell_type = TIME
  note_code text NULL,
  raw_value text
)
  UNIQUE(trip_id, schedule_stop_id)

timetable_note(id, timetable_id -> timetable, code text, description text)
  UNIQUE(timetable_id, code)
```

Indexes on the foreign keys and on `stop.name`, `route.name`, `timetable.timetable_number`
to support the future API's common lookups (by route, by stop, by day-type).

## Tech stack

- **Python 3.14** (installed).
- **Playwright** (headless Chromium) — harvest past Cloudflare.
- **requests** — PDF download.
- **pdfplumber** — PDF text extraction (verified working on real PDFs).
- **psycopg** (v3) for Postgres — with a fallback to `psycopg2-binary` if no 3.14 wheel.
- **PostgreSQL 16** via **Docker Compose** with a persistent named volume.

## Project layout

```
scraper/
  docker-compose.yml          # postgres:16 + persistent volume
  .env.example                # DB DSN, paths
  requirements.txt
  README.md
  sql/schema.sql              # DDL
  src/gabs_scraper/
    __init__.py  config.py  db.py
    harvest.py  download.py  parse.py  load.py  pipeline.py
  data/
    manifest.json  pdfs/
  tests/
    test_parse.py             # against committed sample PDFs
    samples/*.pdf
```

## Risks & mitigations

- **Python 3.14 wheels** for `psycopg`/Playwright may lag → fall back to
  `psycopg2-binary`; Playwright ships its own browser download.
- **PDF parse variance** (multi-page, NO SERVICE, split timetable numbers like
  `0044 01`, unusual stop rows) → test-first parser over several real samples;
  `raw_text` retained; failures isolated and reported.
- **Cloudflare on harvest** → Playwright drives a real browser engine; if it is ever
  challenged, the manifest can be regenerated from the interactive browser as a fallback.

## Success criteria

- `docker compose up` brings up Postgres; `schema.sql` applies cleanly.
- Pipeline runs end-to-end over the whole network (all letters, regular + PH).
- Parser tests pass against the real sample PDFs.
- Row counts are sane (hundreds of routes/timetables, thousands of stop_times); spot
  checks of specific timetables match the source PDFs.
- README documents setup, running, re-running, and example API-shaped SQL queries.
