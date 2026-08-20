"""Journey planning over official timing points AND unofficial pin locations.

An **endpoint** is either a named stop or a pin (lat/lon). Each endpoint resolves to a
set of *anchors* — one per (schedule, trip) it touches — carrying a fractional
``position`` along the trip's stop sequence and a departure/arrival time:

* stop  -> position = stop_sequence, exact time.
* pin   -> matched to legs whose real road path passes within a threshold; position =
           seq_A + f (f = fraction along the A->B leg), time = interpolate(t_A, t_B, f),
           flagged approximate.

A journey exists on a trip when a board anchor precedes an alight anchor (position and
time consistent). Results are grouped by physical service (timetable number + direction
+ day-type), the same as the stop-only planner. Direct buses only.
"""
from __future__ import annotations

import json
import math

from . import geo

DEFAULT_THRESHOLD_M = 700.0  # tolerance for imprecise pins / place-search centroids
_DAY = {"WEEKDAY": 0, "SATURDAY": 1, "SUNDAY": 2, "PUBLIC_HOLIDAY": 3}


def _min(t):
    return None if t is None else t.hour * 60 + t.minute


def _mmss(m):
    if m is None:
        return None
    m = int(round(m))
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


# ---- point location ----

def locate_point(conn, lat, lon, threshold_m=DEFAULT_THRESHOLD_M):
    """Legs whose real road path passes within threshold of (lat, lon).

    Returns list of {from_stop_id, to_stop_id, distance_m, fraction} sorted by distance.
    """
    deg = threshold_m / 111000.0 + 0.001
    cur = conn.cursor()
    cur.execute(
        """
        SELECT from_stop_id, to_stop_id, path, length_m
        FROM leg_geometry
        WHERE path IS NOT NULL
          AND min_lat - %s <= %s AND max_lat + %s >= %s
          AND min_lon - %s <= %s AND max_lon + %s >= %s
        """,
        (deg, lat, deg, lat, deg, lon, deg, lon),
    )
    out = []
    for a, b, path, length_m in cur.fetchall():
        if isinstance(path, str):
            path = json.loads(path)
        d, f = geo.locate_on_path(path, length_m, lat, lon)
        if d <= threshold_m:
            out.append({"from_stop_id": a, "to_stop_id": b, "distance_m": round(d, 1),
                        "fraction": round(f, 4)})
    out.sort(key=lambda r: r["distance_m"])
    return out


# ---- anchors ----

