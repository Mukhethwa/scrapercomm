# Commuttr — Java migration, data-integrity repair, and planner fix

**Date:** 2026-08-20
**Commits:** `3aa5e15..ea5b8e1` on `main` (six commits)

Three pieces of work, in the order they were requested: port the FastAPI backend to Java
/ Spring Boot; repair a timetable dataset that had silently gone 80% stale; and fix a
planner defect that drew journeys the bus never makes.

---

## 1. Backend migration — Python (FastAPI) to Java (Spring Boot)

Commit `67c4323`. New module in `backend/`, ~3,900 lines across 51 source files.

### Stack

- **Java 21** with **virtual threads** (`spring.threads.virtual.enabled=true`)
- **Spring Boot 3.5.16** (latest stable 3.x; 4.0 exists but 3.x was specified)
- Spring Web, Spring Data JPA, PostgreSQL

### What was preserved

All 14 endpoints, with identical route paths, query parameter names, JSON payloads and
HTTP status codes. `planner.py` and `geo.py` were ported wholesale into
`PlannerService.java` and `GeoUtils.java`.

**Scraper and schema untouched.** The nine `@Entity` classes map `sql/schema.sql` exactly
and are all `@Immutable`; `ddl-auto=none`. The analytical SQL — the `stop_time`
self-joins, the `EXISTS` connectivity check, the `leg_geometry` bounding-box scan — is
carried over verbatim as `@Query(nativeQuery = true)`.

**React untouched.** The service listens on **:8000**, the port FastAPI used, so the
existing Vite dev proxy resolves unchanged. `WebConfig` adds a `WebMvcConfigurer` CORS
mapping matching FastAPI's `CORSMiddleware` policy, and serves `web/dist` at `/` the way
`StaticFiles(..., html=True)` did.

### Details that are easy to lose in a port

- Native-query columns are aliased with **quoted camelCase** (`AS "letterGroup"`);
  PostgreSQL folds unquoted aliases to lowercase and the interface projections would
  silently fail to bind.
- `spring.jackson.property-naming-strategy=SNAKE_CASE` reproduces the Pydantic wire
  format; `from`/`to` carry explicit `@JsonProperty`.
- `board_minutes` is typed `Number`, so an exact stop stays an integer (`365`) while an
  interpolated pin keeps its fraction (`407.5`). A plain `Double` would have emitted
  `365.0`.
- `ApiFormat.roundTo`/`roundToLong` round half-to-even over the shortest decimal
  representation, matching Python's `round()` rather than `Math.round`.
- `minutesToClock` uses floor-based div/mod so times past midnight wrap as `_mmss` did.

### Two silent contract breaks avoided

Spring answers **400** for a missing or unparseable query parameter where FastAPI answers
**422** with a `detail` array. `ApiExceptionHandler` restores that, along with the
`{"detail": ...}` envelope for 404s and the 405 reason phrase.

### Event-driven analytics

`PlannerService.plan()` publishes a `SearchAnalyticsEvent` the moment options resolve and
returns without waiting. `SearchAnalyticsListener` performs the INSERT under
`@Async @EventListener` in a `REQUIRES_NEW` transaction, on a virtual thread. Failures are
caught, logged and swallowed, so analytics can never affect a commuter's search.

**One additive schema change:** `search_analytics` did not exist. `sql/analytics.sql`
creates it (`CREATE TABLE IF NOT EXISTS`); no scraper-owned table was altered.

### Strangler Fig facade

`LegacyFallbackFilter` forwards any `/api/**` path no Spring controller claims to the
legacy FastAPI process, allowing an endpoint-at-a-time cutover and per-endpoint rollback.
Off by default, since every endpoint is ported.

### Measured performance

40 requests at concurrency 10, both services against the same database:

| case | Python | Java | throughput |
| --- | --- | --- | --- |
| `/api/journeys` stop→stop | 223 ms p50 | 31 ms p50 | 41 → 193 req/s |
| `/api/plan` stop→stop | 327 ms p50 | 57 ms p50 | 28 → 162 req/s |
| `/api/plan` pin→pin | 8,621 ms p50 | 3,174 ms p50 | 1.1 → 3.1 req/s |

Whole-stack figures, not a virtual-threads benchmark — the JVM, JDBC driver and pooling
all contribute.

---

