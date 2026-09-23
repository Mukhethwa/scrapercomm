"""MyCiTi's own coordinates for MyCiTi's own stops.

    PYTHONPATH=src python -m myciti_scraper.official_positions          # report
    PYTHONPATH=src python -m myciti_scraper.official_positions --fix    # and write

myciti_scraper.positions asks OpenStreetMap where these stops are, which works for the
ones somebody has mapped and leaves the rest with nothing: 43 of 522 had no position at
all, so no journey could start or end at them and they appeared nowhere on a map.

The City publishes the lot. The route and stop map at

    https://www.myciti.org.za/en/routes-stops/route-stop-station-map/

carries every stop and station with its coordinates in the page itself, which is the
operator's own answer rather than a volunteer's - and all 43 of the missing ones are in
it, by name.

Golden Arrow has no equivalent. Its timetables print a street name and nothing else, which
is why placing those stops needs a geocoder and a route to check the answer against. This
module exists because MyCiTi does not have that problem and should not be treated as
though it does.

Every candidate is still checked before it is written: inside Cape Town, and not so far
from the stops either side of it on a route that it would bend the line. A published
coordinate is evidence, not proof.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import urllib.request

from . import db_compat as db

MAP_URL = "https://www.myciti.org.za/en/routes-stops/route-stop-station-map/"
UA = {"User-Agent": "Commuttr/1.0 (+https://commuttr.co.za)"}

# The stop objects the page carries, as it writes them.
STOP = re.compile(
    r'\{"id":"(?P<id>[A-Z0-9_\-]+)","name":"(?P<name>[^"]+)",'
    r'"latitude":(?P<lat>-?\d+\.?\d*),"longitude":(?P<lon>\d+\.?\d*),'
    r'"station":(?P<station>true|false)'
)

# Cape Town and the bit of the West Coast MyCiTi reaches. A coordinate outside this is a
# parse gone wrong, not a stop.
BOUNDS = (-34.40, -33.40, 18.20, 19.10)  # lat min, lat max, lon min, lon max

# How far a published position may sit from where the route says the stop is.
#
# Not a tight number on purpose: it is here to catch a name collision that put the stop in
# another town, not to second-guess the operator about which side of a road its own stop
# is on.
MAX_OFF_ROUTE_KM = 3.0

# A position we already hold that disagrees with the operator's by more than this is
# reported. OpenStreetMap and the City often differ by a few metres across a street.
DISAGREE_KM = 0.25


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    inner = (math.sin(lat1) * math.sin(lat2)
             + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return 6371.0 * math.acos(max(-1.0, min(1.0, inner)))


def published() -> dict[str, tuple[float, float, bool]]:
    """Every stop the City's map carries, keyed by upper-case name."""
    request = urllib.request.Request(MAP_URL, headers=UA)
    with urllib.request.urlopen(request, timeout=120) as response:
        page = response.read().decode("utf-8", "ignore")

    out: dict[str, tuple[float, float, bool]] = {}
    for m in STOP.finditer(page):
        lat, lon = float(m.group("lat")), float(m.group("lon"))
        if not (BOUNDS[0] <= lat <= BOUNDS[1] and BOUNDS[2] <= lon <= BOUNDS[3]):
            continue
        out.setdefault(m.group("name").strip().upper(), (lat, lon, m.group("station") == "true"))
    return out


def _neighbours(cur) -> dict[int, list[tuple[float, float]]]:
    """Where the stops either side of each MyCiTi stop are, across every route."""
    cur.execute(
        """
        SELECT ss.stop_id, other.lat, other.lon
        FROM schedule_stop ss
        JOIN schedule sc      ON sc.id = ss.schedule_id
        JOIN timetable t      ON t.id = sc.timetable_id
        JOIN route r          ON r.id = t.route_id
        JOIN operator o       ON o.id = r.operator_id AND o.code = 'myciti'
        JOIN schedule_stop ns ON ns.schedule_id = ss.schedule_id
                             AND abs(ns.stop_sequence - ss.stop_sequence) = 1
        JOIN stop other       ON other.id = ns.stop_id AND other.lat IS NOT NULL
        """
    )
    near: dict[int, list[tuple[float, float]]] = {}
    for stop_id, lat, lon in cur.fetchall():
        near.setdefault(stop_id, []).append((lat, lon))
    return near


def forget_paths(cur, stop_ids) -> int:
    """
    Throw away the road paths drawn to a stop that has just moved.

    leg_geometry is built FROM stop positions, so a path to the old place is a line to
    somewhere the bus does not go - and gabs_scraper.geometry only fetches legs it has
    nothing for, so a stale path would survive every future run. Deleting them here is
    what makes the next geometry run redraw them.
    """
    ids = [int(i) for i in stop_ids]
    if not ids:
        return 0
    cur.execute(
        "DELETE FROM leg_geometry WHERE from_stop_id = ANY(%s) OR to_stop_id = ANY(%s)",
        (ids, ids),
    )
    return cur.rowcount


def run(fix: bool = False) -> dict:
    official = published()
    conn = db.connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.id, s.name, s.lat, s.lon
        FROM stop s JOIN operator o ON o.id = s.operator_id AND o.code = 'myciti'
        ORDER BY s.name
        """
    )
    stops = cur.fetchall()
    near = _neighbours(cur)

    placed, refused, disagree, unknown = [], [], [], []
    for stop_id, name, lat, lon in stops:
        found = official.get((name or "").strip().upper())
        if not found:
            if lat is None:
                unknown.append(name)
            continue
        new = (found[0], found[1])

        # The route it runs on has to recognise the place.
        others = near.get(stop_id, [])
        off = min((km(new, o) for o in others), default=0.0)
        if others and off > MAX_OFF_ROUTE_KM:
            refused.append((name, off))
            continue

        if lat is None:
            placed.append((stop_id, name, new))
        elif km((lat, lon), new) > DISAGREE_KM:
            disagree.append((stop_id, name, km((lat, lon), new), new))

    if fix:
        forget_paths(cur, [p[0] for p in placed] + [d[0] for d in disagree])
        for stop_id, _name, (lat, lon) in placed:
            cur.execute(
                "UPDATE stop SET lat=%s, lon=%s, geocode_source='myciti:official' WHERE id=%s",
                (lat, lon, stop_id),
            )
        for stop_id, _name, _apart, (lat, lon) in disagree:
            cur.execute(
                "UPDATE stop SET lat=%s, lon=%s, geocode_source='myciti:official' WHERE id=%s",
                (lat, lon, stop_id),
            )
        conn.commit()
    cur.close()
    conn.close()

    print(f"{len(official)} stops published by the City, {len(stops)} held here")
    print(f"  {len(placed)} had no position and now do" if fix
          else f"  {len(placed)} have no position and are on the City's map")
    print(f"  {len(disagree)} disagreed with the City by more than {DISAGREE_KM * 1000:.0f}m"
          f"{' and were moved to it' if fix else ''}")
    for name, off in refused:
        print(f"  refused {name}: the City's position is {off:.1f} km from its own route")
    if unknown:
        print(f"  {len(unknown)} have no position and are not on the map: "
              + ", ".join(unknown[:10]))
    if not fix and (placed or disagree):
        print("\nrun with --fix to write these")
    return {"published": len(official), "placed": len(placed),
            "disagree": len(disagree), "refused": len(refused), "unknown": len(unknown)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Place MyCiTi stops from the City's own map")
    ap.add_argument("--fix", action="store_true", help="write the positions")
    run(fix=ap.parse_args().fix)


if __name__ == "__main__":
    main()
