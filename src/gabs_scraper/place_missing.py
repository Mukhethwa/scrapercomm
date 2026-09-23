"""Golden Arrow stops with no position at all, placed from where their route runs.

    PYTHONPATH=src python -m gabs_scraper.place_missing          # report
    PYTHONPATH=src python -m gabs_scraper.place_missing --fix    # and write

Five stops have never had a coordinate, and one of them, TOWN CENTRE, is on 1,097
schedules. A stop with no position is not fatal - a journey is planned by stop id, so
trips through it work - but it can anchor no leg geometry, appears in no "nearest stops"
list, and draws nothing on a map. For an interchange the size of Mitchells Plain Town
Centre that is a real hole.

They have no position because the geocoder was asked for a bare name against the whole
city and refused to answer, or answered with Cape Town itself and was rightly rejected
(see geocode.is_the_city_itself, written after six stops landed in the CBD).

The route is the context that was missing. TOWN CENTRE sits between Beacon Valley,
Lentegeur and Rocklands, which are all Mitchells Plain; SPEKENAM sits between Bellville,
Sacks Circle and Kasselsvlei, which are all Bellville. Searching the name inside the box
its neighbours make asks a question with an answer, where searching the metro did not.

Nothing is written on the strength of having been found. A candidate has to sit inside
that box AND not bend the routes it serves, measured the same way gabs_scraper
.stop_positions measures every other stop. Where nothing qualifies the stop keeps no
position, which is the honest state and the one the app already handles.
"""
from __future__ import annotations

import argparse
import math
import os
import time

import requests

from . import db
from .geocode import is_the_city_itself

NOMINATIM = "https://nominatim.openstreetmap.org/search"
GOOGLE = "https://maps.googleapis.com/maps/api/geocode/json"
USER_AGENT = "Commuttr/1.0 (+https://commuttr.co.za)"

# How far outside its neighbours a stop may be looked for. A bus stop sits on the road
# between them, so this is generous rather than tight.
PAD_KM = 3.0

# A neighbour seen on only a couple of runs is usually a long express hop, not where the
# stop is. LEAGUES is next to Colorado Park 18 times and next to Westridge - 20 km away
# in Sea Point - twice. Judging the box by the rare one would put the stop in the wrong
# half of the city.
MIN_NEIGHBOUR_SHARE = 0.15