## 2. Data integrity — the dataset was 80% stale

Commits `b183be2` (code), `e9f6857` (data), `ea5b8e1` (PDF cache).

### Reported vs. actual

The report was "1,878 on the site, we have 1,868 — 10 missing". The count was right; the
shortfall was the least of it. Audited against the live site:

| | |
| --- | --- |
| Published by the site | **1,878** |
| Stored locally | 1,868 |
| **Still current** | **366** |
| Superseded (served but withdrawn) | **1,502** |
| Missing entirely | **1,512** |

No routes had been withdrawn — the site had grown from **544 routes to 793**. So:

- **249 routes were absent from the app entirely** (~a third of the network).
- **468 of the 544 existing routes had re-issued timetables**, meaning users were shown
  *outdated departure times* — worse for a commuter app than a missing route.

### Root causes

1. **`harvest.LETTERS` skipped G, I, J, Q, U, X, Y, Z** on the assumption they had no
   routes. U now carries six UWC timetables. Verified live: the real `fetch_all_paths()`
   returned **1,872**, not 1,878. Those six were unreachable no matter how often it ran.
2. **`load` was upsert-only.** Nothing reconciled against the current manifest, so the
   database could only grow. A full re-run would have produced 3,380 timetables, 1,502 of
   them dead — *worse* than doing nothing.
3. **`harvest()` swallowed `ValueError` with a bare `continue`.** Any unexpected filename
   vanished with no log or count. Zero cases today, but a silent time bomb.

**Ruled out:** the reuse of a stale `__VIEWSTATE` across letter postbacks. Per-letter
counts matched a properly chained postback exactly.

### Fixes

- `LETTERS` now iterates A–Z. Verified: **1,878** including the six `Updf` files.
- Rejected filenames are collected and reported loudly.
- `load.prune_superseded()` deletes timetables absent from the fresh manifest plus any
  route left with none, cascading to schedules, trips, stop_times and notes. Stops are
  kept deliberately: shared across routes, carry geocoding, referenced by `leg_geometry`.
- `download.prune_pdfs()` reconciles the download cache the same way.

**Two guards, because these delete data:** both refuse to run against an empty manifest
(that is a harvest failure, not GABS withdrawing everything), and both are skipped when
`--limit` is used, since a sample would delete nearly everything. `--no-prune` opts out.

### Result of the full reload

| | before | after |
| --- | --- | --- |
| routes | 544 | **793** |
| timetables | 1,868 | **1,878** (matches the site) |
| stops | 280 | 527 |
| parse failures | — | **0** |
| orphaned routes / schedules | — | **0** |
| superseded pruned | — | 1,518 |

Then geocoding and road geometry, which the pipeline does **not** run:

- `geocode` — 247 stops geocoded, 0 not found. Stops without coordinates: 247 → **0**.
- `geometry` — 960 legs fetched, 0 empty. `leg_geometry` 1,041 → 2,001. Legs missing
  geometry: 960 → **0**.
- `prune_pdfs` — 1,518 stranded files removed (17.2 MB). Disk and manifest both 1,878,
  zero drift either way.

The prune removed 1,518 rather than the 1,502 predicted: GABS republished ~16 timetables
during the few hours the refresh took.

---

## 3. Planner — the bus appeared to detour to collect you

Commit `26295b1`, applied identically to `planner.py` and `PlannerService.java`.

### The defect

`_road_path` stitched geometry across the *enclosing* timing points —
`int(from_pos)` to `int(to_pos) + 1` — because a leg's geometry only exists between two of
them. A pin sits at a fractional position between that pair, so the drawn line began at a
stop before boarding and ran past the destination, with the pin marker off to one side.

Measured on a CBD → Bellville pin journey:

| | before | after |
| --- | --- | --- |
| line starts, distance from pin | **23,058 m** (the Khayelitsha end of the route) | **175 m** |
| stop-to-stop, line ends from alighting stop | one leg past it — 23,048 m further on | **65 m** |

### The fix

`geo.slice_path` (mirrored as `GeoUtils.slicePath`) cuts a leg at a fraction of its
length, interpolating the cut point onto the line so the path starts and ends exactly
where the passenger does, not at the nearest vertex.

`segment_stops` was deliberately **not** changed: `PlanMap.tsx` skips its first and last
entries when drawing intermediate dots, so the enclosing range is correct there. No React
change was needed.

