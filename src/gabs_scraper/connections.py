"""Journeys that need a change of bus.

The direct planner answers "which single bus goes from A to B". This answers "and if none
does, what do I catch instead". Fewest buses wins: two legs are searched first and three
only if two finds nothing, because a commuter would rather change once than twice. Within
a leg count, results are ordered by total journey time, then by time spent waiting.

Kept byte-identical to ``ConnectionService``/``ConnectionRepository`` in the Java service,
which ``backend/parity_check.py`` verifies.

Three things make the queries work, each learned by getting it wrong first:

* **Narrow to interchange candidates first** — stops reachable from the origin that also
  reach the destination. That set is small (single figures to low hundreds) and costs
  milliseconds, and bounding the leg searches by it took one query from 10.7s to 80ms.
* **Drive the middle leg from that set rather than filtering with a tuple ``IN``.**
  ``(a, b) IN (SELECT x, y ...)`` stops PostgreSQL using the ``stop_id`` index and it
  scans the whole self-join instead: the same 31,578 rows took 23.9s that way versus 1.1s
  as a join.
* **``DISTINCT ON`` per leg.** Without it a connection repeats once per timetable version,
  exactly as the direct planner would without its grouping.

**Which times must exist.** Only 28% of timetable cells carry a published time; 19% are
"via", meaning the bus passes but no time is given. So a leg's departure and its arrival
*at an interchange* must be real times — a change you cannot time is not a plan — but
arrival at the final destination may be "via", because for many stops that is all Golden
Arrow publishes. Requiring a time there finds nothing across a large part of the network.

**Every leg moves forward in time.** A leg's arrival must be later than its departure.
The between-leg checks alone were satisfied by a bus that "arrived" hours before it left,
and because results sort by journey time those impossible connections sorted first. The
cost is that a leg genuinely crossing midnight is excluded, which is the safer trade.
"""
from __future__ import annotations

DEFAULT_BUFFER_MINUTES = 10
DEFAULT_MAX_RESULTS = 6


_TWO_LEG_SQL = """
WITH ix AS (
    SELECT DISTINCT b.stop_id AS id
    FROM schedule_stop a
    JOIN schedule_stop b ON b.schedule_id = a.schedule_id
                        AND b.stop_sequence > a.stop_sequence
    WHERE a.stop_id = %(from_id)s
    INTERSECT
    SELECT DISTINCT a.stop_id
    FROM schedule_stop a
    JOIN schedule_stop b ON b.schedule_id = a.schedule_id
                        AND b.stop_sequence > a.stop_sequence
    WHERE b.stop_id = %(to_id)s
),
leg1 AS (
    SELECT DISTINCT ON (sc.day_type, ssb.stop_id, sc.direction_label,
                        t1.departure_time, t2.departure_time)
           sc.day_type, ssb.stop_id AS x, sc.direction_label AS route,
           tt.timetable_number AS ttn,
           t1.departure_time AS dep, t2.departure_time AS arr,
           sc.id AS sched, tr.trip_index AS trip,
           ssa.stop_sequence AS from_seq, ssb.stop_sequence AS to_seq
    FROM schedule_stop ssa
    JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                          AND ssb.stop_sequence > ssa.stop_sequence
    JOIN schedule sc  ON sc.id = ssa.schedule_id
    JOIN timetable tt ON tt.id = sc.timetable_id
    JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
    JOIN stop_time t1 ON t1.trip_id = tr.id AND t1.schedule_stop_id = ssa.id
                     AND t1.cell_type = 'TIME'
    JOIN stop_time t2 ON t2.trip_id = tr.id AND t2.schedule_stop_id = ssb.id
                     AND t2.cell_type = 'TIME'
                     AND t2.departure_time > t1.departure_time
    WHERE ssa.stop_id = %(from_id)s AND ssb.stop_id IN (SELECT id FROM ix)
    ORDER BY sc.day_type, ssb.stop_id, sc.direction_label,
             t1.departure_time, t2.departure_time, sc.id, tr.trip_index
),
leg2 AS (
    SELECT DISTINCT ON (sc.day_type, ssa.stop_id, sc.direction_label,
                        t1.departure_time, t2.raw_value)
           sc.day_type, ssa.stop_id AS x, sc.direction_label AS route,
           tt.timetable_number AS ttn,
           t1.departure_time AS dep, t2.raw_value AS arr_raw,
           t2.departure_time AS arr_time,
           sc.id AS sched, tr.trip_index AS trip,
           ssa.stop_sequence AS from_seq, ssb.stop_sequence AS to_seq
    FROM schedule_stop ssa
    JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                          AND ssb.stop_sequence > ssa.stop_sequence
    JOIN schedule sc  ON sc.id = ssa.schedule_id
    JOIN timetable tt ON tt.id = sc.timetable_id
    JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
    JOIN stop_time t1 ON t1.trip_id = tr.id AND t1.schedule_stop_id = ssa.id
                     AND t1.cell_type = 'TIME'
    JOIN stop_time t2 ON t2.trip_id = tr.id AND t2.schedule_stop_id = ssb.id
                     AND t2.cell_type <> 'NONE'
                     AND (t2.departure_time IS NULL
                          OR t2.departure_time > t1.departure_time)
    WHERE ssb.stop_id = %(to_id)s AND ssa.stop_id IN (SELECT id FROM ix)
    ORDER BY sc.day_type, ssa.stop_id, sc.direction_label,
             t1.departure_time, t2.raw_value, sc.id, tr.trip_index
)
SELECT l1.day_type, x.id, x.name,
       l1.route, l1.ttn, l1.dep, l1.arr, l1.sched, l1.trip, l1.from_seq, l1.to_seq,
       l2.route, l2.ttn, l2.dep, l2.arr_raw, l2.sched, l2.trip, l2.from_seq, l2.to_seq,
       CAST(EXTRACT(EPOCH FROM (l2.dep - l1.arr)) / 60 AS integer) AS wait_minutes,
       CAST(EXTRACT(EPOCH FROM (COALESCE(l2.arr_time, l2.dep) - l1.dep)) / 60
            AS integer) AS total_minutes
FROM leg1 l1
JOIN leg2 l2 ON l2.x = l1.x AND l2.day_type = l1.day_type
            AND l2.dep >= l1.arr + (%(buffer)s * interval '1 minute')
JOIN stop x ON x.id = l1.x
ORDER BY total_minutes NULLS LAST, wait_minutes, l1.dep
LIMIT %(limit)s
"""


