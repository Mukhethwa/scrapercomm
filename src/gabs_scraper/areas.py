"""Every named place in Cape Town, fetched once and held locally.

    PYTHONPATH=src python -m gabs_scraper.areas --dry-run
    PYTHONPATH=src python -m gabs_scraper.areas

/api/geocode used to ask Nominatim on every pause in typing. That is a request per
keystroke per user against a service whose usage policy is one request a second for the
whole application - fine for one developer, impossible in public. And a rate-limited
Nominatim does not announce itself: it returns nothing, which the app can only report as
"no such place". WOODSTOCK and SALT RIVER vanished from Commuttr that way.

Nominatim also cannot do what a search box most needs. It matches whole words, so "woodst"
finds nothing while the stop list - being local - completes it happily. Two lists in one
menu, behaving differently, with no way for a rider to know which they are typing into.

So the places are fetched once, from a single Overpass query for the place nodes inside
the Cape Town bounding box, and searched locally after that. A few hundred rows, fetched
deliberately, instead of a request per keystroke forever.

Each one is then marked with whether the network actually reaches it, using the same two
questions the planner uses to build anchors - a stop within walking distance, or a road
some service drives nearby. An area nothing serves is a place, not a journey.
"""
from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request

from . import db

OVERPASS = "https://overpass-api.de/api/interpreter"

# Cape Town and surrounds: south, west, north, east.
BBOX = (-34.45, 18.28, -33.40, 19.12)

# The place types that name somewhere people live. Not region or state - "Western Cape" is
# not a journey - and not island or farm.
KINDS = ("city", "town", "borough", "suburb", "quarter", "neighbourhood",
         "village", "hamlet", "locality")

# How far a rider walks to something they can board. The planner's own figure; a place
# nothing comes within this distance of is not somewhere a journey can start.
WALK_M = 2500.0

# Spellings a rider may type that OSM and Golden Arrow do not use. Kept here rather than
# guessed, because a wrong alias silently sends somebody to the wrong township.
ALIASES = {
    "Guguletu": ["gugulethu"],
    "Khayelitsha": ["khayalitsha"],
    "Mitchells Plain": ["mitchell's plain", "mitchells plein"],
    "Athlone": ["athlone industria"],
}


def fetch() -> list[dict]:
    """One Overpass query for every named place in the metro."""
    south, west, north, east = BBOX
    kinds = "|".join(KINDS)
    # node, way AND relation. The first version asked for nodes only and missed every
    # suburb mapped as an outline rather than a point - Kalk Bay, Scarborough, False Bay,
    # Fisantekraal among them, all of which are places a rider names and a bus stops at.
    # "out center" gives a single coordinate for an outline, which is what a search box
    # needs; the exact shape of a suburb is not the question being asked.
    query = (f'[out:json][timeout:120];'
             f'nwr["place"~"^({kinds})$"]({south},{west},{north},{east});'
             f'out center;')
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS, data=data,
                                 headers={"User-Agent": "commuttr-areas"})
    with urllib.request.urlopen(req, timeout=180) as r:
        payload = json.load(r)

    out = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        # A node carries its own position; a way or relation reports a centre instead.
        centre = el if "lat" in el else el.get("center") or {}
        if "lat" not in centre:
            continue
        alts = [a.strip().lower() for a in
                (tags.get("alt_name", "") + ";" + tags.get("old_name", "")).split(";")
                if a.strip()]
        alts += [a.lower() for a in ALIASES.get(name, [])]
        out.append({
            "name": name,
            "kind": tags.get("place", ""),
            "lat": float(centre["lat"]),
            "lon": float(centre["lon"]),
            "full_name": ", ".join(x for x in (name, "Cape Town", "South Africa") if x),
            "aliases": ",".join(sorted(set(alts))),
            # Ids repeat across the three element types, so the type is part of the key.
            "osm_id": int(el["id"]) * 10 + {"node": 1, "way": 2, "relation": 3}.get(
                el.get("type"), 0),
        })
    return out


def served(cur, lat: float, lon: float) -> tuple[bool, bool]:
    """
    Which networks actually reach here - (bus, train).

    Asked per network, not once, because the search box now offers only places and the
    operator chips filter them. Choosing Metro Rail and being offered Hout Bay, which has
    no station within forty kilometres, is the app disagreeing with itself: the place is
    suggested, chosen, and then answers with nothing.

    A stop of that kind within walking distance is the test, which is the same question
    the planner asks before it can build a journey from a point.
    """
    cur.execute(
        """
        SELECT
          EXISTS (SELECT 1 FROM stop s JOIN operator o ON o.id = s.operator_id
                  WHERE o.kind = 'bus' AND s.lat IS NOT NULL
                    AND 6371000 * acos(least(1,
                          cos(radians(s.lat)) * cos(radians(%(lat)s))
                            * cos(radians(%(lon)s) - radians(s.lon))
                        + sin(radians(s.lat)) * sin(radians(%(lat)s)))) <= %(within)s),
          EXISTS (SELECT 1 FROM stop s JOIN operator o ON o.id = s.operator_id
                  WHERE o.kind = 'train' AND s.lat IS NOT NULL
                    AND 6371000 * acos(least(1,
                          cos(radians(s.lat)) * cos(radians(%(lat)s))
                            * cos(radians(%(lon)s) - radians(s.lon))
                        + sin(radians(s.lat)) * sin(radians(%(lat)s)))) <= %(within)s)
        """,
        {"lat": lat, "lon": lon, "within": WALK_M},
    )
    bus, train = cur.fetchone()
    return bool(bus), bool(train)