# What the accepted position has to get the route's detour down to.
MAX_DETOUR_KM = 3.0


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    inner = (math.sin(lat1) * math.sin(lat2)
             + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return 6371.0 * math.acos(max(-1.0, min(1.0, inner)))


def _missing(cur) -> list[tuple[int, str]]:
    cur.execute(
        """
        SELECT s.id, s.name
        FROM stop s JOIN operator o ON o.id = s.operator_id AND o.code = 'gabs'
        WHERE s.lat IS NULL
        ORDER BY s.name
        """
    )
    return cur.fetchall()


def _neighbours(cur, stop_id: int) -> list[tuple[str, float, float, int]]:
    """Placed stops next to this one on a route, and how often they are next to it."""
    cur.execute(
        """
        SELECT other.name, other.lat, other.lon, count(*) AS times
        FROM schedule_stop ss
        JOIN schedule_stop ns ON ns.schedule_id = ss.schedule_id
                             AND abs(ns.stop_sequence - ss.stop_sequence) = 1
        JOIN stop other ON other.id = ns.stop_id AND other.lat IS NOT NULL
        WHERE ss.stop_id = %s
        GROUP BY other.name, other.lat, other.lon
        ORDER BY times DESC
        """,
        (stop_id,),
    )
    return cur.fetchall()


def _search(session, name: str, box, key: str | None):
    """The name inside the box, from Google where a key is set and Nominatim otherwise."""
    lat_min, lat_max, lon_min, lon_max = box
    if key:
        r = session.get(GOOGLE, params={
            "address": f"{name}, Cape Town, South Africa",
            "bounds": f"{lat_min},{lon_min}|{lat_max},{lon_max}",
            "region": "za",
            "key": key,
        }, timeout=30)
        r.raise_for_status()
        for hit in r.json().get("results", [])[:3]:
            if is_the_city_itself(name, hit.get("formatted_address"), hit.get("types")):
                continue
            loc = hit["geometry"]["location"]
            yield float(loc["lat"]), float(loc["lng"]), hit.get("formatted_address", "")
        return

    r = session.get(NOMINATIM, params={
        "q": name,
        "format": "json",
        "limit": 3,
        "countrycodes": "za",
        "viewbox": f"{lon_min:.5f},{lat_max:.5f},{lon_max:.5f},{lat_min:.5f}",
        "bounded": 1,
    }, timeout=30)
    r.raise_for_status()
    for hit in r.json():
        if is_the_city_itself(name, hit.get("display_name"), [hit.get("type")]):
            continue
        yield float(hit["lat"]), float(hit["lon"]), hit.get("display_name", "")


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
    key = os.environ.get("GOOGLE_MAPS_API_KEY") or None
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    conn = db.connect()
    cur = conn.cursor()
    missing = _missing(cur)
    placed, refused = [], []

    for stop_id, name in missing:
        near = _neighbours(cur, stop_id)
        if not near:
            refused.append((name, "no placed neighbour to judge by"))
            continue
        total = sum(times for *_rest, times in near)
        core = [(lat, lon) for _n, lat, lon, times in near if times / total >= MIN_NEIGHBOUR_SHARE]
        if not core:
            core = [(near[0][1], near[0][2])]

        pad = PAD_KM / 111.0
        box = (min(p[0] for p in core) - pad, max(p[0] for p in core) + pad,
               min(p[1] for p in core) - pad, max(p[1] for p in core) + pad)

        best = None
        try:
            for lat, lon, label in _search(session, name, box, key):
                if not (box[0] <= lat <= box[1] and box[2] <= lon <= box[3]):
                    continue
                # The same measure the rest of the pipeline uses: how far this position
                # is from the road its own route drives.
                off = min(km((lat, lon), p) for p in core)
                if off <= MAX_DETOUR_KM:
                    best = (lat, lon, label, off)
                    break
        except requests.RequestException as exc:
            refused.append((name, f"the geocoder could not be asked ({exc})"))
            continue
        if not key:
            time.sleep(1.1)  # Nominatim asks for one request a second.

        if best:
            lat, lon, label, off = best
            placed.append((stop_id, name, lat, lon, label, off))
            if fix:
                cur.execute(
                    "UPDATE stop SET lat=%s, lon=%s, geocode_source='route-context' WHERE id=%s",
                    (lat, lon, stop_id),
                )
        else:
            refused.append((name, "nothing found inside the box its route makes"))

    dropped = 0
    if fix:
        dropped = forget_paths(cur, [p[0] for p in placed])
        conn.commit()
    cur.close()
    conn.close()

    print(f"{len(missing)} Golden Arrow stops have no position")
    if dropped:
        print(f"  {dropped} road paths to the old positions dropped, to be redrawn")
    for _id, name, lat, lon, label, off in placed:
        print(f"  {name}: {lat:.4f},{lon:.4f} ({off:.1f} km from its route)  {label[:56]}")
    for name, why in refused:
        print(f"  {name}: left alone - {why}")
    if fix and placed:
        print("\nleg_geometry is built from stop positions, so draw the new legs:\n"
              "  PYTHONPATH=src python -m gabs_scraper.geometry")
    elif placed:
        print("\nrun with --fix to write these")
    return {"missing": len(missing), "placed": len(placed), "refused": len(refused)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Place stops that have no coordinates")
    ap.add_argument("--fix", action="store_true", help="write the positions")
    run(fix=ap.parse_args().fix)


if __name__ == "__main__":
    main()
