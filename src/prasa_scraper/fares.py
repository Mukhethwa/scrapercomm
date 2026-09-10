"""What a Metrorail journey costs, from PRASA's published zone structure.

    PYTHONPATH=src python -m prasa_scraper.fares --dry-run
    PYTHONPATH=src python -m prasa_scraper.fares

Trains have had no fare at all until now: the `fare` table is Golden Arrow's zone table and
holds nothing for Metrorail, so every train journey showed no price. PRASA does not price
station to station the way Golden Arrow prices zone to zone. It prices by DISTANCE, in four
bands, and the same four numbers cover the whole network.

    Zone 1     1km to 15km      single R10.00    return R20.00
    Zone 2    16km to 40km      single R12.00    return R24.00
    Zone 3    41km to 60km      single R14.00    return R28.00
    Zone 4    over 60km         single R15.00    return R30.00

Which means a journey can be priced from something we already hold - where the stations
are - rather than from a table nobody publishes per pair.

HOW FAR IS THE JOURNEY. Straight line between the two stations, which is not what PRASA
charges for and is nevertheless the right measure to use here.

Summing along the line was tried first and is wrong, because a loaded schedule is not a
physical path: the Northern Line INBOUND sheet lists KRAAIFONTEIN, BRACKENFELL, STELLENBOSCH,
STRAND, SOMERSET WEST, EERSTE RIVER, BELLVILLE, PAROW in one sequence, crossing between
branches. Adding those hops made Cape Town to Kraaifontein 202km of railway, against a real
30km, and would have charged Zone 4 for a Zone 2 trip.

The straight line understates - rail runs about 1.2x the crow across the journeys that can
be checked - but the bands are 15, 25 and 20km wide, so it lands in the right one anyway.
Checked against eleven published Metrorail distances from Cape Town (Woodstock 2km, Wynberg
14, Bellville 26, Kraaifontein 30, Khayelitsha 35, Simon's Town 40, Strand 50, Paarl 60,
Wellington 72): ALL ELEVEN fall in the same band by straight line as by rail. Where it could
go wrong is a journey sitting within a kilometre or two of a boundary, and it goes wrong
towards the cheaper band, which is the direction that does not overcharge anybody.

THE SOURCE is PRASA's commuter announcement of 30 July 2025, "2025 Fare Adjustment",
effective 1 August 2025 - the first increase in ten years, the previous one having been in
July 2015. It is a scanned image with no text layer, so these numbers were read from the
page rather than parsed off it, and they are written out here where they can be checked
against it rather than buried in a migration.
"""
from __future__ import annotations

import argparse
import collections
import math
from datetime import date

from . import db_compat as db

SOURCE = ("PRASA Commuter Announcement, 2025 Fare Adjustment, issued 30 July 2025")
EFFECTIVE_FROM = date(2025, 8, 1)

# (upper bound in km, label, single, return, weekly Mon-Fri, weekly Mon-Sat, monthly), in
# cents. The last band has no upper bound.
ZONES = [
    (15, "Z1", 1000, 2000, 6000, 7500, 18000),
    (40, "Z2", 1200, 2400, 7000, 8000, 22000),
    (60, "Z3", 1400, 2800, 8000, 10000, 25000),
    (None, "Z4", 1500, 3000, 9000, 12000, 28000),
]

