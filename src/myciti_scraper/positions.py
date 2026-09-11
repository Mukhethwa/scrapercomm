"""Where MyCiTi's stops are.

    PYTHONPATH=src python -m myciti_scraper.positions --dry-run
    PYTHONPATH=src python -m myciti_scraper.positions

The timetables give names and times and no coordinates, and without coordinates a stop
might as well not exist: the planner walks a rider from a place to whatever is near them,
and nothing is near a stop that is nowhere.

NOT GEOCODED BY NAME. Half of these are street names - Azalea, Begonia, Bittern, Curlew -
and asking a geocoder for "Azalea, Cape Town" returns a street somewhere, which is the
kind of answer that looks right in a table and puts a bus stop in the wrong suburb. That
mistake has been made in this repository before: nineteen Golden Arrow stops were
re-geocoded with their town as context and landed on the town centroid, scoring a perfect
detour of zero and reading as a triumph.

So the positions come from OpenStreetMap, where MyCiTi's stations are mapped as objects
rather than guessed at from their names, and anything not found there is INTERPOLATED
between its neighbours on the same route using the published times. A stop three minutes
after one that is placed and two minutes before another is somewhere between them; that
is not precise and it is not invented either, and it is recorded as its own source so it
can be told apart from the ones that are known.

Names alone are not trusted where they are ambiguous. "Gardens" is a MyCiTi station, a
suburb and several other things, so a name with more than one candidate is settled by
which candidate is nearest the rest of that route.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import statistics
import urllib.parse
import urllib.request

from . import db_compat as db

OVERPASS = "https://overpass-api.de/api/interpreter"
BBOX = (-34.45, 18.28, -33.40, 19.12)
OPERATOR_CODE = "myciti"

# How far an interpolated stop may sit from the placed neighbours it was put between.
#
# Two placed stops eight kilometres apart say almost nothing about where a stop between
# them is, and a guess that loose is worse than no answer: the planner would offer a
# rider a walk to somewhere the bus does not go. Three kilometres is about the longest
# gap on these routes that still pins a stop inside the right suburb.
MAX_SPAN_M = 3000.0


def squash(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    inner = (math.sin(lat1) * math.sin(lat2)
             + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return 6371000 * math.acos(max(-1.0, min(1.0, inner)))


def _overpass(query: str) -> list[dict]:
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS, data=data,
                                 headers={"User-Agent": "commuttr-myciti"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r).get("elements", [])


# Where the answer is kept between runs.
#
# Overpass is a free service run on donated hardware and it says no when asked too often -
# this step was written against six queries in twenty minutes and the sixth came back 429.
# The PDFs are cached on disk and so is this; nothing about the position of a bus stop
# changes between one run of a parser and the next.
CACHE = os.path.join("data", "myciti", "osm-stops.json")


def candidates(refresh: bool = False) -> dict[str, list[dict]]:
    """
    Every named public-transport object in the metro, by squashed name.

    Two queries in one. MyCiTi's own stations carry operator or network tags and are
    trusted first; but the busiest of them - Civic Centre and Adderley - carry neither,
    being mapped as bare platforms, so the wider question has to be asked as well or the
    two ends of half the network go missing.
    """
    if not refresh and os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as fh:
            els = json.load(fh)
        return _by_name(els)

    s, w, n, e = BBOX
    els = _overpass(f"""[out:json][timeout:240];
        (
          nwr["public_transport"~"platform|stop_position|station"]["name"]({s},{w},{n},{e});
          nwr["highway"="bus_stop"]["name"]({s},{w},{n},{e});
          nwr["amenity"="bus_station"]["name"]({s},{w},{n},{e});
        );
        out center tags;""")
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(els, fh)
    return _by_name(els)


def _by_name(els: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = collections.defaultdict(list)
    for el in els:
        tags = el.get("tags", {})
        name = (tags.get("name") or "").strip()
        centre = el if "lat" in el else el.get("center") or {}
        if not name or "lat" not in centre:
            continue
        who = f"{tags.get('operator', '')} {tags.get('network', '')}".lower()
        out[squash(name)].append({
            "name": name,
            "lat": float(centre["lat"]),
            "lon": float(centre["lon"]),
            # A MyCiTi tag makes a candidate the obvious one where a name is shared.
            "myciti": "myciti" in who or "cape town irt" in who,
        })
    return out


def _routes(cur) -> dict[int, list[int]]:
    """Which stops share a route, so an ambiguous name can be settled by its neighbours."""
    cur.execute(
        """
        SELECT r.id, ss.stop_id
        FROM route r
        JOIN operator o       ON o.id = r.operator_id AND o.code = %s
        JOIN timetable t      ON t.route_id = r.id
        JOIN schedule sc      ON sc.timetable_id = t.id
        JOIN schedule_stop ss ON ss.schedule_id = sc.id
        """,
        (OPERATOR_CODE,),
    )
    by_route: dict[int, set[int]] = collections.defaultdict(set)
    for route_id, stop_id in cur.fetchall():
        by_route[route_id].add(stop_id)
    return {k: sorted(v) for k, v in by_route.items()}


def _sequences(cur) -> list[list[tuple[int, str | None]]]:
    """Each schedule's stops in order, with the time printed against the first trip."""
    cur.execute(
        """
        SELECT sc.id, ss.stop_sequence, ss.stop_id,
               (SELECT min(st.departure_time) FROM stop_time st
                WHERE st.schedule_stop_id = ss.id AND st.cell_type = 'TIME')
        FROM schedule sc
        JOIN timetable t      ON t.id = sc.timetable_id
        JOIN route r          ON r.id = t.route_id
        JOIN operator o       ON o.id = r.operator_id AND o.code = %s
        JOIN schedule_stop ss ON ss.schedule_id = sc.id
        ORDER BY sc.id, ss.stop_sequence
        """,
        (OPERATOR_CODE,),
    )
    runs: dict[int, list] = collections.defaultdict(list)
    for sched, _seq, stop_id, when in cur.fetchall():
        runs[sched].append((stop_id, str(when) if when else None))
    return list(runs.values())


