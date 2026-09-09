"""Bus stops that are not where their route says they are.

    PYTHONPATH=src python -m gabs_scraper.stop_positions
    PYTHONPATH=src python -m gabs_scraper.stop_positions --limit 5

The same question prasa_scraper.positions asks of stations, asked of Golden Arrow's stops
and answered by the route rather than by a namesake: a stop sits BETWEEN its neighbours, so
if riding A - B - C is far longer than riding A - C, B is not on that road.

Why it matters is not the map. A stop's coordinates are what leg_geometry is built from,
and leg_geometry is what turns a place a rider names into a journey. Put a Stellenbosch
street in the Cape Town CBD and the leg drawn to it sweeps forty kilometres across the
metro - so a pin dropped in Kraaifontein lands "on" the Cape Town to Stellenbosch bus, and
the planner offers a journey that boards in Kraaifontein and alights in Cape Town on a bus
that started in Cape Town. Every step of that is the code working correctly on a
coordinate that is wrong.

What it found the first time it ran: CLUVER STR, BIRD STR and MERRIMAN RD are streets in
Stellenbosch, used by no route but CAPE TOWN - STELLENBOSCH, geocoded to same-named streets
in the CBD, Muizenberg and Kuils River. Geocoding a bare street name against a city of four
million finds a street; it does not find the right one.

A FLAGGED STOP IS NOT NECESSARILY A WRONG ONE, and this matters more the fewer are left.
The measure cannot tell three things apart: a stop in the wrong place, a stop whose
NEIGHBOUR is in the wrong place, and a route that genuinely doubles back. ABBOTSDALE sits
17 km off the line between MALMESBURY and KALBASKRAAL and is exactly where Abbotsdale is -
the bus really does go out there and come back. PEP FACTORY is flagged and stands next to
PEPCOR FACTORY in Parow, which is precisely where it should be.

So the number falling is progress and the number reaching zero is not the goal. After
gabs_scraper.repair_positions took this from 69 to 11, the survivors are mostly at the
limit of what the route can say about them.

REPORTS ONLY, and deliberately. A stop is judged against its neighbours, and the odd one
out is sometimes the only correct one - prasa_scraper.positions learned that the hard way,
nearly deleting DAL JOSAFAT, the single well-placed station on its stretch of line. Nothing
here can tell which side of a disagreement is wrong, so it says what it sees and stops. The
repair is to geocode the name again with its town, which is a different job with a
different source of truth.
"""
from __future__ import annotations

import argparse
import collections
import math

from . import db

# How much doubling back a stop has to force before it is worth reporting, in kilometres,
# at its BEST showing on any route it serves.
#
# A stop on the road adds nothing to the ride: A to B to C is A to C. Ten kilometres of
# detour is not a stop slightly off the line, it is a stop somewhere else - and taking the
# best across every route means a stop is only named when no route can vouch for it.
LIMIT_KM = 10.0


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    inner = (math.sin(la1) * math.sin(la2)
             + math.cos(la1) * math.cos(la2) * math.cos(lo2 - lo1))
    return 6371.0 * math.acos(max(-1.0, min(1.0, inner)))


def detours(conn) -> tuple[dict[int, float], dict[int, str], int, int]:
    """For every located bus stop, the least detour it forces on any route it serves."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ss.schedule_id, ss.stop_sequence, s.id, s.name, s.lat, s.lon
        FROM schedule_stop ss
        JOIN stop s     ON s.id = ss.stop_id
        JOIN operator o ON o.id = s.operator_id AND o.kind = 'bus'
        WHERE s.lat IS NOT NULL
        ORDER BY ss.schedule_id, ss.stop_sequence
        """
    )
    schedules: dict[int, list] = collections.defaultdict(list)
    for sched, _seq, stop_id, name, lat, lon in cur.fetchall():
        schedules[sched].append((stop_id, name, float(lat), float(lon)))

    best: dict[int, float] = {}
    names: dict[int, str] = {}
    for stops in schedules.values():
        for i in range(1, len(stops) - 1):
            _, _, alat, alon = stops[i - 1]
            bid, bname, blat, blon = stops[i]
            _, _, clat, clon = stops[i + 1]
            extra = (km((alat, alon), (blat, blon)) + km((blat, blon), (clat, clon))
                     - km((alat, alon), (clat, clon)))
            names[bid] = bname
            if bid not in best or extra < best[bid]:
                best[bid] = extra
    return best, names, len(best), len(schedules)


def routes_of(conn, stop_id: int, limit: int) -> list[str]:
    """The routes a stop serves - the context that says which town it should be in."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT r.name
        FROM schedule_stop ss
        JOIN schedule sc  ON sc.id = ss.schedule_id
        JOIN timetable t  ON t.id = sc.timetable_id
        JOIN route r      ON r.id = t.route_id
        WHERE ss.stop_id = %s
        ORDER BY r.name
        LIMIT %s
        """,
        (stop_id, limit),
    )
    return [r[0] for r in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser(description="Find bus stops placed off their own route")
    ap.add_argument("--limit-km", type=float, default=LIMIT_KM)
    ap.add_argument("--limit", type=int, default=40, help="how many to list")
    ap.add_argument("--routes", type=int, default=2, help="routes to name per stop")
    args = ap.parse_args()

    conn = db.connect()
    try:
        best, names, judged, schedules = detours(conn)
        bad = sorted(((extra, sid) for sid, extra in best.items() if extra > args.limit_km),
                     reverse=True)

        print(f"{judged} located bus stops judged by their neighbours "
              f"on {schedules} schedules")
        if not bad:
            print("every one of them is on the road its route drives")
            return

        print(f"{len(bad)} force more than {args.limit_km:.0f} km of detour on EVERY "
              f"route they serve\n")
        for extra, sid in bad[:args.limit]:
            print(f"  {extra:7.1f} km  {names[sid]}  (stop {sid})")
            for route in routes_of(conn, sid, args.routes):
                print(f"               on {route}")
        if len(bad) > args.limit:
            print(f"\n  ... and {len(bad) - args.limit} more")

        print("\nNothing was changed. A stop is judged against its neighbours and the odd "
              "one out is\nsometimes the only right one, so this reports and stops. The "
              "repair is to geocode the\nname again with the town its route names, and to "
              "keep the answer only where it puts\nthe stop back on the road.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
