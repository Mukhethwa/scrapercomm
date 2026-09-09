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
    query = (f'[out:json][timeout:90];'
             f'node["place"~"^({kinds})$"]({south},{west},{north},{east});'
             f'out body;')
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
        alts = [a.strip().lower() for a in
                (tags.get("alt_name", "") + ";" + tags.get("old_name", "")).split(";")
                if a.strip()]
        alts += [a.lower() for a in ALIASES.get(name, [])]
        out.append({
            "name": name,
            "kind": tags.get("place", ""),
            "lat": float(el["lat"]),
            "lon": float(el["lon"]),
            "full_name": ", ".join(x for x in (name, "Cape Town", "South Africa") if x),
            "aliases": ",".join(sorted(set(alts))),
            "osm_id": int(el["id"]),
        })
    return out


def served(cur, lat: float, lon: float) -> bool:
    """
    Does anything actually go here?

    A stop of either kind within walking distance, or a road some service drives within
    the pin threshold - the same two questions the planner asks before it can build a
    journey from a point. Answered in one statement so this stays a local pass over a few
    hundred rows rather than a few hundred round trips.
    """
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM stop s
            WHERE s.lat IS NOT NULL
              AND 6371000 * acos(least(1,
                    cos(radians(s.lat)) * cos(radians(%s))
                      * cos(radians(%s) - radians(s.lon))
                  + sin(radians(s.lat)) * sin(radians(%s)))) <= %s
        )
        """,
        (lat, lon, lat, WALK_M),
    )
    return bool(cur.fetchone()[0])


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
            p["served"] = served(cur, p["lat"], p["lon"])
            if p["served"]:
                kept += 1
            else:
                dropped += 1

        by_kind: dict[str, int] = {}
        for p in places:
            if p["served"]:
                by_kind[p["kind"]] = by_kind.get(p["kind"], 0) + 1
        print(f"{kept} are within reach of a service, {dropped} are not")
        for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
            print(f"  {kind:<16} {n}")

        if args.dry_run:
            print("\ndry run: nothing written")
            return

        for p in places:
            cur.execute(
                """
                INSERT INTO area (name, kind, lat, lon, full_name, aliases, served, osm_id)
                VALUES (%(name)s, %(kind)s, %(lat)s, %(lon)s, %(full_name)s,
                        %(aliases)s, %(served)s, %(osm_id)s)
                ON CONFLICT (osm_id) DO UPDATE SET
                    name = EXCLUDED.name, kind = EXCLUDED.kind,
                    lat = EXCLUDED.lat, lon = EXCLUDED.lon,
                    full_name = EXCLUDED.full_name, aliases = EXCLUDED.aliases,
                    served = EXCLUDED.served, scraped_at = now()
                """,
                p,
            )
        conn.commit()
        print(f"\n{len(places)} places stored")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
