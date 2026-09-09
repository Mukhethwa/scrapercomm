"""Does a place reach what stands beside it, everywhere?

    PYTHONPATH=src python -m prasa_scraper.reachability
    PYTHONPATH=src python -m prasa_scraper.reachability --limit 20

Mukhethwa reported that Kraaifontein High School offered buses and no train, though the
Northern Line runs past it. That was true, and the fix was general - a walking radius
applies to every place - but the checking was not: one journey, tested by hand, because
that is the one he happened to try.

A bug found by coincidence says nothing about the places nobody has tried. So this asks
the question of the whole network at once: for every station, take a point near it and see
whether the planner offers a train from there. Where it does not, say so and say how far
the station was, because that is the difference between a rule that is too tight and a
journey that genuinely does not exist.

It plans from a point rather than from the station itself. Planning from the station is a
different question - stop to stop, which has always worked - and the fault being watched
for lives in the walk between a place somebody names and the platform they end up on.
"""
from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request

from . import db_compat as db

API = "http://localhost:8000/api"

# How far from a station to drop the test point.
#
# Far enough to exercise the walk rather than land on the platform, and inside the radius
# the planner allows, so a miss is a real miss rather than a point placed out of reach on
# purpose. Roughly the distance Kraaifontein High School sits from its station.
OFFSET_M = 1800.0


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}/{path}", timeout=60) as r:
        return json.load(r)


def offset(lat: float, lon: float, metres: float, bearing_deg: float = 45.0) -> tuple[float, float]:
    """A point `metres` away, for standing somewhere near a station rather than on it."""
    r = 6371000.0
    b = math.radians(bearing_deg)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(metres / r)
                     + math.cos(lat1) * math.sin(metres / r) * math.cos(b))
    lon2 = lon1 + math.atan2(math.sin(b) * math.sin(metres / r) * math.cos(lat1),
                             math.cos(metres / r) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


def stations() -> list[tuple[int, str, float, float]]:
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.id, s.name, s.lat, s.lon
            FROM stop s JOIN operator o ON o.id = s.operator_id AND o.kind = 'train'
            WHERE s.lat IS NOT NULL
            ORDER BY s.name
            """
        )
        return [(i, n, float(la), float(lo)) for i, n, la, lo in cur.fetchall()]
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Check a place reaches the station beside it")
    ap.add_argument("--to", type=int, help="destination stop id (default: CAPE TOWN station)")
    ap.add_argument("--offset", type=float, default=OFFSET_M)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = stations()
    if args.limit:
        rows = rows[:args.limit]

    target = args.to
    if target is None:
        target = next(i for i, n, _, _ in stations() if n == "CAPE TOWN")

    reached = missed = nojourney = 0
    print(f"planning from a point {args.offset:.0f}m from each station, to stop {target}\n")
    for sid, name, lat, lon in rows:
        if sid == target:
            continue
        plat, plon = offset(lat, lon, args.offset)
        try:
            d = _get(f"plan?from_lat={plat:.6f}&from_lon={plon:.6f}&to={target}")
        except Exception as e:      # noqa: BLE001 - one station should not end the run
            print(f"  ERROR  {name}: {e}")
            continue
        options = d.get("options", [])
        trains = [o for o in options if o.get("operator_kind") == "train"]
        if trains:
            reached += 1
            continue

        # What the screen does next, so this measures what a rider sees.
        #
        # A direct plan is not the whole answer: the app asks for a journey with a change
        # when nothing runs straight through, and plenty of the network is like that.
        # PENTECH has no direct train to CAPE TOWN and thirty-seven with one change, and
        # counting only the direct plan reported that as a station nobody can reach.
        try:
            c = _get(f"connections?from_lat={plat:.6f}&from_lon={plon:.6f}&to={target}")
        except Exception:      # noqa: BLE001
            c = {}
        if c.get("connections"):
            reached += 1
            continue

        if not options:
            # No service at all from here, by anything, direct or with a change.
            nojourney += 1
            print(f"  none   {name}: nothing at all from {args.offset:.0f}m away")
        else:
            missed += 1
            buses = len(options) - len(trains)
            print(f"  MISSED {name}: {buses} bus option(s) and no train, "
                  f"from {args.offset:.0f}m away")

    total = reached + missed + nojourney
    print(f"\n{reached} of {total} stations are reached from a point {args.offset:.0f}m away")
    if missed:
        print(f"{missed} offered buses but no train - the walk rule did not carry them")
    if nojourney:
        print(f"{nojourney} had no service of any kind, which is a different question")


if __name__ == "__main__":
    main()
