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


def squash(name: str) -> str:
    """
    A name with the spaces and punctuation taken out.

    Nobody types a place the way an operator prints it. "buhrein" is one word to the
    person searching and two to Golden Arrow - BUH REIN - and the search matches on a
    substring, so "buhrein" found nothing while "buh" found it. The squashed spelling is
    kept as an alias, which the search already looks at, so this costs no query time.
    """
    return "".join(c for c in name.lower() if c.isalnum())


# The same thing in SQL, for the rows built straight from the stop table. Spaces, the
# apostrophe in SIMON'S TOWN, full stops in A.D.E. and the hyphens in double-barrelled
# street names.
SQUASH_SQL = ("replace(replace(replace(replace(lower({0}), ' ', ''), "
              "chr(39), ''), '.', ''), '-', '')")

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
        # "mitchellsplain", "saltriver", "capegate" - the way a rider types them.
        alts.append(squash(name))
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


def mark_served(cur) -> dict[str, int]:
    """
    Which operators reach each place, recomputed from the stops.

    Asked per OPERATOR, not per kind. The kind columns were added so that choosing Metro
    Rail would not offer Hout Bay, whose nearest station is forty kilometres away - and a
    second bus operator breaks them in exactly the way they were built to prevent. A place
    in Atlantis that only MyCiTi reaches is served_bus, so the Golden Arrow chip offers it
    and then finds no journey; and the other way round for the whole Golden Arrow network.

    The kind columns are kept and derived from this, because /api/areas and the loaders
    still read them, and because "is there a bus near here at all" remains a real question
    even once the answer no longer says whose.
    """
    cur.execute("DELETE FROM area_service")
    cur.execute(
        """
        INSERT INTO area_service (area_id, operator_id)
        SELECT DISTINCT a.id, s.operator_id
        FROM area a
        JOIN stop s ON s.lat IS NOT NULL
          AND 6371000 * acos(least(1,
                cos(radians(a.lat)) * cos(radians(s.lat))
                  * cos(radians(s.lon) - radians(a.lon))
              + sin(radians(a.lat)) * sin(radians(s.lat)))) <= %s
        ON CONFLICT DO NOTHING
        """,
        (WALK_M,),
    )
    written = cur.rowcount
    cur.execute(
        """
        UPDATE area a SET
            served_bus = EXISTS (SELECT 1 FROM area_service x
                                 JOIN operator o ON o.id = x.operator_id
                                 WHERE x.area_id = a.id AND o.kind = 'bus'),
            served_train = EXISTS (SELECT 1 FROM area_service x
                                   JOIN operator o ON o.id = x.operator_id
                                   WHERE x.area_id = a.id AND o.kind = 'train'),
            served = EXISTS (SELECT 1 FROM area_service x WHERE x.area_id = a.id)
        """
    )
    cur.execute(
        """
        SELECT o.code, count(*) FROM area_service x
        JOIN operator o ON o.id = x.operator_id GROUP BY o.code ORDER BY 2 DESC
        """
    )
    by_operator = dict(cur.fetchall())
    by_operator["_rows"] = written
    return by_operator