def _stop_anchors(conn, stop_id):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ss.schedule_id, tr.trip_index, ss.stop_sequence, st.departure_time,
               st.raw_value, s.name
        FROM schedule_stop ss
        JOIN stop s        ON s.id = ss.stop_id
        JOIN stop_time st  ON st.schedule_stop_id = ss.id AND st.cell_type <> 'NONE'
        JOIN trip tr       ON tr.id = st.trip_id
        WHERE ss.stop_id = %s
        """,
        (stop_id,),
    )
    anchors = {}
    for sch, ti, seq, dt, raw, name in cur.fetchall():
        anchors.setdefault((sch, ti), []).append({
            "position": float(seq), "minutes": _min(dt), "raw": raw,
            "approx": False, "label": name, "distance_m": 0.0,
        })
    return anchors


def _pin_anchors(conn, lat, lon, threshold_m):
    legs = locate_point(conn, lat, lon, threshold_m)
    anchors = {}
    cur = conn.cursor()
    for leg in legs:
        cur.execute(
            """
            SELECT ssA.schedule_id, tr.trip_index, ssA.stop_sequence,
                   sta.departure_time, stb.departure_time, sa.name, sb.name
            FROM schedule_stop ssA
            JOIN schedule_stop ssB ON ssB.schedule_id = ssA.schedule_id
                                  AND ssB.stop_sequence = ssA.stop_sequence + 1
                                  AND ssB.stop_id = %s
            JOIN stop sa ON sa.id = ssA.stop_id
            JOIN stop sb ON sb.id = ssB.stop_id
            JOIN trip tr ON tr.schedule_id = ssA.schedule_id
            JOIN stop_time sta ON sta.trip_id = tr.id AND sta.schedule_stop_id = ssA.id
                              AND sta.cell_type <> 'NONE'
            JOIN stop_time stb ON stb.trip_id = tr.id AND stb.schedule_stop_id = ssB.id
                              AND stb.cell_type <> 'NONE'
            WHERE ssA.stop_id = %s
            """,
            (leg["to_stop_id"], leg["from_stop_id"]),
        )
        f = leg["fraction"]
        for sch, ti, seqA, tA, tB, nameA, nameB in cur.fetchall():
            ma, mb = _min(tA), _min(tB)
            minutes = None
            if ma is not None and mb is not None:
                minutes = ma + f * (mb - ma)
            elif ma is not None:
                minutes = ma
            elif mb is not None:
                minutes = mb
            anchors.setdefault((sch, ti), []).append({
                "position": seqA + f,
                "minutes": minutes,
                "raw": _mmss(minutes) or "via",
                "approx": True,
                "label": f"near {nameA}–{nameB}",
                "distance_m": leg["distance_m"],
            })
    return anchors


def endpoint_anchors(conn, ep, threshold_m=DEFAULT_THRESHOLD_M):
    if ep["kind"] == "stop":
        return _stop_anchors(conn, ep["stop_id"])
    return _pin_anchors(conn, ep["lat"], ep["lon"], threshold_m)


# ---- schedule metadata + segment ----

def _schedule_meta(conn, schedule_ids):
    if not schedule_ids:
        return {}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sc.id, sc.direction_label, sc.day_type, sc.day_label,
               t.timetable_number
        FROM schedule sc JOIN timetable t ON t.id = sc.timetable_id
        WHERE sc.id = ANY(%s)
        """,
        (list(schedule_ids),),
    )
    return {r[0]: {"direction_label": r[1], "day_type": r[2], "day_label": r[3],
                   "timetable_number": r[4]} for r in cur.fetchall()}


