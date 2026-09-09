"""Read-only FastAPI server over the GABS timetable database.

Endpoints (all JSON):
  GET /api/health
  GET /api/routes?q=&letter=            -> routes with timetable counts
  GET /api/routes/{route_id}            -> route + its timetables
  GET /api/timetables/{timetable_id}    -> full render payload (schedules,
                                           stops w/ coords, trips, stop_times, notes)
  GET /api/connections?from=&to=        -> journeys needing a change of bus

If a built web UI exists at web/dist it is served at /.

Run:  PYTHONPATH=src python -m uvicorn gabs_scraper.api:app --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db

app = FastAPI(title="Commuttr API", version="0.1.0")

# Allow the Vite dev server (localhost:5173) to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# One stop row, as both services return it.
#
# Stops are unique per operator rather than globally now, so RETREAT the station and
# RETREAT the bus stop are two rows with one name. A row that does not say which is which
# leaves a caller with two identical entries and no way to choose. LEFT JOIN because a
# stop with no operator is a bug worth seeing as a null rather than a missing row.
STOP_SELECT = """
    SELECT s.id, s.name, s.lat, s.lon,
           o.code AS operator_code, o.kind AS operator_kind
    FROM stop s LEFT JOIN operator o ON o.id = s.operator_id
"""


def _rows(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _fmt_time(v):
    return v.strftime("%H:%M") if v is not None else None


@app.get("/api/health")
def health():
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM timetable")
        return {"status": "ok", "timetables": cur.fetchone()[0]}
    finally:
        conn.close()


@app.get("/api/routes")
def list_routes(q: str | None = None, letter: str | None = None):
    conn = db.connect()
    try:
        cur = conn.cursor()
        where, params = [], []
        if q:
            where.append("r.name ILIKE %s")
            params.append(f"%{q}%")
        if letter:
            where.append("r.letter_group = %s")
            params.append(letter.upper())
        sql = """
            SELECT r.id, r.name, r.origin, r.destination, r.letter_group,
                   count(t.id) AS timetable_count
            FROM route r
            LEFT JOIN timetable t ON t.route_id = r.id
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY r.id ORDER BY r.name"
        cur.execute(sql, params)
        return {"routes": _rows(cur)}
    finally:
        conn.close()


@app.get("/api/routes/{route_id}")
def get_route(route_id: int):
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, origin, destination, letter_group FROM route WHERE id=%s",
            (route_id,),
        )
        rows = _rows(cur)
        if not rows:
            raise HTTPException(404, "route not found")
        route = rows[0]
        cur.execute(
            """
            SELECT id, timetable_number, is_public_holiday,
                   effective_from, effective_to, pdf_filename, pdf_url,
                   page_count, parse_status
            FROM timetable WHERE route_id=%s
            ORDER BY is_public_holiday, timetable_number, effective_from
            """,
            (route_id,),
        )
        tts = _rows(cur)
        for t in tts:
            t["effective_from"] = t["effective_from"].isoformat() if t["effective_from"] else None
            t["effective_to"] = t["effective_to"].isoformat() if t["effective_to"] else None
        return {"route": route, "timetables": tts}
    finally:
        conn.close()


