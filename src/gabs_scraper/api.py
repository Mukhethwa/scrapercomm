"""Read-only FastAPI server over the GABS timetable database.

Endpoints (all JSON):
  GET /api/health
  GET /api/routes?q=&letter=            -> routes with timetable counts
  GET /api/routes/{route_id}            -> route + its timetables
  GET /api/timetables/{timetable_id}    -> full render payload (schedules,
                                           stops w/ coords, trips, stop_times, notes)

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
            cur.execute(
                "SELECT id, name, lat, lon FROM stop WHERE name ILIKE %s "
                "ORDER BY (name ILIKE %s) DESC, name LIMIT %s",
                (f"%{q}%", f"{q}%", limit),
            )
        else:
            cur.execute("SELECT id, name, lat, lon FROM stop ORDER BY name LIMIT %s", (limit,))
        return {"stops": _rows(cur)}
    finally:
        conn.close()


@app.get("/api/stops/{stop_id}/reachable")
def reachable(stop_id: int):
    """Stops reachable from stop_id on a SINGLE bus (a trip serves both, in order)."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, lat, lon FROM stop WHERE id=%s", (stop_id,))
        origin = _rows(cur)
        if not origin:
            raise HTTPException(404, "stop not found")
        cur.execute(
            """
            SELECT s2.id, s2.name, s2.lat, s2.lon,
                   count(*)                AS trip_count,
                   count(DISTINCT r.id)    AS route_count
            FROM schedule_stop ssx
            JOIN stop_time bx       ON bx.schedule_stop_id = ssx.id AND bx.cell_type <> 'NONE'
            JOIN stop_time byy      ON byy.trip_id = bx.trip_id AND byy.cell_type <> 'NONE'
            JOIN schedule_stop ssy  ON ssy.id = byy.schedule_stop_id
                                   AND ssy.stop_sequence > ssx.stop_sequence
            JOIN stop s2            ON s2.id = ssy.stop_id
            JOIN schedule sc        ON sc.id = ssx.schedule_id
            JOIN timetable t        ON t.id = sc.timetable_id
            JOIN route r            ON r.id = t.route_id
            WHERE ssx.stop_id = %s AND s2.id <> %s
            GROUP BY s2.id, s2.name, s2.lat, s2.lon
            ORDER BY s2.name
            """,
            (stop_id, stop_id),
        )
        return {"origin": origin[0], "reachable": _rows(cur)}
    finally:
        conn.close()


@app.get("/api/journeys")
def journeys(from_: int = Query(..., alias="from"), to: int = Query(...)):
    """Direct single-bus journeys from -> to, grouped by connecting schedule."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, lat, lon FROM stop WHERE id = ANY(%s)", ([from_, to],))
        stops = {r["id"]: r for r in _rows(cur)}
        if from_ not in stops or to not in stops:
            raise HTTPException(404, "stop not found")

        # Connecting schedules (some trip serves both from and to, in order).
        cur.execute(
            """
            SELECT sc.id AS schedule_id, sc.direction_label, sc.day_type, sc.day_label,
                   r.id AS route_id, r.name AS route_name, t.id AS timetable_id,
                   t.timetable_number AS timetable_number,
                   ssx.id AS ssx, ssy.id AS ssy,
                   ssx.stop_sequence AS bseq, ssy.stop_sequence AS aseq
            FROM schedule_stop ssx
            JOIN schedule_stop ssy ON ssy.schedule_id = ssx.schedule_id
                                  AND ssy.stop_sequence > ssx.stop_sequence
            JOIN schedule sc       ON sc.id = ssx.schedule_id
            JOIN timetable t       ON t.id = sc.timetable_id
            JOIN route r           ON r.id = t.route_id
            WHERE ssx.stop_id = %s AND ssy.stop_id = %s
              AND EXISTS (
                SELECT 1 FROM stop_time bx
                JOIN stop_time byy ON byy.trip_id = bx.trip_id
                WHERE bx.schedule_stop_id = ssx.id AND byy.schedule_stop_id = ssy.id
                  AND bx.cell_type <> 'NONE' AND byy.cell_type <> 'NONE'
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
        cur.execute("SELECT id, name, lat, lon FROM stop WHERE id=%s", (ep["stop_id"],))
        r = _rows(cur)
        return r[0] if r else None
    return {"kind": "pin", "lat": ep["lat"], "lon": ep["lon"]}


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
        return {"areas": [r[0] for r in cur.fetchall()]}
    finally:
        conn.close()


@app.get("/api/geocode")
def geocode_place(q: str):
    """Geocode a place/address via OpenStreetMap Nominatim (no key). For pin input."""
    import requests

    from .config import settings as _s
    params = {
        "q": f"{q}, Cape Town, South Africa", "format": "json", "limit": 5,
        "countrycodes": "za", "viewbox": "18.28,-33.40,19.12,-34.45", "bounded": 0,
    }
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params, headers={"User-Agent": _s.user_agent}, timeout=20,
        )
        r.raise_for_status()
        hits = [{"name": h.get("display_name", q).split(",")[0],
                 "full": h.get("display_name"), "lat": float(h["lat"]), "lon": float(h["lon"])}
                for h in r.json()]
    except Exception:  # noqa: BLE001
        hits = []
    return {"results": hits}


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
    with times — for the 'where do I get on / off' breakdown."""
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
        rows = _rows(cur)
        for r in rows:
            r["departure_time"] = _fmt_time(r["departure_time"])
        return {"stops": rows}
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