# Everyone gets this off-peak, on single and return tickets, between 09:00 and 14:00.
# Pensioners, military veterans and scholars in uniform get 50% instead - a fact about the
# rider rather than the journey, so it is said in words and not applied to a number.
OFF_PEAK_DISCOUNT = 0.40
OFF_PEAK_FROM, OFF_PEAK_TO = "09:00", "14:00"


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    inner = (math.sin(lat1) * math.sin(lat2)
             + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return 6371.0 * math.acos(max(-1.0, min(1.0, inner)))


def zone_for(distance_km: float):
    """The band a distance falls in, as (label, single, return, wk_mf, wk_ms, monthly)."""
    for upper, *fares in ZONES:
        if upper is None or distance_km <= upper:
            return fares
    return ZONES[-1][1:]


def distances(conn) -> dict[tuple[int, int], float]:
    """
    Kilometres between every pair of stations a service actually runs between.

    Only pairs some train joins, so this prices journeys that exist rather than every
    combination of stations on the map. The measure is the straight line - see the module
    docstring for why the obvious alternative is worse.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sc.id, ss.stop_sequence, s.id, s.lat, s.lon
        FROM schedule sc
        JOIN timetable t  ON t.id = sc.timetable_id
        JOIN route r      ON r.id = t.route_id
        JOIN operator o   ON o.id = r.operator_id AND o.kind = 'train'
        JOIN schedule_stop ss ON ss.schedule_id = sc.id
        JOIN stop s       ON s.id = ss.stop_id
        WHERE s.lat IS NOT NULL
        ORDER BY sc.id, ss.stop_sequence
        """
    )
    lines: dict[int, list] = collections.defaultdict(list)
    for sched, _seq, sid, lat, lon in cur.fetchall():
        lines[sched].append((sid, float(lat), float(lon)))

    best: dict[tuple[int, int], float] = {}
    for stops in lines.values():
        for i, (from_id, flat, flon) in enumerate(stops):
            for to_id, tlat, tlon in stops[i + 1:]:
                if from_id == to_id:
                    continue
                far = km((flat, flon), (tlat, tlon))
                for pair in ((from_id, to_id), (to_id, from_id)):
                    if pair not in best or far < best[pair]:
                        best[pair] = far
    return best


_DDL = """
ALTER TABLE journey_fare ADD COLUMN IF NOT EXISTS return_cents     INTEGER;
ALTER TABLE journey_fare ADD COLUMN IF NOT EXISTS weekly_sat_cents INTEGER;
ALTER TABLE journey_fare ADD COLUMN IF NOT EXISTS distance_km      NUMERIC(6,1);
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Price every Metrorail journey by distance")
    ap.add_argument("--dry-run", action="store_true", help="measure and report, write nothing")
    args = ap.parse_args()

    conn = db.connect()
    try:
        cur = conn.cursor()
        if not args.dry_run:
            cur.execute(_DDL)
            conn.commit()

        pairs = distances(conn)
        print(f"{len(pairs)} station pairs a train runs between\n")

        counts: dict[str, int] = collections.Counter()
        for (from_id, to_id), far in pairs.items():
            label, single, ret, wk_mf, wk_ms, monthly = zone_for(far)
            counts[label] += 1
            if args.dry_run:
                continue
            cur.execute(
                """
                INSERT INTO journey_fare (from_stop_id, to_stop_id, code, basis,
                    basis_from, basis_to, zone_approx, cash_cents, cash_effective_from,
                    return_cents, weekly_cents, weekly_sat_cents, monthly_cents,
                    distance_km, computed_at)
                VALUES (%s, %s, %s, 'prasa_zone', %s, %s, FALSE, %s, %s,
                        %s, %s, %s, %s, %s, now())
                ON CONFLICT (from_stop_id, to_stop_id) DO UPDATE SET
                    code = EXCLUDED.code, basis = EXCLUDED.basis,
                    basis_from = EXCLUDED.basis_from, basis_to = EXCLUDED.basis_to,
                    cash_cents = EXCLUDED.cash_cents,
                    cash_effective_from = EXCLUDED.cash_effective_from,
                    return_cents = EXCLUDED.return_cents,
                    weekly_cents = EXCLUDED.weekly_cents,
                    weekly_sat_cents = EXCLUDED.weekly_sat_cents,
                    monthly_cents = EXCLUDED.monthly_cents,
                    distance_km = EXCLUDED.distance_km,
                    computed_at = now()
                """,
                (from_id, to_id, label, label, f"{far:.1f} km apart", single,
                 EFFECTIVE_FROM, ret, wk_mf, wk_ms, monthly, round(far, 1)),
            )
        if not args.dry_run:
            conn.commit()

        for upper, label, single, *_ in ZONES:
            band = f"1-{upper}km" if label == "Z1" else (
                f"over {ZONES[-2][0]}km" if upper is None else f"to {upper}km")
            print(f"  {label}  {band:<12} single R{single / 100:.2f}   "
                  f"{counts[label]:>5} pairs")
        print(f"\n{sum(counts.values())} journeys "
              f"{'would be' if args.dry_run else ''} priced from "
              f"PRASA's distance bands")
        print(f"source: {SOURCE}, effective {EFFECTIVE_FROM}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