@app.get("/api/timetables/{timetable_id}")
def get_timetable(timetable_id: int):
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT t.id, t.timetable_number, t.is_public_holiday, t.effective_from,
                   t.effective_to, t.pdf_filename, t.pdf_url, t.page_count,
                   r.id AS route_id, r.name AS route_name
            FROM timetable t JOIN route r ON r.id = t.route_id
            WHERE t.id=%s
            """,
            (timetable_id,),
        )
        base = _rows(cur)
        if not base:
            raise HTTPException(404, "timetable not found")
        tt = base[0]
        tt["effective_from"] = tt["effective_from"].isoformat() if tt["effective_from"] else None
        tt["effective_to"] = tt["effective_to"].isoformat() if tt["effective_to"] else None

        cur.execute(
            "SELECT code, description FROM timetable_note WHERE timetable_id=%s ORDER BY code",
            (timetable_id,),
        )
        notes = _rows(cur)

        cur.execute(
            """
            SELECT id, page_number, direction_index, direction_label, day_type,
                   day_label, section_timetable_number, no_service
            FROM schedule WHERE timetable_id=%s
            ORDER BY page_number, direction_index,
                     CASE day_type WHEN 'WEEKDAY' THEN 0 WHEN 'SATURDAY' THEN 1
                                   WHEN 'SUNDAY' THEN 2 WHEN 'PUBLIC_HOLIDAY' THEN 3
                                   ELSE 4 END
            """,
            (timetable_id,),
        )
        schedules = _rows(cur)

        for sc in schedules:
            sid = sc["id"]
            cur.execute(
                """
                SELECT ss.stop_sequence, s.name, s.lat, s.lon
                FROM schedule_stop ss JOIN stop s ON s.id = ss.stop_id
                WHERE ss.schedule_id=%s ORDER BY ss.stop_sequence
                """,
                (sid,),
            )
            sc["stops"] = _rows(cur)

            cur.execute(
                "SELECT trip_index, note_codes FROM trip WHERE schedule_id=%s ORDER BY trip_index",
                (sid,),
            )
            trips = {t["trip_index"]: {**t, "cells": []} for t in _rows(cur)}

            cur.execute(
                """
                SELECT t.trip_index, ss.stop_sequence, st.cell_type,
                       st.departure_time, st.note_code, st.raw_value
                FROM stop_time st
                JOIN trip t          ON t.id = st.trip_id
                JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
                WHERE t.schedule_id=%s
                ORDER BY t.trip_index, ss.stop_sequence
                """,
                (sid,),
            )
            for cell in _rows(cur):
                ti = cell.pop("trip_index")
                cell["departure_time"] = _fmt_time(cell["departure_time"])
                if ti in trips:
                    trips[ti]["cells"].append(cell)
            sc["trips"] = [trips[k] for k in sorted(trips)]

        return {"timetable": tt, "notes": notes, "schedules": schedules}
    finally:
        conn.close()


@app.get("/api/stops")
def list_stops(q: str | None = None, limit: int = 20):
    conn = db.connect()
    try:
        cur = conn.cursor()
        if q:
            # Also match ignoring spaces. The timetables and the riders disagree about
            # whether a name is one word or two - BLUE DOWNS against "bluedowns", CAPE
            # TOWN against "capetown" - and a search that cannot cross a space returns
            # nothing for a stop that plainly exists.
            squashed = q.replace(" ", "")
            cur.execute(
                STOP_SELECT +
                "WHERE s.name ILIKE %s OR replace(s.name, ' ', '') ILIKE %s "
                "ORDER BY (s.name ILIKE %s) DESC, s.name LIMIT %s",
                (f"%{q}%", f"%{squashed}%", f"{q}%", limit),
            )
        else:
            cur.execute(STOP_SELECT + "ORDER BY s.name LIMIT %s", (limit,))
        return {"stops": _rows(cur)}
    finally:
        conn.close()


@app.get("/api/stops/{stop_id}/reachable")
def reachable(stop_id: int):
    """Stops reachable from stop_id on a SINGLE bus (a trip serves both, in order)."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(STOP_SELECT + "WHERE s.id=%s", (stop_id,))
        origin = _rows(cur)
        if not origin:
            raise HTTPException(404, "stop not found")
        cur.execute(
            """
            SELECT s2.id, s2.name, s2.lat, s2.lon,
                   count(*)                AS trip_count,
                   count(DISTINCT r.id)    AS route_count,
                   -- Which network gets you there. A destination list can hold both, and
                   -- a row that does not say which leaves the rider to guess. Everything
                   -- loaded before operators existed is Golden Arrow.
                   coalesce(max(o2.code), 'gabs') AS operator_code,
                   coalesce(max(o2.kind), 'bus')  AS operator_kind
            FROM schedule_stop ssx
            JOIN stop_time bx       ON bx.schedule_stop_id = ssx.id AND bx.cell_type <> 'NONE'
            JOIN stop_time byy      ON byy.trip_id = bx.trip_id AND byy.cell_type <> 'NONE'
                                   AND (bx.departure_time IS NULL OR byy.departure_time IS NULL
                                        OR byy.departure_time >= bx.departure_time)
            JOIN schedule_stop ssy  ON ssy.id = byy.schedule_stop_id
                                   AND ssy.stop_sequence > ssx.stop_sequence
            JOIN stop s2            ON s2.id = ssy.stop_id
            LEFT JOIN operator o2   ON o2.id = s2.operator_id
            JOIN schedule sc        ON sc.id = ssx.schedule_id
            JOIN timetable t        ON t.id = sc.timetable_id
            JOIN route r            ON r.id = t.route_id
            WHERE ssx.stop_id = %s AND s2.id <> %s
            GROUP BY s2.id, s2.name, s2.lat, s2.lon
            ORDER BY s2.name
            """,
            (stop_id, stop_id),
        )
        direct = _rows(cur)

        # Where else you could get to by changing bus once. Without this the app only
        # ever offered the handful of stops on a single bus - six, from a stop like BUH
        # REIN - and a rider had no way to discover that MALMESBURY is perfectly
        # reachable by changing at CAPE TOWN. The direct ones are excluded so the two
        # lists do not repeat each other.
        cur.execute(
            """
            WITH direct AS (
                SELECT DISTINCT ssy.stop_id AS mid
                FROM schedule_stop ssx
                JOIN stop_time bx  ON bx.schedule_stop_id = ssx.id AND bx.cell_type <> 'NONE'
                JOIN stop_time byy ON byy.trip_id = bx.trip_id AND byy.cell_type <> 'NONE'
                                  AND (bx.departure_time IS NULL OR byy.departure_time IS NULL
                                       OR byy.departure_time >= bx.departure_time)
                JOIN schedule_stop ssy ON ssy.id = byy.schedule_stop_id
                                      AND ssy.stop_sequence > ssx.stop_sequence
                WHERE ssx.stop_id = %s
            )
            SELECT s2.id, s2.name, s2.lat, s2.lon, count(DISTINCT d.mid) AS change_count
            FROM direct d
            JOIN schedule_stop ssx ON ssx.stop_id = d.mid
            JOIN stop_time bx  ON bx.schedule_stop_id = ssx.id AND bx.cell_type <> 'NONE'
            JOIN stop_time byy ON byy.trip_id = bx.trip_id AND byy.cell_type <> 'NONE'
                              AND (bx.departure_time IS NULL OR byy.departure_time IS NULL
                                   OR byy.departure_time >= bx.departure_time)
            JOIN schedule_stop ssy ON ssy.id = byy.schedule_stop_id
                                  AND ssy.stop_sequence > ssx.stop_sequence
            JOIN stop s2 ON s2.id = ssy.stop_id
            WHERE s2.id <> %s AND NOT EXISTS (
                SELECT 1 FROM direct dd WHERE dd.mid = s2.id
            )
            GROUP BY s2.id, s2.name, s2.lat, s2.lon
            ORDER BY s2.name
            """,
            (stop_id, stop_id),
        )
        return {"origin": origin[0], "reachable": direct, "connecting": _rows(cur)}
    finally:
        conn.close()


