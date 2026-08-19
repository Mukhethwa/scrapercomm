# GABS Timetable Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrape every GABS timetable PDF into a normalized PostgreSQL database via a re-runnable harvest → download → parse → load pipeline.

**Architecture:** Four idempotent stages. Playwright harvests the Cloudflare-protected HTML into a `manifest.json` of PDF URLs; `requests` downloads the (unprotected) static PDFs; `pdfplumber` parses each PDF's pipe-delimited text layer into dataclasses; a loader upserts them into Postgres keyed on the unique PDF filename. The parser is the risk center and is built test-first against real sample PDFs.

**Tech Stack:** Python 3.14, Playwright (Chromium), requests, pdfplumber, psycopg (fallback psycopg2-binary), PostgreSQL 16 via Docker Compose.

## Global Constraints

- Python 3.14 (installed). Prefer wheels; fall back to `psycopg2-binary` if `psycopg` has no 3.14 wheel.
- PostgreSQL 16 in Docker Compose with a persistent named volume.
- Scope: all letter groups A–W, both regular and Public-Holiday (`_PH_`) PDFs.
- Every stage must be idempotent and independently runnable.
- Per-PDF error isolation: a failure marks `timetable.parse_status='failed'`, keeps `raw_text`, and never aborts the batch.
- PDF filename is the unique natural key of a "timetable version".
- DB DSN read from `.env` (`DATABASE_URL`); never hard-code credentials.

---

### Task 1: Project scaffold, Docker Postgres, schema

**Files:**
- Create: `docker-compose.yml`, `.env.example`, `requirements.txt`, `sql/schema.sql`, `src/gabs_scraper/__init__.py`, `README.md`
- Test: manual — `docker compose up -d` then apply schema

**Interfaces:**
- Produces: a running Postgres on `localhost:5432` (db `gabs`, user `gabs`), and all tables from the design spec.

- [ ] **Step 1:** Write `docker-compose.yml` — `postgres:16`, env `POSTGRES_DB=gabs POSTGRES_USER=gabs POSTGRES_PASSWORD=gabs`, port `5432:5432`, named volume `gabs_pgdata`, and mount `./sql/schema.sql` into `/docker-entrypoint-initdb.d/` so the schema applies on first boot.
- [ ] **Step 2:** Write `sql/schema.sql` — DDL for `route, timetable, stop, schedule, schedule_stop, trip, stop_time, timetable_note` exactly as in the design spec (FKs, UNIQUE constraints, indexes on FKs + `stop.name`, `route.name`, `timetable.timetable_number`). Use `CREATE TABLE IF NOT EXISTS`.
- [ ] **Step 3:** Write `requirements.txt`: `playwright`, `requests`, `pdfplumber`, `psycopg[binary]`, `python-dotenv`, `pytest`.
- [ ] **Step 4:** Write `.env.example` with `DATABASE_URL=postgresql://gabs:gabs@localhost:5432/gabs` and `GABS_BASE_URL=https://www.gabs.co.za/`.
- [ ] **Step 5:** `docker compose up -d`; wait healthy; verify tables exist: `docker exec <c> psql -U gabs -d gabs -c "\dt"`. Expected: 8 tables.
- [ ] **Step 6:** Commit.

---

### Task 2: Config and DB helpers