_THREE_LEG_SQL = """
WITH r1 AS (
    SELECT DISTINCT b.stop_id AS id
    FROM schedule_stop a
    JOIN schedule_stop b ON b.schedule_id = a.schedule_id
                        AND b.stop_sequence > a.stop_sequence
    WHERE a.stop_id = %(from_id)s
),
r3 AS (
    SELECT DISTINCT a.stop_id AS id
    FROM schedule_stop a
    JOIN schedule_stop b ON b.schedule_id = a.schedule_id
                        AND b.stop_sequence > a.stop_sequence
    WHERE b.stop_id = %(to_id)s
),
mid AS (
    SELECT DISTINCT a.stop_id AS x, b.stop_id AS y
    FROM schedule_stop a
    JOIN schedule_stop b ON b.schedule_id = a.schedule_id
                        AND b.stop_sequence > a.stop_sequence
    WHERE a.stop_id IN (SELECT id FROM r1)
      AND b.stop_id IN (SELECT id FROM r3)
      AND a.stop_id <> b.stop_id
      AND a.stop_id <> %(to_id)s AND b.stop_id <> %(from_id)s
),
leg1 AS (
    SELECT DISTINCT ON (sc.day_type, ssb.stop_id, sc.direction_label,
                        t1.departure_time, t2.departure_time)
           sc.day_type, ssb.stop_id AS x, sc.direction_label AS route,
           tt.timetable_number AS ttn,
           t1.departure_time AS dep, t2.departure_time AS arr,
           sc.id AS sched, tr.trip_index AS trip,
           ssa.stop_sequence AS from_seq, ssb.stop_sequence AS to_seq
    FROM schedule_stop ssa
    JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                          AND ssb.stop_sequence > ssa.stop_sequence
    JOIN schedule sc  ON sc.id = ssa.schedule_id
    JOIN timetable tt ON tt.id = sc.timetable_id
    JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
    JOIN stop_time t1 ON t1.trip_id = tr.id AND t1.schedule_stop_id = ssa.id
                     AND t1.cell_type = 'TIME'
    JOIN stop_time t2 ON t2.trip_id = tr.id AND t2.schedule_stop_id = ssb.id
                     AND t2.cell_type = 'TIME'
                     AND t2.departure_time > t1.departure_time
    WHERE ssa.stop_id = %(from_id)s
      AND ssb.stop_id IN (SELECT x FROM mid)
    ORDER BY sc.day_type, ssb.stop_id, sc.direction_label,
             t1.departure_time, t2.departure_time, sc.id, tr.trip_index
),
leg2 AS (
    SELECT DISTINCT ON (sc.day_type, ssa.stop_id, ssb.stop_id,
                        sc.direction_label, t1.departure_time, t2.departure_time)
           sc.day_type, ssa.stop_id AS x, ssb.stop_id AS y,
           sc.direction_label AS route, tt.timetable_number AS ttn,
           t1.departure_time AS dep, t2.departure_time AS arr,
           sc.id AS sched, tr.trip_index AS trip,
           ssa.stop_sequence AS from_seq, ssb.stop_sequence AS to_seq
    -- Driven FROM mid rather than filtering with a tuple IN; see the module docstring.
    FROM mid m
    JOIN schedule_stop ssa ON ssa.stop_id = m.x
    JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                          AND ssb.stop_id = m.y
                          AND ssb.stop_sequence > ssa.stop_sequence
    JOIN schedule sc  ON sc.id = ssa.schedule_id
    JOIN timetable tt ON tt.id = sc.timetable_id
    JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
    JOIN stop_time t1 ON t1.trip_id = tr.id AND t1.schedule_stop_id = ssa.id
                     AND t1.cell_type = 'TIME'
    JOIN stop_time t2 ON t2.trip_id = tr.id AND t2.schedule_stop_id = ssb.id
                     AND t2.cell_type = 'TIME'
                     AND t2.departure_time > t1.departure_time
    ORDER BY sc.day_type, ssa.stop_id, ssb.stop_id, sc.direction_label,
             t1.departure_time, t2.departure_time, sc.id, tr.trip_index
),
leg3 AS (
    SELECT DISTINCT ON (sc.day_type, ssa.stop_id, sc.direction_label,
                        t1.departure_time, t2.raw_value)
           sc.day_type, ssa.stop_id AS y, sc.direction_label AS route,
           tt.timetable_number AS ttn,
           t1.departure_time AS dep, t2.raw_value AS arr_raw,
           t2.departure_time AS arr_time,
           sc.id AS sched, tr.trip_index AS trip,
           ssa.stop_sequence AS from_seq, ssb.stop_sequence AS to_seq
    FROM schedule_stop ssa
    JOIN schedule_stop ssb ON ssb.schedule_id = ssa.schedule_id
                          AND ssb.stop_sequence > ssa.stop_sequence
    JOIN schedule sc  ON sc.id = ssa.schedule_id
    JOIN timetable tt ON tt.id = sc.timetable_id
    JOIN trip tr      ON tr.schedule_id = ssa.schedule_id
    JOIN stop_time t1 ON t1.trip_id = tr.id AND t1.schedule_stop_id = ssa.id
                     AND t1.cell_type = 'TIME'
    JOIN stop_time t2 ON t2.trip_id = tr.id AND t2.schedule_stop_id = ssb.id
                     AND t2.cell_type <> 'NONE'
                     AND (t2.departure_time IS NULL
                          OR t2.departure_time > t1.departure_time)
    WHERE ssb.stop_id = %(to_id)s
      AND ssa.stop_id IN (SELECT y FROM mid)
    ORDER BY sc.day_type, ssa.stop_id, sc.direction_label,
             t1.departure_time, t2.raw_value, sc.id, tr.trip_index
)
SELECT l1.day_type, x1.id, x1.name, x2.id, x2.name,
       l1.route, l1.ttn, l1.dep, l1.arr, l1.sched, l1.trip, l1.from_seq, l1.to_seq,
       l2.route, l2.ttn, l2.dep, l2.arr, l2.sched, l2.trip, l2.from_seq, l2.to_seq,
       l3.route, l3.ttn, l3.dep, l3.arr_raw, l3.sched, l3.trip, l3.from_seq, l3.to_seq,
       CAST(EXTRACT(EPOCH FROM ((l2.dep - l1.arr) + (l3.dep - l2.arr))) / 60
            AS integer) AS wait_minutes,
       CAST(EXTRACT(EPOCH FROM (COALESCE(l3.arr_time, l3.dep) - l1.dep)) / 60
            AS integer) AS total_minutes
FROM leg1 l1
JOIN leg2 l2 ON l2.x = l1.x AND l2.day_type = l1.day_type
            AND l2.dep >= l1.arr + (%(buffer)s * interval '1 minute')
JOIN leg3 l3 ON l3.y = l2.y AND l3.day_type = l2.day_type
            AND l3.dep >= l2.arr + (%(buffer)s * interval '1 minute')
JOIN stop x1 ON x1.id = l1.x
JOIN stop x2 ON x2.id = l2.y
ORDER BY total_minutes NULLS LAST, wait_minutes, l1.dep
LIMIT %(limit)s
"""