def _segment(conn, schedule_id, from_pos, to_pos):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.id, s.name, s.lat, s.lon, ss.stop_sequence
        FROM schedule_stop ss JOIN stop s ON s.id = ss.stop_id
        WHERE ss.schedule_id = %s AND ss.stop_sequence >= %s AND ss.stop_sequence <= %s
        ORDER BY ss.stop_sequence
        """,
        (schedule_id, int(from_pos), int(to_pos) + 1),
    )
    return [{"stop_id": i, "name": n, "lat": la, "lon": lo, "stop_sequence": sq}
            for i, n, la, lo, sq in cur.fetchall()]


def _leg_path(cur, a, b):
    """Cached road geometry for one leg, or a straight line if none was fetched."""
    cur.execute(
        "SELECT path FROM leg_geometry WHERE from_stop_id=%s AND to_stop_id=%s", (a, b)
    )
    row = cur.fetchone()
    path = row[0] if row else None
    if isinstance(path, str):
        path = json.loads(path)
    if not path:
        cur.execute("SELECT id, lat, lon FROM stop WHERE id IN (%s, %s)", (a, b))
        coords = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        ca, cb = coords.get(a), coords.get(b)
        path = ([[ca[0], ca[1]], [cb[0], cb[1]]]
                if ca and cb and ca[0] is not None and cb[0] is not None else [])
    return path


def _road_path(conn, seg, from_pos, to_pos):
    """The road the passenger actually rides — nothing before boarding, nothing after
    alighting.

    ``seg`` spans the *enclosing* timing points (``int(from_pos)`` to
    ``int(to_pos) + 1``) because a leg's geometry is only available between two of them.
    The ride itself starts wherever the boarding endpoint really is: exactly at a timing
    point, or a fraction along the leg that follows it. Drawing the whole enclosing range
    put road on the map that the passenger is never on — which is what made the bus look
    like it detoured to collect them from an unofficial stop.
    """
    lo = int(from_pos)
    hi = int(to_pos) + (1 if to_pos > int(to_pos) else 0)
    head_f = from_pos - lo          # 0.0 when boarding exactly at a timing point
    tail_f = to_pos - int(to_pos)   # 0.0 when alighting exactly at a timing point

    ids = [s["stop_id"] for s in seg
           if s["stop_id"] is not None and lo <= s["stop_sequence"] <= hi]
    legs = list(zip(ids, ids[1:]))
    if not legs:
        return []

    cur = conn.cursor()
    full: list[list[float]] = []
    for i, (a, b) in enumerate(legs):
        path = _leg_path(cur, a, b)
        if not path:
            continue
        start_f = head_f if i == 0 else 0.0
        end_f = tail_f if (i == len(legs) - 1 and tail_f > 0) else 1.0
        if start_f > 0 or end_f < 1:
            path = geo.slice_path(path, start_f, end_f)
        if not path:
            continue
        if full and full[-1] == path[0]:
            path = path[1:]
        full.extend(path)
    return full


# ---- journeys ----

def resolve_journeys(conn, from_ep, to_ep, threshold_m=DEFAULT_THRESHOLD_M):
    board = endpoint_anchors(conn, from_ep, threshold_m)
    alight = endpoint_anchors(conn, to_ep, threshold_m)

    # Candidate journeys per (schedule, trip): earliest board, first alight after it.
    #
    # Iterate in (schedule, trip) order rather than set order. Python does not define the
    # iteration order of a set, and it decided real output: which trip a departure was
    # attributed to, and — because departures are sorted only by board time and the sort
    # is stable — the order of any departures that leave at the same minute. Sorting here
    # makes the result reproducible and identical to the Java service.
    raw = []
    for key in sorted(set(board) & set(alight)):
        sch, ti = key
        b = min(board[key], key=lambda x: x["position"])
        later = [a for a in alight[key] if a["position"] > b["position"]
                 and (a["minutes"] is None or b["minutes"] is None or a["minutes"] >= b["minutes"] - 1)]
        if not later:
            continue
        a = min(later, key=lambda x: x["position"])
        raw.append((sch, ti, b, a))

    meta = _schedule_meta(conn, {r[0] for r in raw})
    groups = {}
    seg_cache = {}
    for sch, ti, b, a in raw:
        m = meta.get(sch)
        if not m:
            continue
        gkey = (m["timetable_number"], m["direction_label"], m["day_type"])
        g = groups.get(gkey)
        if g is None:
            if sch not in seg_cache:
                seg_cache[sch] = _segment(conn, sch, b["position"], a["position"])
            seg = seg_cache[sch]
            g = groups[gkey] = {
                "timetable_number": m["timetable_number"], "route_label": m["direction_label"],
                "day_type": m["day_type"], "day_label": m["day_label"],
                "segment_stops": seg,
                "road_path": _road_path(conn, seg, b["position"], a["position"]),
                "departures": [], "_seen": set(),
                "board_approx": b["approx"], "alight_approx": a["approx"],
                "board_label": b["label"], "alight_label": a["label"],
            }
        sig = (b["raw"], a["raw"])
        if sig in g["_seen"]:
            continue
        g["_seen"].add(sig)
        g["departures"].append({
            "board_raw": b["raw"], "board_approx": b["approx"], "board_minutes": b["minutes"],
            "arrive_raw": a["raw"], "arrive_approx": a["approx"], "arrive_minutes": a["minutes"],
            # source trip + segment range so the UI can fetch a stop-by-stop breakdown
            "schedule_id": sch, "trip_index": ti,
            "from_seq": max(0, math.ceil(b["position"] - 1e-6)),
            "to_seq": int(a["position"] + 1e-6),
        })

    options = []
    for g in groups.values():
        g.pop("_seen")
        g["departures"].sort(key=lambda d: (d["board_minutes"] is None, d["board_minutes"] or 0))
        options.append(g)
    options.sort(key=lambda o: (_DAY.get(o["day_type"], 9), o["route_label"]))
    return options


def nearby_origins(conn, lat, lon, to_stop_id, radius_m=2500, limit=8,
                   exclude_stop_id=None, day_type=None):
    """Stops within radius of (lat,lon) that DO have a direct bus to to_stop_id —
    for suggesting an alternative boarding point when your own stop has none."""
    deg = radius_m / 111000.0 + 0.001
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, lat, lon FROM stop
        WHERE lat IS NOT NULL AND lat BETWEEN %s AND %s AND lon BETWEEN %s AND %s
          AND id <> %s AND id <> COALESCE(%s, -1)
        """,
        (lat - deg, lat + deg, lon - deg, lon + deg, to_stop_id, exclude_stop_id),
    )
    cands = []
    for sid, name, slat, slon in cur.fetchall():
        d = geo.haversine_m(lat, lon, slat, slon)
        if d <= radius_m and not (exclude_stop_id is None and d < 30):
            cands.append((d, sid, name, slat, slon))
    cands.sort(key=lambda c: c[0])

    out = []
    for d, sid, name, slat, slon in cands[:60]:
        cur.execute(
            """
            SELECT min(b.departure_time), count(*)
            FROM schedule_stop ss1
            JOIN schedule_stop ss2 ON ss2.schedule_id = ss1.schedule_id
                                  AND ss2.stop_sequence > ss1.stop_sequence
            JOIN schedule sc ON sc.id = ss1.schedule_id
            JOIN trip tr ON tr.schedule_id = ss1.schedule_id
            JOIN stop_time b ON b.trip_id = tr.id AND b.schedule_stop_id = ss1.id
                            AND b.cell_type <> 'NONE'
            JOIN stop_time a ON a.trip_id = tr.id AND a.schedule_stop_id = ss2.id
                            AND a.cell_type <> 'NONE'
            WHERE ss1.stop_id = %s AND ss2.stop_id = %s
              AND (%s::text IS NULL OR sc.day_type = %s)
            """,
            (sid, to_stop_id, day_type, day_type),
        )
        earliest, cnt = cur.fetchone()
        if cnt:
            out.append({
                "id": sid, "name": name, "lat": slat, "lon": slon,
                "distance_m": round(d), "trip_count": cnt,
                "earliest": earliest.strftime("%H:%M") if earliest else None,
            })
        if len(out) >= limit:
            break
    return out


def reachable_from(conn, ep, threshold_m=DEFAULT_THRESHOLD_M):
    """Distinct downstream stops reachable from an endpoint on a single bus."""
    board = endpoint_anchors(conn, ep, threshold_m)
    if not board:
        return []
    cur = conn.cursor()
    dest = {}
    for (sch, ti), anchors in board.items():
        pos = min(a["position"] for a in anchors)
        cur.execute(
            """
            SELECT s.id, s.name, s.lat, s.lon
            FROM stop_time st
            JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
            JOIN stop s ON s.id = ss.stop_id
            JOIN trip tr ON tr.id = st.trip_id
            WHERE tr.schedule_id = %s AND tr.trip_index = %s
              AND st.cell_type <> 'NONE' AND ss.stop_sequence > %s
            """,
            (sch, ti, pos),
        )
        for sid, name, la, lo in cur.fetchall():
            d = dest.get(sid)
            if d is None:
                d = dest[sid] = {"id": sid, "name": name, "lat": la, "lon": lo, "trip_count": 0}
            d["trip_count"] += 1
    out = list(dest.values())
    out.sort(key=lambda r: r["name"])
    return out