def add_orphan_stops(cur) -> list[str]:
    """
    Stops that are places nobody mapped.

    The search box offers areas and nothing else now, so a stop with no area near it is a
    destination a rider cannot ask for. Eight are like that even after reading outlines as
    well as points: FALSE BAY, FISANTEKRAAL, KALBASKRAAL, DASSENBERG and a few streets on
    the Mitchells Plain side.

    They are added from the stop itself, which is honest rather than invented - the
    operator prints the name, a service calls there, and the coordinate is the one the app
    already plans with. Their osm_id is the negative stop id, which cannot collide with a
    real one, and their kind says plainly where they came from.
    """
    cur.execute(
        """
        INSERT INTO area (name, kind, lat, lon, full_name, aliases, served,
                          served_bus, served_train, osm_id)
        SELECT s.name, 'stop', s.lat, s.lon,
               s.name || ', Cape Town, South Africa', '', TRUE,
               bool_or(o.kind = 'bus'), bool_or(o.kind = 'train'), -s.id
        FROM stop s
        JOIN operator o ON o.id = s.operator_id
        WHERE s.lat IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM area a
            WHERE a.served AND a.kind <> 'stop'
              AND 6371000 * acos(least(1,
                    cos(radians(a.lat)) * cos(radians(s.lat))
                      * cos(radians(s.lon) - radians(a.lon))
                  + sin(radians(a.lat)) * sin(radians(s.lat)))) <= %s)
        GROUP BY s.id, s.name, s.lat, s.lon
        ON CONFLICT (osm_id) DO UPDATE SET
            lat = EXCLUDED.lat, lon = EXCLUDED.lon,
            served_bus = EXCLUDED.served_bus, served_train = EXCLUDED.served_train
        RETURNING name
        """,
        (WALK_M,),
    )
    return [r[0] for r in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser(description="Load the named places of Cape Town")
    ap.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    args = ap.parse_args()

    print("asking Overpass for every named place in the metro...", flush=True)
    places = fetch()
    print(f"  {len(places)} places\n", flush=True)

    conn = db.connect()
    try:
        cur = conn.cursor()
        kept = dropped = 0
        for p in places:
            p["served_bus"], p["served_train"] = served(cur, p["lat"], p["lon"])
            p["served"] = p["served_bus"] or p["served_train"]
            if p["served"]:
                kept += 1
            else:
                dropped += 1

        by_kind: dict[str, int] = {}
        for p in places:
            if p["served"]:
                by_kind[p["kind"]] = by_kind.get(p["kind"], 0) + 1
        buses = sum(1 for p in places if p["served_bus"])
        trains = sum(1 for p in places if p["served_train"])
        print(f"{kept} are within reach of a service, {dropped} are not")
        print(f"  {buses} reachable by bus, {trains} by train")
        for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
            print(f"  {kind:<16} {n}")

        if args.dry_run:
            print("\ndry run: nothing written")
            return

        for p in places:
            cur.execute(
                """
                INSERT INTO area (name, kind, lat, lon, full_name, aliases, served,
                                  served_bus, served_train, osm_id)
                VALUES (%(name)s, %(kind)s, %(lat)s, %(lon)s, %(full_name)s,
                        %(aliases)s, %(served)s, %(served_bus)s, %(served_train)s,
                        %(osm_id)s)
                ON CONFLICT (osm_id) DO UPDATE SET
                    name = EXCLUDED.name, kind = EXCLUDED.kind,
                    lat = EXCLUDED.lat, lon = EXCLUDED.lon,
                    full_name = EXCLUDED.full_name, aliases = EXCLUDED.aliases,
                    served = EXCLUDED.served, served_bus = EXCLUDED.served_bus,
                    served_train = EXCLUDED.served_train, scraped_at = now()
                """,
                p,
            )
        conn.commit()
        print(f"\n{len(places)} places stored")

        added = add_orphan_stops(cur)
        conn.commit()
        if added:
            print(f"{len(added)} stops added as places, having none mapped near them: "
                  + ", ".join(sorted(added)))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