@app.get("/api/journeys")
def journeys(from_: int = Query(..., alias="from"), to: int = Query(...)):
    """Direct single-bus journeys from -> to, grouped by connecting schedule."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(STOP_SELECT + "WHERE s.id = ANY(%s)", ([from_, to],))
        stops = {r["id"]: r for r in _rows(cur)}
        if from_ not in stops or to not in stops:
            raise HTTPException(404, "stop not found")

        # Connecting schedules (some trip serves both from and to, in order).
        cur.execute(
            """
            SELECT sc.id AS schedule_id, sc.direction_label, sc.day_type, sc.day_label,
                   r.id AS route_id, r.name AS route_name, t.id AS timetable_id,
                   t.timetable_number AS timetable_number,
                   o.code AS operator_code, o.name AS operator_name,
                   o.kind AS operator_kind,
                   ssx.id AS ssx, ssy.id AS ssy,
                   ssx.stop_sequence AS bseq, ssy.stop_sequence AS aseq
            FROM schedule_stop ssx
            JOIN schedule_stop ssy ON ssy.schedule_id = ssx.schedule_id
                                  AND ssy.stop_sequence > ssx.stop_sequence
            JOIN schedule sc       ON sc.id = ssx.schedule_id
            JOIN timetable t       ON t.id = sc.timetable_id
            JOIN route r           ON r.id = t.route_id
            LEFT JOIN operator o   ON o.id = r.operator_id
            WHERE ssx.stop_id = %s AND ssy.stop_id = %s
              AND EXISTS (
                SELECT 1 FROM stop_time bx
                JOIN stop_time byy ON byy.trip_id = bx.trip_id
                WHERE bx.schedule_stop_id = ssx.id AND byy.schedule_stop_id = ssy.id
                  AND bx.cell_type <> 'NONE' AND byy.cell_type <> 'NONE'
                  AND (bx.departure_time IS NULL OR byy.departure_time IS NULL
                       OR byy.departure_time >= bx.departure_time)
              )
            """,
            (from_, to),
        )
        conns = _rows(cur)

        _DAY = {"WEEKDAY": 0, "SATURDAY": 1, "SUNDAY": 2, "PUBLIC_HOLIDAY": 3}
        # Group connecting schedules by (route, direction, day-type); merge their
        # departures (dedup across timetable versions) and keep one segment path.
        groups: dict[tuple, dict] = {}
        for c in conns:
            # Same physical service = same timetable number + direction path + day-type
            # (the site lists it under several origin/destination route names).
            key = (c["timetable_number"], c["direction_label"], c["day_type"])
            g = groups.get(key)
            if g is None:
                cur.execute(
                    """
                    SELECT s.name, s.lat, s.lon, ss.stop_sequence
                    FROM schedule_stop ss JOIN stop s ON s.id = ss.stop_id
                    WHERE ss.schedule_id = %s AND ss.stop_sequence BETWEEN %s AND %s
                    ORDER BY ss.stop_sequence
                    """,
                    (c["schedule_id"], c["bseq"], c["aseq"]),
                )
                g = groups[key] = {
                    "timetable_number": c["timetable_number"],
                    "route_label": c["direction_label"],  # the actual bus path
                    "operator_code": c["operator_code"],
                    "operator_name": c["operator_name"],
                    "operator_kind": c["operator_kind"],
                    "day_type": c["day_type"], "day_label": c["day_label"],
                    "timetable_ids": set(), "segment_stops": _rows(cur),
                    "departures": [], "_seen": set(),
                }
            g["timetable_ids"].add(c["timetable_id"])
            cur.execute(
                """
                SELECT bx.departure_time AS board_time, bx.raw_value AS board_raw,
                       bx.cell_type AS board_type, bx.note_code AS note_code,
                       byy.departure_time AS arrive_time, byy.raw_value AS arrive_raw,
                       byy.cell_type AS arrive_type
                FROM trip tr
                JOIN stop_time bx  ON bx.trip_id = tr.id AND bx.schedule_stop_id = %s
                JOIN stop_time byy ON byy.trip_id = tr.id AND byy.schedule_stop_id = %s
                WHERE tr.schedule_id = %s
                  AND bx.cell_type <> 'NONE' AND byy.cell_type <> 'NONE'
                  -- A stop later in the PDF is not necessarily later in the journey:
                  -- GABS prints alternative origins as the bottom rows of a grid, so
                  -- roughly one trip in twenty has times that run backwards by sequence.
                  AND (bx.departure_time IS NULL OR byy.departure_time IS NULL
                       OR byy.departure_time >= bx.departure_time)
                """,
                (c["ssx"], c["ssy"], c["schedule_id"]),
            )
            for d in _rows(cur):
                sig = (d["board_raw"], d["arrive_raw"])
                if sig in g["_seen"]:
                    continue
                g["_seen"].add(sig)
                d["board_time"] = _fmt_time(d["board_time"])
                d["arrive_time"] = _fmt_time(d["arrive_time"])
                g["departures"].append(d)

        options = []
        for g in groups.values():
            g.pop("_seen")
            g["timetable_ids"] = sorted(g["timetable_ids"])
            g["departures"].sort(key=lambda d: (d["board_time"] is None, d["board_time"] or "",
                                                d["arrive_time"] or ""))
            options.append(g)
        options.sort(key=lambda o: (_DAY.get(o["day_type"], 9), o["route_label"]))
        return {"from": stops[from_], "to": stops[to], "options": options}
    finally:
        conn.close()


def _endpoint(stop_id, lat, lon):
    if stop_id is not None:
        return {"kind": "stop", "stop_id": stop_id}
    if lat is not None and lon is not None:
        return {"kind": "pin", "lat": lat, "lon": lon}
    return None


def _describe(conn, ep):
    if ep["kind"] == "stop":
        cur = conn.cursor()
        cur.execute(STOP_SELECT + "WHERE s.id=%s", (ep["stop_id"],))
        r = _rows(cur)
        return r[0] if r else None
    return {"kind": "pin", "lat": ep["lat"], "lon": ep["lon"]}


@app.get("/api/operators")
def operators():
    """
    Who the app can plan with, and how much of each it holds.

    Counted rather than listed, because the question the UI is asking is whether pressing
    an operator's filter will show a rider anything: a chip that returns an empty screen
    is worse than one that is visibly not ready yet.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT o.code, o.name, o.kind,
                   count(DISTINCT r.id)::int AS routes,
                   count(st.id)              AS departures
            FROM operator o
            LEFT JOIN route r      ON r.operator_id = o.id
            LEFT JOIN timetable t  ON t.route_id = r.id
            LEFT JOIN schedule sc  ON sc.timetable_id = t.id
            LEFT JOIN trip tr      ON tr.schedule_id = sc.id
            LEFT JOIN stop_time st ON st.trip_id = tr.id
            GROUP BY o.code, o.name, o.kind
            ORDER BY o.name
            """
        )
        return {"operators": _rows(cur)}
    finally:
        conn.close()


@app.get("/api/areas")
def areas():
    """Route-endpoint area names that are NOT published stops (e.g. KRAAIFONTEIN,
    NYANGA, PHILIPPI) — the timetable names routes by area but lists specific timing
    points as stops. Surfaced in search so an area is a first-class origin/destination."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            WITH endpoints AS (
              SELECT DISTINCT origin AS area FROM route WHERE origin <> ''
              UNION SELECT DISTINCT destination FROM route WHERE destination <> ''
            )
            SELECT e.area FROM endpoints e
            LEFT JOIN stop s ON s.name = e.area
            WHERE s.id IS NULL
            ORDER BY e.area
            """
        )
        areas = [r[0] for r in cur.fetchall()]

        # Which of those have a station in them.
        #
        # An area is by definition a name no stop carries, so no area is ever a train
        # terminus and no name match can answer this - only geography can. A kilometre and
        # a half is the distance somebody walks to a train rather than waiting for a second
        # bus. Areas whose stops have no coordinates do not appear: the claim is made only
        # where it can be shown, because promising a train in Bluedowns sends a rider to
        # look for a station that is not there.
        cur.execute(
            """
            WITH endpoints AS (
              SELECT DISTINCT origin AS area FROM route WHERE origin <> ''
              UNION SELECT DISTINCT destination FROM route WHERE destination <> ''
            ),
            areas AS (
              SELECT e.area FROM endpoints e
              LEFT JOIN stop s ON s.name = e.area
              WHERE s.id IS NULL
            ),
            here AS (
              SELECT a.area, s.lat, s.lon
              FROM areas a
              JOIN stop s     ON s.lat IS NOT NULL AND s.name ILIKE '%' || a.area || '%'
              JOIN operator o ON o.id = s.operator_id AND o.kind = 'bus'
            )
            SELECT DISTINCT h.area
            FROM here h
            JOIN stop t     ON t.lat IS NOT NULL
            JOIN operator o ON o.id = t.operator_id AND o.kind = 'train'
            WHERE 6371 * acos(least(1,
                    cos(radians(h.lat)) * cos(radians(t.lat))
                      * cos(radians(t.lon) - radians(h.lon))
                  + sin(radians(h.lat)) * sin(radians(t.lat)))) <= 1.5
            ORDER BY h.area
            """
        )
        return {"areas": areas, "railAreas": [r[0] for r in cur.fetchall()]}
    finally:
        conn.close()


# Settlement-scale places, and nothing else.
#
# OSM's "class" says what kind of thing a feature is, and "place" is the one that means
# somewhere people live rather than a building they visit. The types are listed rather
# than taken wholesale because "place" also covers a province and an ocean, and "Western
# Cape" is not a journey.
AREA_TYPES = {
    "city", "town", "borough", "suburb", "quarter", "neighbourhood",
    "village", "hamlet", "locality", "residential", "city_block",
}


def _nominatim(q: str) -> list[dict] | None:
    """The areas Nominatim knows for this query, or None where the lookup itself failed."""
    import requests

    from .config import settings as _s
    params = {
        "q": q, "format": "json", "limit": 10,
        "countrycodes": "za", "viewbox": "18.28,-33.40,19.12,-34.45", "bounded": 0,
    }
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params, headers={"User-Agent": _s.user_agent}, timeout=20,
        )
        r.raise_for_status()
        return [h for h in r.json()
                if h.get("class") == "place" and h.get("type") in AREA_TYPES]
    except Exception:  # noqa: BLE001
        # None, not []. A failed lookup is not the same answer as "no such area", and a
        # caller that cannot tell them apart reports an outage as a place that does not
        # exist.
        return None


def _rank_places(hits: list[dict], query: str) -> list[dict]:
    """
    The areas in the order a rider reads them.

    Nominatim's own order is not it. For "kraaifontein" it returns the town last of four,
    behind a sea scout group, because its ranking is about how well a feature matched the
    address hierarchy rather than about what the word most likely meant.
    """
    ql = query.strip().lower()
    words = [w for w in ql.split() if w]
    best: dict[str, tuple[float, dict]] = {}
    for h in hits:
        name = (h.get("name") or "").strip() or h.get("display_name", query).split(",")[0].strip()
        nl = name.lower()
        if nl == ql:
            score = 1000.0
        elif nl.startswith(ql):
            score = 500.0
        else:
            score = 100.0 * sum(1 for w in words if w in nl) / len(words) if words else 0.0
        score += float(h.get("importance") or 0.0) * 10

        # One row per area, keyed on the name. Parow is mapped twice, once as a town and
        # once as the suburb inside it, and two identical rows is a choice with no
        # difference behind it.
        if nl not in best or score > best[nl][0]:
            best[nl] = (score, {"name": name, "full": h.get("display_name"),
                                "lat": float(h["lat"]), "lon": float(h["lon"])})
    ordered = sorted(best.values(), key=lambda p: -p[0])
    return [place for _, place in ordered[:4]]


@app.get("/api/geocode")
def geocode_place(q: str):
    """
    The areas a rider can name, via OpenStreetMap Nominatim (no key). For pin input.

    Areas only. Nominatim will happily return a school, a night shelter, a scout hall and
    a supermarket for "kraaifontein", and offering those as places to travel from is a
    promise the timetables cannot keep. A pin becomes a journey by matching it against the
    road a bus drives and the stops within walking distance, so naming a building produces
    "a bus passes here" for a point where, as far as anything published says, no bus stops
    at all. Golden Arrow's timetables list timing points rather than every kerb, so the app
    cannot tell the difference between a stop it does not know about and no stop.

    The named stops and stations in the same menu come from /api/stops, which is the app's
    own data, so this removes nothing a rider can actually board at.

    And only areas the network reaches. An area is worth offering when a service runs
    through it, whether or not it is anywhere near the end of a route: Woodstock is
    somewhere buses drive on the way into town, so a rider coming from Makhaza can get off
    there, and it belongs in the list even though no route is named after it.
    """
    query = (q or "").strip()
    if not query:
        return {"results": []}
    found = _nominatim(query)
    if found is None:
        return {"results": []}

    # Served areas only, and checked after ranking so the database is asked about a
    # handful of candidates rather than everything Nominatim returned.
    from . import planner
    conn = db.connect()
    try:
        return {"results": [p for p in _rank_places(found, query)
                            if planner.is_served(conn, p["lat"], p["lon"])]}
    finally:
        conn.close()


@app.get("/api/connections")
def connections(from_: int = Query(..., alias="from"), to: int = Query(...)):
    """How to get from A to B when no single bus does it: two buses, or three.

    Named stops only. The client consults this after /api/plan comes back empty.
    """
    from . import connections as conn_engine
    conn = db.connect()
    try:
        result = conn_engine.connections(conn, from_, to)
        if result is None:
            raise HTTPException(404, "stop not found")
        return result
    finally:
        conn.close()


@app.get("/api/locate")
def locate(lat: float, lon: float):
    from . import planner
    conn = db.connect()
    try:
        return {"lat": lat, "lon": lon, "legs": planner.locate_point(conn, lat, lon)}
    finally:
        conn.close()


@app.get("/api/reachable_point")
def reachable_point(lat: float, lon: float):
    from . import planner
    conn = db.connect()
    try:
        ep = {"kind": "pin", "lat": lat, "lon": lon}
        return {"origin": {"kind": "pin", "lat": lat, "lon": lon},
                "reachable": planner.reachable_from(conn, ep)}
    finally:
        conn.close()


@app.get("/api/trip_stops")
def trip_stops(schedule_id: int, trip_index: int, from_seq: int, to_seq: int):
    """The stops a specific trip actually serves between two sequence positions,
    with times — for the 'where do I get on / off' breakdown.

    Returned in travel order rather than PDF row order; see planner.order_by_time.
    """
    from . import planner
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.name, s.lat, s.lon, ss.stop_sequence,
                   st.raw_value, st.cell_type, st.departure_time
            FROM stop_time st
            JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
            JOIN stop s          ON s.id  = ss.stop_id
            JOIN trip tr         ON tr.id = st.trip_id
            WHERE tr.schedule_id = %s AND tr.trip_index = %s
              AND ss.stop_sequence >= %s AND ss.stop_sequence <= %s
              AND st.cell_type <> 'NONE'
            ORDER BY ss.stop_sequence
            """,
            (schedule_id, trip_index, from_seq, to_seq),
        )
        rows = planner.order_by_time(_rows(cur))
        for r in rows:
            r["departure_time"] = _fmt_time(r["departure_time"])

        # The footnote letters this trip uses, with their meanings. "16:20b" runs only on
        # the days note "b" describes, and each timetable defines its own letters.
        cur.execute(
            """
            SELECT DISTINCT tn.code, tn.description
            FROM stop_time st
            JOIN trip tr        ON tr.id = st.trip_id
            JOIN schedule sc    ON sc.id = tr.schedule_id
            JOIN timetable_note tn ON tn.timetable_id = sc.timetable_id
                                  AND tn.code = st.note_code
            WHERE tr.schedule_id = %s AND tr.trip_index = %s
              AND st.note_code IS NOT NULL
            ORDER BY tn.code
            """,
            (schedule_id, trip_index),
        )
        return {"stops": rows, "notes": _rows(cur)}
    finally:
        conn.close()


@app.get("/api/nearby_origins")
def nearby_origins(lat: float, lon: float, to: int, radius: int = 2500,
                   exclude: int | None = None, day_type: str | None = None):
    from . import planner
    conn = db.connect()
    try:
        return {"origins": planner.nearby_origins(conn, lat, lon, to, radius,
                                                  exclude_stop_id=exclude, day_type=day_type)}
    finally:
        conn.close()


@app.get("/api/plan")
def plan(
    from_: int | None = Query(None, alias="from"),
    from_lat: float | None = None,
    from_lon: float | None = None,
    to: int | None = None,
    to_lat: float | None = None,
    to_lon: float | None = None,
):
    from . import planner
    fe = _endpoint(from_, from_lat, from_lon)
    te = _endpoint(to, to_lat, to_lon)
    if not fe or not te:
        raise HTTPException(400, "provide from (stop id) or from_lat/from_lon, and to likewise")
    conn = db.connect()
    try:
        options = planner.resolve_journeys(conn, fe, te)
        return {"from": _describe(conn, fe), "to": _describe(conn, te), "options": options}
    finally:
        conn.close()


# Serve the built UI (if present) at "/". Registered last so /api/* wins.
_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