# The fastest a MyCiTi bus could conceivably be going between two stops.
#
# The trunk routes run on the R27 and the N2 and do reach seventy or eighty; a hundred and
# twenty is not a speed limit, it is an impossibility, and that is the point. This is not
# tuned to catch near misses - it is here to catch a stop that has been put in the wrong
# suburb entirely, where the implied speed comes out in the hundreds or thousands.
IMPOSSIBLE_KMH = 120.0


def implausible(placed: dict[int, tuple[float, float]],
                sequences: list[list[tuple[int, str | None]]]) -> dict[int, float]:
    """
    Stops whose position the timetable says cannot be right, and how fast they imply.

    A name is not a place. All six objects OpenStreetMap calls "Avondale" are in Parow,
    38km from the Atlantis suburb of that name where MyCiTi's route 241 calls - and
    because they agree with each other to within a few hundred metres, every check that
    asks "do the candidates cluster" says yes. This asks the timetable instead: route 241
    reaches Avondale three minutes after leaving Atlantis Station, and no bus covers 38km
    in three minutes.

    Nineteen Golden Arrow stops were once re-geocoded onto their town's centroid and
    scored a perfect detour of zero, which read as a triumph until somebody looked. The
    lesson was that a position has to be checked against something other than the name it
    came from. This is that something.
    """
    speeds: dict[int, list[float]] = collections.defaultdict(list)
    for seq in sequences:
        timed = [(i, sid, _minutes(when)) for i, (sid, when) in enumerate(seq)
                 if sid in placed and _minutes(when) is not None]
        for (_, a, ta), (_, b, tb) in zip(timed, timed[1:]):
            gap = tb - ta
            if gap <= 0:
                continue                       # backwards or simultaneous; says nothing
            km = metres(placed[a], placed[b]) / 1000.0
            kmh = km / (gap / 60.0)
            speeds[a].append(kmh)
            speeds[b].append(kmh)
    # The median, so one odd pairing cannot condemn a stop that is otherwise consistent
    # with every neighbour it has.
    return {sid: statistics.median(v) for sid, v in speeds.items()
            if statistics.median(v) > IMPOSSIBLE_KMH}


