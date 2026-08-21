# Commuttr API — Java / Spring Boot

The Java port of the read-only FastAPI server in `src/gabs_scraper/api.py`, following a
Strangler Fig migration. Every route path, query parameter, JSON payload and HTTP status
code is preserved, so the React client and the Python scraper both keep working unchanged.

- **Java 21** with **Virtual Threads** (`spring.threads.virtual.enabled=true`)
- **Spring Boot 3.5.16**, Spring Web, Spring Data JPA
- **PostgreSQL** — the scraper's existing database, read-only apart from two additive analytics tables

## Run it

```bash
mvn -f backend/pom.xml spring-boot:run
```

It listens on **:8000**, the port FastAPI used, so `web/vite.config.ts` and its `/api`
proxy need no edit at all. Package a jar with `mvn -f backend/pom.xml package`.

Configuration (all overridable by environment variable):

| Variable | Default | Purpose |
| --- | --- | --- |
| `JDBC_DATABASE_URL` | `jdbc:postgresql://localhost:5433/gabs` | JDBC form of `DATABASE_URL` |
| `PGUSER` / `PGPASSWORD` | `gabs` / `gabs` | database credentials |
| `PORT` | `8000` | HTTP port |
| `COMMUTTR_WEB_DIST` | `../web/dist` | built React bundle to serve at `/` |
| `ANALYTICS_ENABLED` | `true` | write search analytics rows |
| `ANALYTICS_SCHEMA_INIT` | `always` | create the analytics tables at startup |
| `LEGACY_FALLBACK_ENABLED` | `false` | proxy unmigrated paths to FastAPI |
| `LEGACY_BASE_URL` | `http://localhost:8001` | where the legacy app listens |

`DATABASE_URL` in `.env` is libpq-style (`postgresql://…`) and JDBC needs its own form, so
the two are configured separately rather than parsed apart at runtime.

## What was preserved, and how

### The scraper and the schema

No scraper code was ported and no existing table was altered. The `@Entity` classes in
`domain/` map onto `sql/schema.sql` exactly — same table names, same column names — and
every one of them is annotated `@Immutable`, so Hibernate cannot write them even by
accident. `spring.jpa.hibernate.ddl-auto=none` keeps Hibernate away from DDL entirely.

The analytical SQL (self-joins across `stop_time`, the `EXISTS` connectivity check, the
`leg_geometry` bounding-box scan) is carried over verbatim as `@Query(nativeQuery = true)`
on Spring Data repositories, so query plans and results are unchanged. Simple lookups use
derived queries and JPQL.

Native-query columns are aliased with **quoted camelCase** — `AS "letterGroup"` — because
PostgreSQL folds unquoted aliases to lowercase and the interface projections would then
fail to bind.

### The React frontend

Untouched. Two things keep it that way:

- the service listens on **:8000**, so the existing Vite dev proxy resolves;
- `config/WebConfig.java` registers a `WebMvcConfigurer` CORS mapping over `/api/**` with
  the same policy FastAPI's `CORSMiddleware` had (`allow_origins=["*"]`,
  `allow_methods=["GET"]`), so `localhost:5173` can also call the API directly.

`WebConfig` also serves `web/dist` at `/` when a build is present, matching FastAPI's
`StaticFiles(..., html=True)` mount — including its rule of serving `index.html` for
directory requests and 404-ing anything else. `/api/**` still wins, because Spring orders
controller mappings ahead of resource handlers.

### The JSON payloads

`spring.jackson.property-naming-strategy=SNAKE_CASE` turns `letterGroup` into
`letter_group`, `boardTime` into `board_time`, and so on across every DTO, so the records
read as idiomatic Java while the wire format stays exactly what Pydantic produced. The
`from` and `to` keys carry an explicit `@JsonProperty`, which the strategy leaves alone.

Details that are easy to lose in a port, and were not:

- `board_minutes` is typed `Number`: an exact stop stays an integer (`365`), an
  interpolated pin keeps its fraction (`407.5`), as in Python.
- `ApiFormat.roundTo`/`roundToLong` round half-to-even over the shortest decimal
  representation, matching Python's `round()` rather than Java's `Math.round`.
- `minutesToClock` uses floor-based div/mod so times past midnight wrap the way
  `_mmss` did.
- Nulls are serialised, not dropped.

### Error contracts

`web/ApiExceptionHandler.java` reproduces FastAPI's envelope:

| Case | Status | Body |
| --- | --- | --- |
| `HTTPException(404, "route not found")` | 404 | `{"detail": "route not found"}` |
| missing required query parameter | 422 | `{"detail": [{"type": "missing", "loc": ["query", "to"], …}]}` |
| unparseable query parameter | 422 | `{"detail": [{"type": "int_parsing", …}]}` |
| unknown path | 404 | `{"detail": "Not Found"}` |

Spring would have answered 400 for the two validation cases, which would have been a
silent contract break.

## Virtual threads

`spring.threads.virtual.enabled=true` puts Tomcat request handling on virtual threads.
This service is a good fit: the planner issues many short blocking JDBC calls per request
(anchors, then a segment and a road-path stitch per group), and under the old platform
thread pool those requests occupied a worker for their whole duration. On virtual threads
each blocking call parks instead of pinning, so concurrency is bounded by the Hikari pool
rather than by Tomcat's thread count.

The same flag makes Spring Boot's `applicationTaskExecutor` virtual-thread backed, which
is what `@Async` analytics writes run on.

Measured end to end — 40 requests at concurrency 10, both services against the same
restored database:

| case | Python | Java | throughput |
| --- | --- | --- | --- |
| `/api/journeys` stop→stop | 223 ms p50 | 31 ms p50 | 41 → 193 req/s |
| `/api/plan` stop→stop | 327 ms p50 | 57 ms p50 | 28 → 162 req/s |
| `/api/plan` pin→pin | 8,621 ms p50 | 3,174 ms p50 | 1.1 → 3.1 req/s |

Treat that as a whole-stack figure, not a virtual-threads benchmark: the JVM, the JDBC
driver and connection pooling all contribute, and the Python side runs its synchronous
endpoints on FastAPI's thread pool. What the numbers do establish is that the concurrency
model holds up on the pin planner, which is by far the heaviest endpoint — it issues one
`leg_geometry` scan plus a query per matched leg, and is the case most likely to have
exhausted a fixed thread pool.

## Event-driven search analytics

```
PlannerService.plan()
   └─ resolveJourneys(...)                  route found
   └─ ApplicationEventPublisher.publishEvent(SearchAnalyticsEvent)
   └─ return the response                   ← does not wait for the insert

SearchAnalyticsListener.onSearch()          @Async @EventListener
   └─ INSERT INTO search_analytics          on a virtual thread, REQUIRES_NEW
   └─ INSERT INTO search_analytics_option   one row per route offered
```

`analytics/SearchAnalyticsEvent.java` is published the moment options are resolved, by
both `/api/plan` and `/api/journeys` (the row records which). `SearchAnalyticsListener`
consumes it with `@Async @EventListener`, enabled by `@EnableAsync` in
`config/AsyncConfig.java`, and writes in its own `REQUIRES_NEW` transaction so it is
never entangled with the read-only request transaction.

Analytics is best-effort by design: the listener catches and logs every failure, and
`AsyncConfig` installs an `AsyncUncaughtExceptionHandler`, so a missing or broken
analytics table can never affect a commuter's journey search. Set `ANALYTICS_ENABLED=false`
to turn it off.

### The schema additions

The analytics inserts need somewhere to go, and the scraper schema has no analytics
tables. `sql/analytics.sql` adds two and nothing else. Both are purely additive
(`CREATE TABLE IF NOT EXISTS`), touch no scraper-owned table, and are applied at startup
via `spring.sql.init`. Apply them by hand and set `ANALYTICS_SCHEMA_INIT=never` if you
would rather manage them out-of-band.

| table | one row per | answers |
| --- | --- | --- |
| `search_analytics` | search | who searched what, from where to where, how many results, how long it took |
| `search_analytics_option` | journey option returned | **which routes** were surfaced, and how many departures each offered |

The second table exists because the first cannot answer route demand: it records
`option_count`, not which options. Without it you can say "Bellville to Nyanga was
searched 400 times" but never "route 004401 is the most sought-after service". That is
not backfillable, so it records from the first search onward.

### Reading the data

pgAdmin is at <http://localhost:5050> once `docker compose up -d` is running (server
*GABS (local)*, password `gabs`), or query directly:

```bash
docker exec -it gabs_pg psql -U gabs -d gabs
```

**Which routes are commuters searching for**

```sql
SELECT o.route_label, o.timetable_number, o.day_type,
       count(DISTINCT o.search_id) AS searches,
       sum(o.departure_count)      AS departures_offered
FROM search_analytics_option o
GROUP BY 1, 2, 3
ORDER BY searches DESC;
```

**Most-searched origin/destination pairs, with stop names resolved**