**Files:**
- Create: `src/gabs_scraper/config.py`, `src/gabs_scraper/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `config.settings` (attrs `database_url: str`, `base_url: str`, `data_dir: Path`, `pdf_dir: Path`, `manifest_path: Path`); `db.connect() -> Connection`; `db.apply_schema(conn)`.

- [ ] **Step 1:** Write failing `tests/test_db.py::test_connect_and_roundtrip` that connects, `SELECT 1`, asserts result `(1,)`.
- [ ] **Step 2:** Run → fails (module missing).
- [ ] **Step 3:** Implement `config.py` (load `.env` via python-dotenv, expose `settings`) and `db.py` (`connect()` returns psycopg connection from `DATABASE_URL`; try `import psycopg`, except fall back to `psycopg2`).
- [ ] **Step 4:** Run → passes (needs Postgres up).
- [ ] **Step 5:** Commit.

---

### Task 3: PDF parser (test-first — the core)

**Files:**
- Create: `src/gabs_scraper/parse.py`
- Test: `tests/test_parse.py`, `tests/samples/*.pdf` (committed real PDFs)

**Interfaces:**
- Produces the dataclasses and entry point that the loader consumes:

```python
@dataclass
class StopTime:
    stop_name: str
    cell_type: str            # 'TIME' | 'VIA' | 'NONE'
    departure_time: str | None   # 'HH:MM' when cell_type == 'TIME'
    note_code: str | None
    raw_value: str

@dataclass
class Trip:
    trip_index: int           # 0-based column position among active trips
    note_codes: list[str]
    times: list[StopTime]     # one per schedule stop, in stop order

@dataclass
class Schedule:
    page_number: int
    direction_index: int
    direction_label: str
    day_type: str             # 'WEEKDAY'|'SATURDAY'|'SUNDAY'|'PUBLIC_HOLIDAY'
    section_effective_date: str | None   # 'YYYY-MM-DD'
    no_service: bool
    stops: list[str]          # ordered stop names (grid rows)
    trips: list[Trip]

@dataclass
class Note:
    code: str
    description: str

@dataclass
class ParsedTimetable:
    timetable_number: str | None   # e.g. '004401' (from PDF; may be None)
    page_count: int
    raw_text: str
    schedules: list[Schedule]
    notes: list[Note]

def parse_pdf(path: str) -> ParsedTimetable: ...
```

**Parsing approach (verified against real PDFs):**
- Each page: line 0 = `direction_label`. Section headers matched by keyword (`MONDAYS TO FRIDAYS`→WEEKDAY, `SATURDAYS`→SATURDAY, `SUNDAYS`→SUNDAY; PH pages→PUBLIC_HOLIDAY). `NO SERVICE` in a header ⇒ `no_service=True`, no grid.
- Data rows begin with `|`. Split on `|`, strip; field 0 = stop name, remaining fields are positionally-aligned trip columns (fixed width per section).
- Active trips = column indices where ≥1 stop cell is not `--`. A cell is `VIA` if it equals `via`; `TIME` if it matches `HH:MM` with optional trailing note letter(s); else `NONE`.
- `ABBREVIATIONS` block ⇒ parse `code - description` into `notes`.
- Effective date parsed from `EFFECTIVE DATE: YYYY/MM/DD`; timetable number from `TIMETABLE NUMBER: NNNN NN` (strip the space).

- [ ] **Step 1:** Copy the 3 already-downloaded samples into `tests/samples/` and download 3 more edge cases (a `_PH_` PDF, a single-direction PDF, one with `SUNDAYS - NO SERVICE`). Commit the sample PDFs.
- [ ] **Step 2:** Write failing tests in `tests/test_parse.py`:
  - `test_parse_returns_two_directions` — sample1 → `len({s.direction_index for s in schedules})==2`.
  - `test_weekday_schedule_has_expected_stops` — sample1 page1 WEEKDAY stops include `NYANGA TERM` and `BELLVILLE`.
  - `test_first_trip_times` — sample1 page1 WEEKDAY: a trip exists where `NYANGA TERM`=`05:40` and `BELLVILLE`=`06:05`.
  - `test_via_cell_type` — a `GUGULETU` cell parses as `cell_type='VIA'`.
  - `test_note_suffix_split` — a `05:30a` cell → `departure_time='05:30'`, `note_code='a'`.
  - `test_no_service_sunday` — sample1 SUNDAY schedule has `no_service=True`.
  - `test_notes_parsed` — notes include `('a', 'Mondays,Tuesdays,Wednesdays,Thursdays')`.
  - `test_ph_flag_via_filename` (in loader task) — deferred.
- [ ] **Step 3:** Run → all fail (parse_pdf missing).
- [ ] **Step 4:** Implement `parse.py` per the approach above.
- [ ] **Step 5:** Run tests → iterate until all pass. Inspect any failing sample's `raw_text` and adjust matchers (do NOT special-case a single PDF; fix the general rule).
- [ ] **Step 6:** Commit.

---

### Task 4: Manifest harvester (Playwright)

**Files:**
- Create: `src/gabs_scraper/harvest.py`
- Test: `tests/test_harvest.py` (unit test the URL/route parser on static HTML fixtures)

**Interfaces:**
- Produces: `harvest.parse_route_name(display: str) -> tuple[str,str,str]` (name, origin, destination); `harvest.entry_from_pdf_path(path: str) -> ManifestEntry`; `harvest.run() -> list[ManifestEntry]` writes `data/manifest.json`.
- `ManifestEntry` fields: `route_name, timetable_number, is_public_holiday, effective_from, effective_to, letter_group, pdf_path, pdf_url, pdf_filename`.

- [ ] **Step 1:** Write failing `tests/test_harvest.py`:
  - `entry_from_pdf_path('Pdf/Apdf/AIRPORT_IND___BELLVILLE_from_20260622_to_99999999_004401.pdf')` → `is_public_holiday=False, effective_from='2026-06-22', effective_to=None, timetable_number='004401', letter_group='A', route_name='AIRPORT IND-BELLVILLE'`.
  - `entry_from_pdf_path('Pdf/Apdf/AIRPORT_IND___BELLVILLE___PH_20260810_004401.pdf')` → `is_public_holiday=True, effective_from='2026-08-10', effective_to=None`.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement path parsing: strip `Pdf/{L}pdf/` and `.pdf`; detect `___PH_` vs `_from_..._to_...`; convert `___`→`-`, `_`→` ` for the route name; `99999999`→None; letter group from folder.
- [ ] **Step 4:** Run → pass.
- [ ] **Step 5:** Implement `run()`: Playwright launches Chromium (headless), `goto` Timetable.aspx, wait for the challenge, iterate each letter tab, for each extract every download button's `onclick` `Pdf/...` path via `page.eval_on_selector_all`. Dedupe by `pdf_filename`. Write `data/manifest.json`.
- [ ] **Step 6:** Commit (harvester code; manifest is data, produced at run time). Note: a bootstrap `manifest.json` is also generated via the interactive browser as a fallback.

---

### Task 5: Downloader

**Files:**
- Create: `src/gabs_scraper/download.py`
- Test: `tests/test_download.py`

**Interfaces:**
- Produces: `download.download_all(entries, pdf_dir) -> list[DownloadResult]` where `DownloadResult` has `pdf_filename, path, sha256, ok, error`. Skips files already present with matching size unless `--force`.

- [ ] **Step 1:** Write failing `tests/test_download.py::test_sha256_and_skip` using a tiny local HTTP server (or monkeypatched requests) returning fixed bytes; assert file written and sha256 correct; second call skips.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement with `requests` + retry/backoff, streaming to `pdf_dir/{pdf_filename}`, sha256 over content.
- [ ] **Step 4:** Run → pass.
- [ ] **Step 5:** Commit.

---

### Task 6: Loader

**Files:**
- Create: `src/gabs_scraper/load.py`
- Test: `tests/test_load.py` (integration — against the Docker Postgres)

**Interfaces:**
- Consumes: `ManifestEntry` (Task 4), `DownloadResult` (Task 5), `ParsedTimetable` (Task 3), `db.connect` (Task 2).
- Produces: `load.load_timetable(conn, entry, dl, parsed) -> int` (returns timetable id); upserts `route`, `timetable` (on `pdf_filename`), and replaces child rows (`schedule`, `schedule_stop`, `trip`, `stop_time`, `timetable_note`) transactionally. `stop` upserted on name.

- [ ] **Step 1:** Write failing `tests/test_load.py::test_load_sample1` — parse sample1, build a synthetic entry/dl, load, then assert: 1 route, 1 timetable, ≥2 schedules, `NYANGA TERM` stop exists, and a known stop_time row (`BELLVILLE` `06:05`) is present.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement upserts (route ON CONFLICT(name); timetable ON CONFLICT(pdf_filename) DO UPDATE; delete-then-insert children within one transaction; stop ON CONFLICT(name)).
- [ ] **Step 4:** Run → pass. Add `test_reload_is_idempotent` (load twice → same counts).
- [ ] **Step 5:** Commit.

---

### Task 7: Pipeline orchestration, full run, verification

**Files:**
- Create: `src/gabs_scraper/pipeline.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: all prior modules.
- Produces: CLI `python -m gabs_scraper.pipeline [--harvest] [--download] [--load] [--all] [--limit N]`.

- [ ] **Step 1:** Implement `pipeline.py`: `--harvest` runs Playwright harvest; `--download` downloads from manifest; `--load` parses+loads each downloaded PDF (per-PDF try/except → `parse_status`); `--all` runs all; `--limit` caps count for smoke tests. Print a summary (counts, failures).
- [ ] **Step 2:** Smoke test: `--all --limit 5` → 5 PDFs loaded, summary clean.
- [ ] **Step 3:** Full run: harvest whole network → download all → load all. Capture summary.
- [ ] **Step 4:** Verify in Postgres: counts per table; spot-check 2–3 timetables against source PDFs; list any `parse_status='failed'` and triage (fix general parser rules if systemic).
- [ ] **Step 5:** Finalize `README.md`: setup (`docker compose up`, `pip install`, `playwright install chromium`), running, re-running, and 3–4 example API-shaped SQL queries (routes list; a route's weekday departures; departures from a stop).
- [ ] **Step 6:** Commit.

---

## Self-Review

- **Spec coverage:** harvest (T4), download (T5), parse (T3), load (T6), schema/Docker (T1), config/db (T2), orchestration+run+verify+docs (T7), error isolation (T7 step1, T6), raw_text fallback (T3 `raw_text` → T6), PH scope (T4 path parsing + T6 flag). All spec sections mapped.
- **Placeholder scan:** none — each task has concrete files, tests, and rules.
- **Type consistency:** `ParsedTimetable`/`Schedule`/`Trip`/`StopTime`/`Note` used identically in T3 and consumed in T6; `ManifestEntry` fields consistent T4↔T6; `DownloadResult` T5↔T6.