def _minutes(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None


def interpolate(placed: dict[int, tuple[float, float]],
                sequences: list[list[tuple[int, str | None]]]) -> dict[int, tuple[float, float]]:
    """
    Stops with no mapped object, put between the placed ones either side of them.

    The fraction comes from the timetable rather than from counting stops: a stop one
    minute after the last placed one and nine before the next is a tenth of the way along,
    and spacing them evenly would put it in the middle of a gap it is nowhere near.

    A stop on several routes can be interpolated several times. The answers are averaged,
    which is the honest thing to do with several estimates of one position and also keeps
    the result from depending on which schedule happened to be read last.
    """
    guesses: dict[int, list[tuple[float, float]]] = collections.defaultdict(list)
    for seq in sequences:
        known = [i for i, (sid, _) in enumerate(seq) if sid in placed]
        if len(known) < 2:
            continue
        for a, b in zip(known, known[1:]):
            if b - a < 2:
                continue                        # nothing between them
            pa, pb = placed[seq[a][0]], placed[seq[b][0]]
            span = metres(pa, pb)
            if span > MAX_SPAN_M:
                continue                        # too far apart to say anything
            ta, tb = _minutes(seq[a][1]), _minutes(seq[b][1])
            for i in range(a + 1, b):
                sid = seq[i][0]
                if sid in placed:
                    continue
                ti = _minutes(seq[i][1])
                if ta is not None and tb is not None and ti is not None and tb > ta:
                    f = max(0.0, min(1.0, (ti - ta) / (tb - ta)))
                else:
                    f = (i - a) / (b - a)       # no usable times; space them evenly
                guesses[sid].append((pa[0] + f * (pb[0] - pa[0]),
                                     pa[1] + f * (pb[1] - pa[1])))
    return {sid: (sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps))
            for sid, ps in guesses.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description="Place every MyCiTi stop on the map")
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    ap.add_argument("--refresh", action="store_true",
                    help="ask Overpass again rather than using the cached answer")
    args = ap.parse_args()

    print("reading the public-transport objects in the metro"
          + (" (asking Overpass)" if args.refresh else " (cached)") + "...", flush=True)
    found = candidates(refresh=args.refresh)
    print(f"  {sum(len(v) for v in found.values())} objects under {len(found)} names\n",
          flush=True)

    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.id, s.name FROM stop s
            JOIN operator o ON o.id = s.operator_id AND o.code = %s
            ORDER BY s.name
            """,
            (OPERATOR_CODE,),
        )
        stops = {sid: name for sid, name in cur.fetchall()}
        by_route = _routes(cur)

        # Pass one: names with one candidate, or with a MyCiTi-tagged one.
        placed: dict[int, tuple[float, float]] = {}
        source: dict[int, str] = {}
        ambiguous: dict[int, list[dict]] = {}
        for sid, name in stops.items():
            hits = found.get(squash(name), [])
            if not hits:
                continue
            tagged = [h for h in hits if h["myciti"]]
            pick = tagged or hits
            if len(pick) == 1 or all(metres((pick[0]["lat"], pick[0]["lon"]),
                                            (h["lat"], h["lon"])) < 400 for h in pick):
                # One object, or several platforms of one station a few metres apart.
                placed[sid] = (sum(h["lat"] for h in pick) / len(pick),
                               sum(h["lon"] for h in pick) / len(pick))
                source[sid] = "osm" if tagged else "osm-untagged"
            else:
                ambiguous[sid] = pick
        print(f"{len(placed)} placed by name, {len(ambiguous)} names with rival candidates")

        # Pass two: a shared name settled by the rest of its route.
        settled = 0
        for sid, hits in ambiguous.items():
            near = [placed[o] for r, members in by_route.items() if sid in members
                    for o in members if o in placed]
            if not near:
                continue
            mid = (sum(p[0] for p in near) / len(near), sum(p[1] for p in near) / len(near))
            best = min(hits, key=lambda h: metres(mid, (h["lat"], h["lon"])))
            placed[sid] = (best["lat"], best["lon"])
            source[sid] = "osm-by-route"
            settled += 1
        print(f"{settled} of those settled by which one is nearest the rest of the route")

        # The timetable's own veto, before anything is built on top of these.
        #
        # Run after the route-based tie-break rather than before it, because a wrong
        # candidate can be the only candidate - Avondale has six and all six are in the
        # wrong town, so there is nothing for "nearest the rest of the route" to choose
        # between and the check has to be able to reject them all.
        sequences = _sequences(cur)
        wrong = implausible(placed, sequences)
        for sid, kmh in sorted(wrong.items(), key=lambda kv: -kv[1]):
            print(f"   rejected {stops[sid]}: its position implies {kmh:,.0f} km/h "
                  f"between it and its neighbours")
            placed.pop(sid, None)
            source.pop(sid, None)
        if wrong:
            print(f"{len(wrong)} placement(s) the timetable rules out")

        # Pass three: the rest, between their neighbours.
        guessed = interpolate(placed, sequences)
        print(f"{len(guessed)} interpolated between placed neighbours")
        for sid, point in guessed.items():
            placed[sid] = point
            source[sid] = "interpolated"

        missing = [stops[s] for s in stops if s not in placed]
        print(f"\n{len(placed)} of {len(stops)} stops placed "
              f"({len(placed) / len(stops) * 100:.0f}%)")
        by_source = collections.Counter(source.values())
        for k, v in by_source.most_common():
            print(f"   {k:<16} {v}")
        if missing:
            print(f"\n{len(missing)} still have no position: "
                  + ", ".join(sorted(missing)[:20]))

        if args.dry_run:
            print("\ndry run: nothing written")
            return

        for sid, (lat, lon) in placed.items():
            cur.execute(
                "UPDATE stop SET lat = %s, lon = %s, geocoded_at = now(), "
                "geocode_source = %s WHERE id = %s",
                (lat, lon, f"myciti:{source[sid]}", sid),
            )
        conn.commit()
        print(f"\n{len(placed)} positions written")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
