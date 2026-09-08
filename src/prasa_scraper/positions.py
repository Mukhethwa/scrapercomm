"""Stations that are on the map in the wrong place.

    PYTHONPATH=src python -m prasa_scraper.positions          # report
    PYTHONPATH=src python -m prasa_scraper.positions --fix    # and forget the bad ones

A station with no coordinates draws no pin, and the app is built for that: a journey is
planned by stop id, so STEENBERG to CAPE TOWN works whether or not we know where Steenberg
is. A station with the WRONG coordinates is a different thing entirely. It draws a line
across the peninsula, it puts itself into "nearest stops" lists for places it is nowhere
near, and every one of those answers looks as confident as a right one.

Metrorail's stations were geocoded through Nominatim, because no Google key was set. It
placed WELLINGTON and MBEKWENI about forty-eight kilometres from the towns they are in,
and STELLENBOSCH twenty-two - all three somewhere in the northern suburbs. Nothing
complained, because a coordinate cannot be self-inconsistent the way a timetable can.

Two checks, because neither covers the other:

    against its namesake  Where a Golden Arrow stop shares the station's name, it was
                          geocoded through Google and is reliable. Far apart means one of
                          them is wrong, and it is not the one Google placed.

    against its line      A station sits among its neighbours on the line. This one only
                          reports, and never clears anything, because it cannot tell which
                          side of a disagreement is wrong - and the first time it ran it
                          had it backwards. DAL JOSAFAT is correctly placed near Paarl and
                          shows as forty-seven kilometres from everything else on its
                          line, because everything else on that stretch is what moved.
                          Clearing the odd one out would have deleted the only good
                          coordinate on the line.

Between them they catch four. PAARL and HUGUENOT are wrong too - both sit in the northern
suburbs, thirty-odd kilometres from Paarl - and neither check finds them: no Golden Arrow
namesake, and they have each other for company, so the line looks consistent around them.

The real fix is a Google key. Every bus stop in this database was placed by Google and not
one of them is wrong like this; the stations were done on Nominatim alone because no key
was set, and this module cleans up after that rather than replacing it.
"""
from __future__ import annotations

import argparse
import math

from . import db_compat as db

# How far apart two readings of one place may be before one of them is wrong.
#
# A station and a bus stop of the same name are rarely on the same corner - Steenberg's
# are three kilometres apart and both are right - so this is set well beyond that, to
# catch a reading in the wrong town rather than one across the road.
NAMESAKE_KM = 6.0

# The longest believable gap between neighbouring stations on a line. The Northern Line
# runs about seventy kilometres over twenty-odd stations and its widest real gap, Paarl to
# Wellington, is thirteen. Twenty-five is comfortably clear of that.
NEIGHBOUR_KM = 25.0


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    inner = (math.sin(lat1) * math.sin(lat2)
             + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return 6371.0 * math.acos(max(-1.0, min(1.0, inner)))


def _namesake_suspects(cur) -> dict[int, str]:
    """Stations far from the Golden Arrow stop of the same name."""
    cur.execute(
        """
        SELECT t.id, t.name, t.lat, t.lon, b.lat, b.lon
        FROM stop t
        JOIN operator ot ON ot.id = t.operator_id AND ot.kind = 'train'
        JOIN stop b      ON upper(regexp_replace(b.name, '[^A-Za-z0-9]', '', 'g'))
                          = upper(regexp_replace(t.name, '[^A-Za-z0-9]', '', 'g'))
        JOIN operator ob ON ob.id = b.operator_id AND ob.kind = 'bus'
        WHERE t.lat IS NOT NULL AND b.lat IS NOT NULL
        """
    )
    out: dict[int, str] = {}
    for sid, name, tlat, tlon, blat, blon in cur.fetchall():
        d = km((tlat, tlon), (blat, blon))
        if d > NAMESAKE_KM:
            out[sid] = f"{name}: {d:.0f} km from the bus stop of the same name"
    return out


def _line_suspects(cur) -> dict[int, str]:
    """Stations far from every neighbour on every line they are on."""
    cur.execute(
        """
        SELECT sc.id, ss.stop_sequence, s.id, s.name, s.lat, s.lon
        FROM schedule sc
        JOIN timetable t  ON t.id = sc.timetable_id
        JOIN route r      ON r.id = t.route_id
        JOIN operator o   ON o.id = r.operator_id AND o.kind = 'train'
        JOIN schedule_stop ss ON ss.schedule_id = sc.id
        JOIN stop s       ON s.id = ss.stop_id
        ORDER BY sc.id, ss.stop_sequence
        """
    )
    lines: dict[int, list[tuple]] = {}
    for sched, seq, sid, name, lat, lon in cur.fetchall():
        lines.setdefault(sched, []).append((seq, sid, name, lat, lon))

    # A station is judged by its closest neighbour anywhere on the line, not by the one
    # next to it: two stations placed wrongly side by side would otherwise vouch for each
    # other, and a terminus has only one neighbour to be judged against.
    worst: dict[int, float] = {}
    names: dict[int, str] = {}
    for stops in lines.values():
        placed = [(sid, name, lat, lon) for _, sid, name, lat, lon in stops if lat is not None]
        if len(placed) < 3:
            continue
        for sid, name, lat, lon in placed:
            others = [km((lat, lon), (o_lat, o_lon))
                      for o_sid, _, o_lat, o_lon in placed if o_sid != sid]
            if not others:
                continue
            nearest = min(others)
            if sid not in worst or nearest < worst[sid]:
                worst[sid] = nearest
            names[sid] = name

    return {sid: f"{names[sid]}: {d:.0f} km from the nearest station on its own line"
            for sid, d in worst.items() if d > NEIGHBOUR_KM}


def main() -> None:
    ap = argparse.ArgumentParser(description="Find stations placed in the wrong place")
    ap.add_argument("--fix", action="store_true",
                    help="clear the coordinates of the stations reported")
    args = ap.parse_args()

    conn = db.connect()
    try:
        with conn.cursor() as cur:
            wrong = _namesake_suspects(cur)
            odd = {sid: why for sid, why in _line_suspects(cur).items()
                   if sid not in wrong}

            if not wrong and not odd:
                print("every located station is where it should be")
                return

            if wrong:
                print(f"{len(wrong)} stations are in the wrong place:")
                for why in sorted(wrong.values()):
                    print(f"  {why}")
            if odd:
                print()
                print(f"{len(odd)} sit oddly on their line. Look before believing "
                      f"it - the odd one out is sometimes the only right one:")
                for why in sorted(odd.values()):
                    print(f"  {why}")

            if not args.fix:
                print()
                print("run with --fix to clear the ones in the wrong place, so the "
                      "map draws nothing rather than something wrong")
                return
            suspects = wrong
            # Cleared rather than corrected. Where a station really is, is a fact about
            # Cape Town, and guessing it from a bus stop nearby would be inventing one.
            # The app plans by stop id, so these stations keep working; they simply stop
            # claiming a position nobody can vouch for.
            cur.execute(
                "UPDATE stop SET lat = NULL, lon = NULL, geocode_source = 'misplaced' "
                "WHERE id = ANY(%s)",
                (list(suspects),),
            )
            conn.commit()
            print(f"\ncleared {len(suspects)}; re-run the geocoder with a Google key to "
                  "place them properly")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
