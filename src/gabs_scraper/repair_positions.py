"""Put misplaced bus stops back on the road their route drives.

    PYTHONPATH=src python -m gabs_scraper.repair_positions --dry-run
    PYTHONPATH=src python -m gabs_scraper.repair_positions

gabs_scraper.stop_positions finds them and deliberately stops there, because a stop judged
by its neighbours is judged by evidence that could itself be wrong. This module is the
repair, and it only acts where a better coordinate can be *demonstrated* - not where one
merely looks plausible.

The fault is always the same. Golden Arrow prints a street name and the geocoder was asked
for it against the whole of Cape Town, so "CLUVER STR" - a street in Stellenbosch, on no
route but CAPE TOWN - STELLENBOSCH - came back as a Cluver in the CBD. The name was never
ambiguous to a person reading the timetable; it was ambiguous to a geocoder that was not
told which town.

So the stop's own route is the context, in two forms, strongest first:

    where its neighbours are   The stops either side of it are somewhere. Search the name
                               bounded to a box around them and a street of that name
                               inside that box is almost certainly the one meant. This
                               uses the route's own geometry rather than any guess.

    which towns it runs to     Route names are endpoints - "CAPE TOWN-STELLENBOSCH" - so
                               the name plus each of those towns is worth asking.

Every candidate is then MEASURED, by the same detour the finder uses: how much doubling
back does this position force on the routes this stop serves? One is accepted if it gets
under the threshold, or if it removes most of the error - KAPTEINSKLIP STN sits 48.5 km off
its route and Google places it 11.5 km off, and three quarters of the disagreement gone is
evidence in a way that a few percent is not. What remains there is its neighbours, not it.
That second door is deliberately narrow: ESCOM VILLAGE improves 44.0 to 42.1 and stays
refused, which is right.

Where nothing qualifies, the stop is left exactly as it was and reported - a wrong
coordinate is bad, and replacing it with a differently wrong one that happens to score
better is worse, because it looks fixed.

It runs in passes, because the evidence improves as it works. CLUVER STR cannot be judged
on the first pass: its neighbours on CAPE TOWN - STELLENBOSCH are MERRIMAN RD and BIRD STR,
which are themselves in the wrong place, so the correct Stellenbosch position scores worse
than the wrong CBD one and is rightly refused. Repair BIRD STR and the ground under CLUVER
STR firms up. Each pass therefore re-measures from scratch, and it stops when a pass
changes nothing.

Two sources, because they fail differently. Nominatim is free and is asked at the one
request a second its usage policy sets; it matches names literally, so it cannot find
BLUE ROUTE CENTRE (the mall is mapped as Blue Route Mall) or DALJOSAFAT STN (it is Dal
Josafat). Google reads a name the way a person would and finds both, at a cost per
request. Neither is trusted on the strength of having answered: every candidate from
either is measured against the route before it is allowed to replace anything.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import time
import urllib.parse
import urllib.request

from . import db
from .stop_positions import LIMIT_KM, km, routes_of

NOMINATIM = "https://nominatim.openstreetmap.org/search"
GOOGLE = "https://maps.googleapis.com/maps/api/geocode/json"

# Nominatim's usage policy is one request a second. Google bills per request and does not
# need the wait, but a small one costs almost nothing and keeps a bug from becoming a bill.
PAUSE_NOMINATIM_S = 1.1
PAUSE_GOOGLE_S = 0.12

# Golden Arrow abbreviates; a geocoder does not.
_WORDS = {
    "STR": "Street", "RD": "Road", "AVE": "Avenue", "AV": "Avenue", "DRV": "Drive",
    "DR": "Drive", "CLSE": "Close", "CRES": "Crescent", "LN": "Lane", "SQ": "Square",
    "STN": "Station", "SCH": "School", "IND": "Industrial", "TERM": "Terminus",
    "CNR": "Corner", "PK": "Park", "HGTS": "Heights", "BLVD": "Boulevard",
}

# How far around the neighbouring stops to look. Wide enough for a stop that genuinely
# sits off the straight line between them, narrow enough that a same-named street in the
# next town over cannot creep in.
BOX_PAD_DEG = 0.06


def expand(name: str) -> str:
    """"CLUVER STR" -> "Cluver Street". """
    out = []
    for word in name.split():
        out.append(_WORDS.get(word.upper(), word.title()))
    return " ".join(out)


def geocode_nominatim(query: str,
                      box: tuple[float, float, float, float] | None) -> tuple[float, float] | None:
    """One Nominatim lookup, optionally confined to a box, or None."""
    params = {"q": query, "format": "json", "limit": 1, "countrycodes": "za"}
    if box:
        south, west, north, east = box
        params["viewbox"] = f"{west},{north},{east},{south}"
        params["bounded"] = 1
    url = f"{NOMINATIM}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "commuttr-stop-repair"})
    try:
        hits = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception:      # noqa: BLE001 - one stop must not end the run
        return None
    return (float(hits[0]["lat"]), float(hits[0]["lon"])) if hits else None


def geocode_google(query: str, box: tuple[float, float, float, float] | None,
                   key: str) -> tuple[float, float] | None:
    """
    One Google Geocoding lookup, biased toward the stop's own neighbourhood.

    Google reads a name the way a person would. It knows BLUE ROUTE CENTRE is the Blue
    Route Mall and DALJOSAFAT is Dal Josafat, which is the whole reason for asking it:
    those are not misspellings a rule can repair, they are the same place under the name
    a local uses.

    `bounds` is a bias rather than a filter - unlike Nominatim's bounded viewbox, Google
    will still answer from outside it. That is fine here and would not be elsewhere,
    because nothing is accepted on the strength of having been found: every candidate is
    still measured against the route before it is allowed to replace anything.
    """
    params = {"address": query, "key": key, "components": "country:ZA", "region": "za"}
    if box:
        south, west, north, east = box
        params["bounds"] = f"{south},{west}|{north},{east}"
    url = f"{GOOGLE}?{urllib.parse.urlencode(params)}"
    try:
        js = json.load(urllib.request.urlopen(url, timeout=30))
    except Exception:      # noqa: BLE001
        return None
    status = js.get("status")
    if status == "OK" and js.get("results"):
        loc = js["results"][0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])
    if status in ("REQUEST_DENIED", "OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"):
        # Worth stopping for: every later stop would fail the same way, silently, and the
        # run would report "nothing found" for a network problem.
        raise RuntimeError(f"Google refused the request: {status} "
                           f"{js.get('error_message', '')}")
    return None


def neighbourhoods(conn) -> dict[int, list[tuple]]:
    """For every bus stop, the (before, after) coordinate pairs it sits between."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ss.schedule_id, ss.stop_sequence, s.id, s.lat, s.lon
        FROM schedule_stop ss
        JOIN stop s     ON s.id = ss.stop_id
        JOIN operator o ON o.id = s.operator_id AND o.kind = 'bus'
        ORDER BY ss.schedule_id, ss.stop_sequence
        """
    )
    scheds: dict[int, list] = collections.defaultdict(list)
    for sched, _seq, sid, lat, lon in cur.fetchall():
        scheds[sched].append((sid, lat, lon))

    pairs: dict[int, list[tuple]] = collections.defaultdict(list)
    for stops in scheds.values():
        for i in range(1, len(stops) - 1):
            before, here, after = stops[i - 1], stops[i], stops[i + 1]
            if before[1] is None or after[1] is None:
                continue
            pairs[here[0]].append(((before[1], before[2]), (after[1], after[2])))
    return pairs


def detour_of(point: tuple[float, float], pairs: list[tuple]) -> float:
    """The least detour this position forces on any route the stop serves."""
    best = float("inf")
    for before, after in pairs:
        extra = km(before, point) + km(point, after) - km(before, after)
        best = min(best, extra)
    return best


def box_around(pairs: list[tuple]) -> tuple[float, float, float, float] | None:
    """A bounding box over every neighbour, padded."""
    lats = [p[0] for pair in pairs for p in pair]
    lons = [p[1] for pair in pairs for p in pair]
    if not lats:
        return None
    return (min(lats) - BOX_PAD_DEG, min(lons) - BOX_PAD_DEG,
            max(lats) + BOX_PAD_DEG, max(lons) + BOX_PAD_DEG)


def towns_of(conn, stop_id: int) -> list[str]:
    """The place names a stop's routes are titled with."""
    seen = []
    for route in routes_of(conn, stop_id, 6):
        for part in route.replace("-", " - ").split(" - "):
            part = part.strip().title()
            if part and part not in seen:
                seen.append(part)
    return seen


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-geocode stops that sit off their route")
    ap.add_argument("--dry-run", action="store_true", help="ask and measure, write nothing")
    ap.add_argument("--limit-km", type=float, default=LIMIT_KM)
    ap.add_argument("--only", type=int, help="repair just this stop id")
    ap.add_argument("--improve-frac", type=float, default=0.6,
                    help="accept a candidate still above the threshold if it removes at "
                         "least this fraction of the detour")
    ap.add_argument("--improve-km", type=float, default=10.0,
                    help="and at least this many kilometres of it")
    ap.add_argument("--provider", choices=("auto", "nominatim", "google"), default="auto",
                    help="auto uses Google when GOOGLE_MAPS_API_KEY is set, else Nominatim")
    ap.add_argument("--passes", type=int, default=4,
                    help="re-measure and try again; a stop whose neighbours were repaired "
                         "can become judgeable on a later pass")
    args = ap.parse_args()

    key = os.environ.get("GOOGLE_MAPS_API_KEY") or None
    provider = args.provider
    if provider == "auto":
        provider = "google" if key else "nominatim"
    if provider == "google" and not key:
        raise SystemExit("--provider google needs GOOGLE_MAPS_API_KEY in the environment")
    args.provider_resolved = provider
    args.key = key
    print(f"asking {provider}")
    print()

    conn = db.connect()
    try:
        # A dry run writes nothing, so the ground never firms up and a second pass would
        # only ask Nominatim the same questions and get the same answers.
        passes = 1 if args.dry_run else args.passes
        total = 0
        for attempt in range(1, passes + 1):
            print(f"=== pass {attempt} ===")
            moved = one_pass(conn, args)
            total += moved
            if moved == 0:
                break
        print(f"\n{total} stops repaired in all")
        if total and not args.dry_run:
            print("\nleg_geometry is built from these coordinates and is now stale for the "
                  "repaired stops.\nRun: PYTHONPATH=src python -m gabs_scraper.geometry "
                  "--provider osrm")
    finally:
        conn.close()


