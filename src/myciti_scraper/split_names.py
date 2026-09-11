"""One name, two places.

    PYTHONPATH=src python -m myciti_scraper.split_names --dry-run
    PYTHONPATH=src python -m myciti_scraper.split_names

MyCiTi calls a stop in Gardens "Highlands" and a stop in Mitchells Plain "Highlands", and
a stop is unique by name and operator, so both loaded onto one row. That is not an
untidiness, it is a false interchange: routes 101 and 111 now meet D03 and D04 at a stop
that exists in two places twenty kilometres apart, and the connections engine joins
journeys at a stop id without asking where it is. A rider would be offered a change from
a Gardens bus onto a Mitchells Plain one, at a stop they are already standing at.

Leaving the stop unplaced does not fix it. The planner needs coordinates but the
connections engine does not - it joins on the id - so an unplaced shared stop still
manufactures the journey and merely stops anyone seeing where it happens.

So the row is split. The schedules that call there are grouped by where the REST of their
stops are, and each group away from the original keeps the name with its area in brackets:
"Highlands (Mitchells Plain)". The name a rider searches still finds both, and the two are
no longer one place.

This is the same fault Golden Arrow has with VICTORIA RD, where eight routes share one row
across the peninsula. That one is untouched here: this step only looks at MyCiTi, and
widening it is a separate decision about somebody else's data.
"""
from __future__ import annotations

import argparse
import collections
import statistics

from . import db_compat as db
from .positions import (IMPOSSIBLE_KMH, OPERATOR_CODE, _minutes, _sequences,
                        candidates, metres, squash)

# How far apart two groups of schedules must sit before one name is two places.
#
# Generous on purpose. A trunk route's terminus genuinely has neighbours twenty-five
# kilometres from another route's, so distance alone cannot decide this - which is why
# the timetable has the casting vote below.
APART_M = 8000.0


def _placements(cur) -> dict[int, tuple[float, float]]:
    """Positions from OpenStreetMap alone, which is all this step needs to cluster by."""
    found = candidates()
    cur.execute(
        "SELECT s.id, s.name FROM stop s "
        "JOIN operator o ON o.id = s.operator_id AND o.code = %s",
        (OPERATOR_CODE,),
    )
    placed = {}
    for sid, name in cur.fetchall():
        hits = found.get(squash(name), [])
        if not hits:
            continue
        pick = [h for h in hits if h["myciti"]] or hits
        if len(pick) == 1 or all(
                metres((pick[0]["lat"], pick[0]["lon"]), (h["lat"], h["lon"])) < 400
                for h in pick):
            placed[sid] = (sum(h["lat"] for h in pick) / len(pick),
                           sum(h["lon"] for h in pick) / len(pick))
    return placed


def _schedule_middles(cur, placed) -> dict[int, dict[int, tuple[float, float]]]:
    """For each stop, where the rest of each calling schedule sits."""
    cur.execute(
        """
        SELECT ss.schedule_id, ss.stop_id
        FROM schedule_stop ss
        JOIN schedule sc ON sc.id = ss.schedule_id
        JOIN timetable t ON t.id = sc.timetable_id
        JOIN route r     ON r.id = t.route_id
        JOIN operator o  ON o.id = r.operator_id AND o.code = %s
        """,
        (OPERATOR_CODE,),
    )
    members = collections.defaultdict(list)
    for sched, stop_id in cur.fetchall():
        members[sched].append(stop_id)

    out: dict[int, dict[int, tuple[float, float]]] = collections.defaultdict(dict)
    for sched, stop_ids in members.items():
        pts = [placed[s] for s in stop_ids if s in placed]
        if len(pts) < 3:
            continue
        middle = (statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts))
        for s in stop_ids:
            out[s][sched] = middle
    return out