The pin was already guaranteed to lie *between* origin and destination in sequence terms —
`_pin_anchors` only matches consecutive timing points, and position ordering is enforced.
The defect was purely in what got drawn.

### A second bug the refreshed data exposed

After the reload, parity dropped to 42/45. The two services returned the *same three
departures* in different orders — `[18:30a, 18:00, 18:45b]` versus
`[18:00, 18:45b, 18:30a]` — plus mismatched `trip_index`.

Cause: `resolve_journeys` iterated `set(board) & set(alight)`. Python does not define a
set's iteration order, and that order decided real output — which `schedule_id` and
`trip_index` a departure was attributed to, and, because departures sort only on board
time with a stable sort, the order of departures leaving at the same minute.

Both implementations now iterate in `(schedule, trip)` order. Results are reproducible run
to run, and the `schedule_id` divergence previously documented as unavoidable disappeared
entirely.

---

## Verification

| check | result |
| --- | --- |
| API parity (Python vs Java, same DB) | **45/45 endpoints identical**, no reconciliation |
| Java tests | 22 pass |
| Python tests | 27 pass |
| Pin planning on a route that did not exist before | 2 options, 4 departures, line starts **0 m** from the pin |
| Async analytics | table auto-created; rows written for both `/api/plan` and `/api/journeys`, stop and pin endpoints |

`backend/parity_check.py` discovers real ids from live data and deep-diffs status codes
and JSON bodies across every endpoint including error cases, exiting non-zero on any
difference. It carries a guard that re-resolves any differing `departures[].schedule_id`
through `/api/trip_stops` and fails unless both produce the same breakdown — that guard is
what caught the ordering defect above.

---

## Environment notes

The machine is Entra ID (Azure AD) joined; the account was a standard user until admin
rights were granted on 2026-08-20. Consequences worth remembering:

- **Docker Desktop 4.87 is installed per-user** at `%LOCALAPPDATA%\Programs\DockerDesktop`,
  not `C:\Program Files\Docker`, because it fell back when it could not elevate. Its CLI
  is **not on PATH**.
- Its engine could not start until **WSL** was installed (`wsl --install`, WSL 2.7.12 +
  Ubuntu). Hardware virtualisation was already available.
- A portable PostgreSQL was used briefly as a stopgap and removed at the user's request.
  **Docker is the supported path**; `docker compose up -d` then restore
  `data/gabs_dump.sql.gz`.
- Python dependencies live in the project `.venv`.
- Geocoding and road geometry used a Google Maps API key supplied at runtime via `.env`;
  the file was deleted afterwards.

---

## Open items

1. **Schedule the pipeline.** GABS republished 16 timetables during this session alone,
   and many current files expire within days. The pipeline now reconciles rather than
   accumulates — database, routes and PDF cache — so it is safe to run repeatedly, but
   nothing runs it automatically.
2. **`geocode` and `geometry` are not part of the pipeline.** New routes need both before
   pin planning works for them. `geometry` requires a Google Directions key and has no
   fallback; `geocode` falls back to Nominatim without one.
3. **Repo size.** Deleting PDFs from the working tree does not shrink the repository — the
   blobs remain in history. Untracking `data/pdfs` and relying on `pipeline --download`
   would be the fix if clone size becomes a problem.
4. **Residual ordering fragility.** The departure sort key is still only `board_minutes`,
   so equal-board-time departures rely on both languages' stable sorts seeing the same
   insertion order. That holds now that iteration is aligned; a total sort key (adding
   arrival time) would remove the coupling entirely.
5. **The 700 m pin threshold is unchanged.** A pin up to 700 m from the road still
   matches. Tightening it, or preferring the nearest matching leg over the earliest one
   (relevant where a route doubles back), was offered and not taken.

---

## Commits

```
ea5b8e1  fix(scraper): reconcile the PDF cache with what GABS still publishes
af0d626  docs: cover the Java backend, and why a full load also deletes
e9f6857  chore(data): refresh timetables from gabs.co.za (1878 published)
26295b1  fix(planner): draw only the road the passenger rides, and order results deterministically
b183be2  fix(scraper): harvest every letter and remove superseded timetables
67c4323  feat(backend): add Java 21 / Spring Boot 3 API alongside the FastAPI service
```