def one_pass(conn, args) -> int:
    """One measure-and-repair sweep over every stop still off its route."""
    try:
        cur = conn.cursor()
        pairs = neighbourhoods(conn)
        cur.execute(
            """
            SELECT s.id, s.name, s.lat, s.lon
            FROM stop s JOIN operator o ON o.id = s.operator_id AND o.kind = 'bus'
            WHERE s.lat IS NOT NULL
            """
        )
        stops = {sid: (name, float(lat), float(lon)) for sid, name, lat, lon in cur.fetchall()}

        targets = []
        for sid, (name, lat, lon) in stops.items():
            if args.only and sid != args.only:
                continue
            if sid not in pairs:
                continue
            now = detour_of((lat, lon), pairs[sid])
            if now > args.limit_km:
                targets.append((now, sid, name, lat, lon))
        targets.sort(reverse=True)

        print(f"{len(targets)} stops sit more than {args.limit_km:.0f} km off their route\n")
        fixed = unfixed = 0
        for now, sid, name, lat, lon in targets:
            box = box_around(pairs[sid])
            tried: list[tuple[float, tuple[float, float], str]] = []

            # Strongest first: the name, confined to where its neighbours are.
            queries = [(expand(name) + ", South Africa", box)]
            # Then the name in each town its routes are named for.
            queries += [(f"{expand(name)}, {town}, South Africa", None)
                        for town in towns_of(conn, sid)]

            for query, bounds in queries:
                if args.provider_resolved == "google":
                    found = geocode_google(query, bounds, args.key)
                    time.sleep(PAUSE_GOOGLE_S)
                else:
                    found = geocode_nominatim(query, bounds)
                    time.sleep(PAUSE_NOMINATIM_S)
                if not found:
                    continue
                score = detour_of(found, pairs[sid])
                tried.append((score, found, query))
                if score <= args.limit_km:
                    break      # good enough; stop asking

            tried.sort(key=lambda t: t[0])
            best_score = tried[0][0] if tried else float("inf")

            # Good enough outright, or so much better that it cannot be coincidence.
            #
            # The threshold alone was too strict once the stops around a candidate were
            # themselves still wrong. KAPTEINSKLIP STN sits 48.5 km off its route and
            # Google places it 11.5 km off - three quarters of the disagreement gone, and
            # refused for missing the bar by a kilometre and a half. What remains there is
            # its neighbours, not it.
            #
            # A candidate that removes most of the error is evidence in a way that one
            # shaving a few percent is not, so the second door is deliberately narrow:
            # ESCOM VILLAGE improves 44.0 to 42.1 and stays refused, which is right.
            good = best_score <= args.limit_km
            decisive = (best_score < now * (1 - args.improve_frac)
                        and now - best_score >= args.improve_km)
            if tried and (good or decisive) and best_score < now:
                score, (nlat, nlon), query = tried[0]
                how = "" if good else "  (much better, still off)"
                print(f"  FIXED  {name:<22} {now:6.1f} km -> {score:5.1f} km   "
                      f"[{query}]{how}")
                if not args.dry_run:
                    cur.execute(
                        "UPDATE stop SET lat=%s, lon=%s, geocode_source='route-context' "
                        "WHERE id=%s",
                        (nlat, nlon, sid),
                    )
                    conn.commit()
                fixed += 1
            else:
                best = f"{tried[0][0]:.1f} km" if tried else "nothing found"
                print(f"  kept   {name:<22} {now:6.1f} km   best candidate {best}")
                unfixed += 1

        print(f"  -- {fixed} repaired, {unfixed} left alone")
        return fixed
    finally:
        pass


if __name__ == "__main__":
    main()