def _impossible(placed, sequences) -> set[int]:
    """Stops whose position the timetable rules out - see positions.implausible."""
    speeds = collections.defaultdict(list)
    for seq in sequences:
        timed = [(sid, _minutes(w)) for sid, w in seq
                 if sid in placed and _minutes(w) is not None]
        for (a, ta), (b, tb) in zip(timed, timed[1:]):
            if tb - ta <= 0:
                continue
            kmh = (metres(placed[a], placed[b]) / 1000.0) / ((tb - ta) / 60.0)
            speeds[a].append(kmh)
            speeds[b].append(kmh)
    return {s for s, v in speeds.items() if statistics.median(v) > IMPOSSIBLE_KMH}


def _area_near(cur, point) -> str | None:
    """The mapped place nearest a position, to name the half being split off."""
    cur.execute(
        """
        SELECT name FROM area
        WHERE kind NOT IN ('stop') AND lat IS NOT NULL
        ORDER BY 6371000 * acos(least(1,
            cos(radians(lat)) * cos(radians(%s)) * cos(radians(%s) - radians(lon))
          + sin(radians(lat)) * sin(radians(%s))))
        LIMIT 1
        """,
        (point[0], point[1], point[0]),
    )
    row = cur.fetchone()
    return row[0] if row else None


def find(cur) -> list[dict]:
    """Names used for two places, with the schedules belonging to each."""
    placed = _placements(cur)
    sequences = _sequences(cur)
    suspect = _impossible(placed, sequences)
    middles = _schedule_middles(cur, placed)

    cur.execute(
        "SELECT s.id, s.name FROM stop s "
        "JOIN operator o ON o.id = s.operator_id AND o.code = %s",
        (OPERATOR_CODE,),
    )
    names = dict(cur.fetchall())

    out = []
    for sid in sorted(suspect):
        where = middles.get(sid) or {}
        if len(where) < 2:
            continue
        # Two groups, split at the widest gap from the first schedule's middle.
        anchor = next(iter(where.values()))
        near = {s: p for s, p in where.items() if metres(anchor, p) <= APART_M}
        far = {s: p for s, p in where.items() if metres(anchor, p) > APART_M}
        if not far:
            continue          # one place after all; the position is simply wrong
        # The half that keeps the original row is the one the mapped object belongs to.
        here = placed.get(sid)
        if here and statistics.median(metres(here, p) for p in far.values()) < \
                statistics.median(metres(here, p) for p in near.values()):
            near, far = far, near
        centre = (statistics.median(p[0] for p in far.values()),
                  statistics.median(p[1] for p in far.values()))
        out.append({
            "stop_id": sid,
            "name": names[sid],
            "keep": sorted(near),
            "move": sorted(far),
            "area": _area_near(cur, centre),
            "centre": centre,
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Split MyCiTi stops that are two places")
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()

    conn = db.connect()
    try:
        cur = conn.cursor()
        print("asking OpenStreetMap where MyCiTi's stops are...", flush=True)
        splits = find(cur)
        if not splits:
            print("\nno MyCiTi stop name is used for two places")
            return
        print(f"\n{len(splits)} name(s) used for two places:")
        for s in splits:
            print(f"   {s['name']}: {len(s['keep'])} schedules stay, "
                  f"{len(s['move'])} move to \"{s['name']} ({s['area']})\"")
        if args.dry_run:
            print("\ndry run: nothing written")
            return

        op = None
        for s in splits:
            if op is None:
                cur.execute("SELECT id FROM operator WHERE code = %s", (OPERATOR_CODE,))
                op = cur.fetchone()[0]
            new_name = f"{s['name']} ({s['area']})" if s["area"] else f"{s['name']} (2)"
            cur.execute(
                "INSERT INTO stop (name, operator_id) VALUES (%s, %s) "
                "ON CONFLICT (name, operator_id) DO UPDATE SET name = EXCLUDED.name "
                "RETURNING id",
                (new_name, op),
            )
            new_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE schedule_stop SET stop_id = %s "
                "WHERE stop_id = %s AND schedule_id = ANY(%s)",
                (new_id, s["stop_id"], s["move"]),
            )
            print(f"   {cur.rowcount} calling points moved to {new_name}")
        conn.commit()
        print("\nsplit written; re-run myciti_scraper.positions to place the new rows")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