def _fmt_time(v):
    return v.strftime("%H:%M") if v is not None else None


def _minutes(v):
    return None if v is None else v.hour * 60 + v.minute


def _stop(cur, stop_id):
    cur.execute("SELECT id, name, lat, lon FROM stop WHERE id=%s", (stop_id,))
    r = cur.fetchone()
    return None if r is None else {"id": r[0], "name": r[1], "lat": r[2], "lon": r[3]}


def _coords(cur, stop_ids):
    ids = sorted({i for i in stop_ids if i is not None})
    if not ids:
        return {}
    cur.execute("SELECT id, lat, lon FROM stop WHERE id = ANY(%s)", (ids,))
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def _leg(from_id, from_name, from_ll, to_id, to_name, to_ll, route, ttn,
         board, arrive_raw, arrive_time, sched, trip, from_seq, to_seq):
    return {
        "from_stop_id": from_id, "from_name": from_name,
        "from_lat": from_ll[0], "from_lon": from_ll[1],
        "to_stop_id": to_id, "to_name": to_name,
        "to_lat": to_ll[0], "to_lon": to_ll[1],
        "route_label": route,
        "timetable_number": ttn,
        "board_raw": _fmt_time(board),
        "arrive_raw": arrive_raw,
        "board_minutes": _minutes(board),
        "arrive_minutes": _minutes(arrive_time),
        "schedule_id": sched, "trip_index": trip,
        "from_seq": from_seq, "to_seq": to_seq,
    }