```sql
SELECT COALESCE(so.name, 'pin') AS origin,
       COALESCE(sd.name, 'pin') AS destination,
       count(*) AS searches, round(avg(sa.option_count), 1) AS avg_options
FROM search_analytics sa
LEFT JOIN stop so ON so.id = sa.from_stop_id
LEFT JOIN stop sd ON sd.id = sa.to_stop_id
GROUP BY 1, 2
ORDER BY searches DESC;
```

**Unmet demand — journeys people want that no bus makes.** Probably the most valuable
query here: every row is a commuter who searched and got nothing.

```sql
SELECT COALESCE(so.name, 'pin ' || round(sa.from_lat::numeric, 3) || ',' ||
                                   round(sa.from_lon::numeric, 3)) AS origin,
       COALESCE(sd.name, 'pin ' || round(sa.to_lat::numeric, 3) || ',' ||
                                   round(sa.to_lon::numeric, 3))   AS destination,
       count(*) AS failed_searches
FROM search_analytics sa
LEFT JOIN stop so ON so.id = sa.from_stop_id
LEFT JOIN stop sd ON sd.id = sa.to_stop_id
WHERE sa.option_count = 0
GROUP BY 1, 2
ORDER BY failed_searches DESC;
```

**Official stops versus dropped pins, and what each costs**

```sql
SELECT endpoint, from_kind, count(*) AS searches,
       round(avg(option_count), 1) AS avg_options,
       round(avg(duration_ms))     AS avg_ms
FROM search_analytics
GROUP BY 1, 2 ORDER BY 1, 2;
```

**What is deliberately not recorded:** no user or session identifier, so these are counts
of searches rather than of people; and no record of which option a commuter actually
chose, only what was offered. Both would need the React client to send something, which
this migration did not touch.

## The Strangler Fig facade

`config/LegacyFallbackFilter.java` lets this service front the legacy app: any `/api/**`
request no Spring controller claims is forwarded to FastAPI and its response returned
untouched. That allows an endpoint-at-a-time cutover behind a single origin, and a
per-endpoint rollback if one misbehaves.

It is **off by default**, because every FastAPI endpoint has been ported. To use it, move
the legacy app to another port and start this one with:

```bash
LEGACY_FALLBACK_ENABLED=true LEGACY_BASE_URL=http://localhost:8001 mvn -f backend/pom.xml spring-boot:run
```

## Verifying the port

```bash
mvn -f backend/pom.xml test
```

- `ApiContractTest` — a `@WebMvcTest` asserting the wire format: snake_case keys, the
  `from`/`to` keys, the `{"detail": …}` error envelope, 404/400/422 statuses, and the
  integer-vs-float shape of `board_minutes`.
- `ApiFormatAndGeoTest` — the time, date and rounding helpers, plus haversine and
  point-to-polyline location.
- `ContextLoadsTest` — boots the whole application offline, which catches a mistyped
  `@Column`, unparseable JPQL, or a derived finder naming a property that does not exist.

These do not touch a database, so they cannot exercise the native SQL. That is what
`parity_check.py` is for — run both services against the same database and diff them:

```bash
python backend/parity_check.py --legacy http://localhost:8001 --java http://localhost:8000
```

It discovers real route, timetable and stop ids from live data, then deep-diffs status
codes and JSON bodies across every endpoint, including the error cases, and exits non-zero
on any difference so it can gate the cutover.

**Result against the refreshed database** (793 routes, 1,878 timetables, 527 stops, all
parsed with zero failures): **45/45 endpoints identical**, no reconciliation required.
That covers every native query, every interface projection, the grouping and sorting
rules, and the 404/400/422 error paths.

The async analytics were confirmed in the same run: `search_analytics` was created at
startup and collected 15 rows (5 from `/api/journeys`, 10 from `/api/plan`), with stop and
pin endpoints recorded correctly. Pin plans took 1.9–2.5 s to resolve and still returned
without waiting on the insert.

Bring the database up the way README.md documents — `docker compose up -d`, then restore
`data/gabs_dump.sql.gz` — and run both services against it.

## Endpoint map