def add_stop_names(cur) -> list[str]:
    """
    Every name the operators print that OSM does not have as a place.

    The search box offers areas and nothing else, which is what was asked for: one entry
    per place, rather than the same suburb listed three times over as a bus, a train and a
    place. What it cost was every name that only the operators use. Mukhethwa typed
    "buhrein" and got nothing - BUH REIN is a bus stop in Kraaifontein serving a
    development of that name, and no place node in OSM carries it. 416 of the 584 stop
    names in this database were unreachable from the search box the same way, ADDERLEY
    STR and AKASIA PARK station among them.

    The rule was geographic before - add a stop only where no mapped place lies within
    walking distance - which kept the list short and answered the wrong question. Whether
    a rider can find a name is not about what else is nearby: Kraaifontein is 1.5km from
    BUH REIN and does not help somebody who typed BUH REIN.

    So the test is the NAME. A stop whose name is already a place adds nothing and is
    skipped, which is what keeps this from undoing the single-entry rule; a stop whose
    name appears nowhere becomes a place, once, carrying whichever networks call there.

    One row per name, not per stop, because CAPE TOWN is a station and a bus terminus and
    a rider typing it means the place. It takes the position of the lowest-numbered stop
    of that name rather than averaging, which would put the entry between them and at
    neither.
    """
    cur.execute(
        """
        WITH named AS (
            SELECT s.name,
                   min(s.id)                  AS pick,
                   bool_or(o.kind = 'bus')    AS by_bus,
                   bool_or(o.kind = 'train')  AS by_train
            FROM stop s
            JOIN operator o ON o.id = s.operator_id
            WHERE s.lat IS NOT NULL
              -- Same name AND same place. Both halves are needed.
              --
              -- The spelling is compared with the punctuation taken out, because the two
              -- sources write one place differently: OSM has Simon's Town and Mitchells
              -- Plain where Golden Arrow prints SIMONSTOWN and MITCHELL'S PLAIN, and
              -- matched literally each pair survives as two entries of one place.
              --
              -- But a shared name is not a shared place. The village of Kalbaskraal sits
              -- 16.7km from the bus stop called KALBASKRAAL, and dropping the stop on the
              -- strength of the name left the nearest place to it 10.4km away - so a
              -- rider typing Kalbaskraal was sent somewhere no service reaches, and the
              -- stop could no longer be asked for at all.
              AND NOT EXISTS (
                SELECT 1 FROM area a
                WHERE a.kind <> 'stop' AND SQUASHED_AREA = SQUASHED_STOP
                  AND 6371000 * acos(least(1,
                        cos(radians(a.lat)) * cos(radians(s.lat))
                          * cos(radians(s.lon) - radians(a.lon))
                      + sin(radians(a.lat)) * sin(radians(s.lat)))) <= WALKING)
            GROUP BY s.name
        )
        INSERT INTO area (name, kind, lat, lon, full_name, aliases, served,
                          served_bus, served_train, osm_id)
        SELECT n.name, 'stop', s.lat, s.lon,
               n.name || ', Cape Town, South Africa',
               SQUASHED_NAME, TRUE,
               n.by_bus, n.by_train, -n.pick
        FROM named n
        JOIN stop s ON s.id = n.pick
        ON CONFLICT (osm_id) DO UPDATE SET
            name = EXCLUDED.name, lat = EXCLUDED.lat, lon = EXCLUDED.lon,
            aliases = EXCLUDED.aliases,
            served_bus = EXCLUDED.served_bus, served_train = EXCLUDED.served_train
        RETURNING name
        """.replace("SQUASHED_NAME", SQUASH_SQL.format("n.name"))
             .replace("SQUASHED_AREA", SQUASH_SQL.format("a.name"))
             .replace("SQUASHED_STOP", SQUASH_SQL.format("s.name"))
             .replace("WALKING", str(WALK_M))
    )
    return [r[0] for r in cur.fetchall()]


def drop_stale_stop_names(cur) -> int:
    """
    Stop-derived entries whose name has since been mapped as a real place.

    Left behind they are a second copy of the same suburb, which is the duplication the
    single-entry rule exists to prevent.
    """
    cur.execute(
        """
        DELETE FROM area a
        WHERE a.kind = 'stop'
          AND EXISTS (SELECT 1 FROM area b
                      WHERE b.kind <> 'stop' AND SQUASHED_B = SQUASHED_A
                        AND 6371000 * acos(least(1,
                              cos(radians(b.lat)) * cos(radians(a.lat))
                                * cos(radians(a.lon) - radians(b.lon))
                            + sin(radians(b.lat)) * sin(radians(a.lat)))) <= WALKING)
        """.replace("SQUASHED_B", SQUASH_SQL.format("b.name"))
             .replace("SQUASHED_A", SQUASH_SQL.format("a.name"))
             .replace("WALKING", str(WALK_M))
    )
    return cur.rowcount


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

        stale = drop_stale_stop_names(cur)
        added = add_stop_names(cur)
        conn.commit()
        if stale:
            print(f"{stale} stop entries dropped, now mapped as places in their own right")
        if added:
            print(f"{len(added)} operator names added as places, having none mapped "
                  f"under that name")
            print("  e.g. " + ", ".join(sorted(added)[:8]))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