def connections(conn, from_id, to_id,
                buffer_minutes=DEFAULT_BUFFER_MINUTES, limit=DEFAULT_MAX_RESULTS):
    """Two legs if possible, three if not, and nothing if neither connects."""
    cur = conn.cursor()
    origin = _stop(cur, from_id)
    dest = _stop(cur, to_id)
    if origin is None or dest is None:
        return None

    params = {"from_id": from_id, "to_id": to_id,
              "buffer": buffer_minutes, "limit": limit}
    from_ll = (origin["lat"], origin["lon"])
    to_ll = (dest["lat"], dest["lon"])

    cur.execute(_TWO_LEG_SQL, params)
    rows = cur.fetchall()
    if rows:
        coords = _coords(cur, [r[1] for r in rows])
        out = []
        for (day, xid, xname, r1, n1, d1, a1, s1, t1, f1, e1,
             r2, n2, d2, araw2, s2, t2, f2, e2, wait, total) in rows:
            xll = coords.get(xid, (None, None))
            out.append({
                "day_type": day,
                "change_at": [xname],
                "legs": [
                    _leg(from_id, origin["name"], from_ll, xid, xname, xll,
                         r1, n1, d1, _fmt_time(a1), a1, s1, t1, f1, e1),
                    _leg(xid, xname, xll, to_id, dest["name"], to_ll,
                         r2, n2, d2, araw2, None, s2, t2, f2, e2),
                ],
                "wait_minutes": wait,
                "total_minutes": total,
            })
        return {"from": origin, "to": dest, "legs_required": 2, "connections": out}

    cur.execute(_THREE_LEG_SQL, params)
    rows = cur.fetchall()
    if rows:
        coords = _coords(cur, [r[1] for r in rows] + [r[3] for r in rows])
        out = []
        for (day, xid, xname, yid, yname,
             r1, n1, d1, a1, s1, t1, f1, e1,
             r2, n2, d2, a2, s2, t2, f2, e2,
             r3, n3, d3, araw3, s3, t3, f3, e3, wait, total) in rows:
            xll = coords.get(xid, (None, None))
            yll = coords.get(yid, (None, None))
            out.append({
                "day_type": day,
                "change_at": [xname, yname],
                "legs": [
                    _leg(from_id, origin["name"], from_ll, xid, xname, xll,
                         r1, n1, d1, _fmt_time(a1), a1, s1, t1, f1, e1),
                    _leg(xid, xname, xll, yid, yname, yll,
                         r2, n2, d2, _fmt_time(a2), a2, s2, t2, f2, e2),
                    _leg(yid, yname, yll, to_id, dest["name"], to_ll,
                         r3, n3, d3, araw3, None, s3, t3, f3, e3),
                ],
                "wait_minutes": wait,
                "total_minutes": total,
            })
        return {"from": origin, "to": dest, "legs_required": 3, "connections": out}

    # Genuinely unreachable within three buses.
    return {"from": origin, "to": dest, "legs_required": None, "connections": []}