| Endpoint | FastAPI | Java |
| --- | --- | --- |
| `GET /api/health` | `api.health` | `CatalogController` → `CatalogService` |
| `GET /api/routes` | `api.list_routes` | `CatalogController` |
| `GET /api/routes/{id}` | `api.get_route` | `CatalogController` |
| `GET /api/timetables/{id}` | `api.get_timetable` | `CatalogController` |
| `GET /api/areas` | `api.areas` | `CatalogController` |
| `GET /api/stops` | `api.list_stops` | `StopController` → `StopService` |
| `GET /api/stops/{id}/reachable` | `api.reachable` | `StopController` |
| `GET /api/reachable_point` | `api.reachable_point` | `StopController` → `PlannerService` |
| `GET /api/journeys` | `api.journeys` | `PlannerController` → `JourneyService` |
| `GET /api/plan` | `api.plan` | `PlannerController` → `PlannerService` |
| `GET /api/locate` | `api.locate` | `PlannerController` |
| `GET /api/trip_stops` | `api.trip_stops` | `PlannerController` |
| `GET /api/nearby_origins` | `api.nearby_origins` | `PlannerController` |
| `GET /api/geocode` | `api.geocode_place` | `PlannerController` → `GeocodeService` |
| `GET /api/connections` | *(new — Java only)* | `PlannerController` → `ConnectionService` |

`planner.py` maps onto `service/PlannerService.java`, and `geo.py` onto
`service/GeoUtils.java`.

## Connections: getting there when no single bus does

`GET /api/connections?from=&to=` answers "no direct bus — so what do I catch instead".
Named stops only, and the client consults it after `/api/plan` returns nothing.

Two legs are searched first and three only if two finds nothing, since a commuter would
rather change once than twice. Within a leg count, results are ordered by total journey
time, then by waiting time.

Three things make it work:

- **Narrow to interchanges first.** Stops reachable from the origin that also reach the
  destination — a set of single figures to low hundreds, found in milliseconds. Bounding
  the leg searches by it took one query from 10.7s to 80ms.
- **Drive the middle leg from that set, not a tuple `IN`.** `(a, b) IN (SELECT x, y …)`
  stops PostgreSQL using the `stop_id` index and it scans the whole self-join instead:
  the same 31,578 rows took 23.9s that way versus 1.1s as a join.
- **`DISTINCT ON` per leg.** Without it a connection repeats once per timetable version,
  exactly as the direct planner would without its grouping.

Measured: two legs 0.1–0.2s, three legs 1.9–4.2s, unreachable 1.3s.

### Which times have to exist

Only 28% of timetable cells carry a real time; 19% are "via", meaning the bus passes but
no time is published. So a leg's departure and its arrival **at an interchange** must be
real times — you cannot plan a change you cannot time — but arrival at the final
destination may be "via", because for many stops that is all Golden Arrow publishes.
Requiring a time there finds nothing across a large part of the network: BELLVILLE to
STRANDFONTEIN, for instance, has zero fully-timed legs.

### Every leg moves forward in time

A leg's arrival must be later than its departure. The between-leg checks alone were
satisfied by a bus that "arrived" hours before it left — one result had leg 2 departing
Cape Town at 08:00 and reaching Town Centre at 06:10 — and because results sort by total
journey time those impossible connections went straight to the top. The cost is that a
leg genuinely crossing midnight is excluded, which is the safer trade.

### Java only

This endpoint has no FastAPI counterpart. The Python service is being retired, and
duplicating a non-trivial engine into it would be waste. `parity_check.py` still passes
45/45, because it compares the endpoints both services share and none of those changed —
but the legacy service cannot answer connection queries.

## Determinism: why both services sort the same way

`planner.resolve_journeys` originally iterated `set(board) & set(alight)`. Python does not
specify a set's iteration order, and that order decided real output: which `schedule_id`
and `trip_index` a departure was attributed to, and — because departures are sorted only
by board time, with a stable sort — the order of any departures leaving at the same minute.

Against the refreshed database this surfaced concretely: for one pin journey the two
services returned the same three departures ordered `[18:30a, 18:00, 18:45b]` and
`[18:00, 18:45b, 18:30a]`. Same journeys, arbitrary order.

Both implementations now iterate in `(schedule, trip)` order, so results are reproducible
run to run and identical across the two services. **Parity is 45/45 with no reconciliation
required.**

`parity_check.py` still carries a guard for this class of bug: if the two services ever
report a different `departures[].schedule_id`, it re-resolves both through
`/api/trip_stops` — the only thing the React client does with that field — and fails the
run unless both produce the same stop-by-stop breakdown. That guard is what caught the
ordering defect above, by reporting breakdowns that did not match.

One residual fragility worth knowing: the departure sort key is still only `board_minutes`,
so equal-board-time departures rely on both languages' stable sorts seeing the same
insertion order. That holds now that iteration is aligned, but a *total* sort key (adding
arrival time) would remove the coupling entirely.
