"""What a MyCiTi journey costs, from the City's published distance bands.

    PYTHONPATH=src python -m myciti_scraper.fares --dry-run
    PYTHONPATH=src python -m myciti_scraper.fares

MyCiTi prices by DISTANCE, in eight bands, with a peak and a saver price in each, paid from
a myconnect card ("Mover" fares). There is no cash fare. Peak is a journey STARTING on a
weekday between 06:45 and 08:00 or between 16:15 and 17:30; every other time, weekends and
public holidays included, is saver. A journey with a change is one fare for its whole
distance, not a fare per bus - the City's own calculator charges Table View to Kloof Nek,
which changes at Civic Centre, a single 20-30km fare.

HOW FAR IS THE JOURNEY. Along the route: the stop-to-stop hops added up, taking the
shortest of the schedules that run between the two stops. Checked against the City's fare
calculator (www.myciti.org.za/en/myconnect-fares/fare-calculator/) on 40 random pairs on
22 September 2026: 38 land in the same band. The straight line between the two stops,
which is what Metrorail is priced from, matched only 35 - MyCiTi's routes wind (Civic
Centre to Promenade is 3.7km as the crow flies and 6.0km along the route, and the City
charges the 5-10km band). The two that differ sit within a kilometre of a boundary: Hol Bay
to Riebeeckstrand (4.5km here, 5-10km there) and Kei Apple to Adderley (5.1km here, 0-5km
there). Hops are straight lines between stops, so they can cut a bend in the road.

THE SOURCE is the City of Cape Town media release "Fare adjustments 2026"
(www.myciti.org.za/en/contact/media-releases/fare-adjustments-2026/), effective 1 July 2026,
and the multi-day packages page (www.myciti.org.za/en/myconnect-fares/multi-day-packages/).
The figures are written out here so they can be checked against those pages.
"""
from __future__ import annotations

import argparse
import collections
import math
from datetime import date

from . import db_compat as db

SOURCE = "City of Cape Town, MyCiTi fare adjustments 2026"
EFFECTIVE_FROM = date(2026, 7, 1)

# (upper bound in km, peak, saver), in cents. The last band has no upper bound.
BANDS = [
    (5, 1950, 1500),
    (10, 2550, 1950),
    (20, 3250, 2550),
    (30, 3450, 2950),
    (40, 3750, 3200),
    (50, 4250, 3850),
    (60, 4850, 4350),
    (None, 5250, 4600),
]

# Unlimited travel anywhere, at any time, on a myconnect card. In cents.
DAY_PASS = 13000
THREE_DAY_PASS = 29000
SEVEN_DAY_PASS = 42000
MONTHLY_PASS = 150000


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    inner = (math.sin(lat1) * math.sin(lat2)
             + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return 6371.0 * math.acos(max(-1.0, min(1.0, inner)))


def band_for(distance_km: float) -> tuple[str, int, int]:
    """("10-20km", peak, saver) for a distance."""
    lower = 0
    for upper, peak, saver in BANDS:
        if upper is None:
            return f"{lower}km+", peak, saver
        if distance_km <= upper:
            return f"{lower}-{upper}km", peak, saver
        lower = upper
    raise AssertionError("the last band has no upper bound")


def distances(conn) -> dict[tuple[int, int], float]:
    """
    Kilometres along the route between every pair of stops a MyCiTi bus runs between,
    in the direction it runs, the shortest over the schedules that serve both.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ss.schedule_id, ss.stop_sequence, s.id, s.lat, s.lon
        FROM schedule_stop ss
        JOIN stop s     ON s.id = ss.stop_id
        JOIN operator o ON o.id = s.operator_id AND o.code = 'myciti'
        WHERE s.lat IS NOT NULL
        ORDER BY ss.schedule_id, ss.stop_sequence
        """
    )
    runs: dict[int, list] = collections.defaultdict(list)
    for sched, _seq, sid, lat, lon in cur.fetchall():
        runs[sched].append((sid, float(lat), float(lon)))

    best: dict[tuple[int, int], float] = {}
    for stops in runs.values():
        along = [0.0]
        for prev, here in zip(stops, stops[1:]):
            along.append(along[-1] + km(prev[1:], here[1:]))
        for i, (from_id, *_a) in enumerate(stops):
            for j in range(i + 1, len(stops)):
                to_id = stops[j][0]
                if from_id == to_id:
                    continue
                far = along[j] - along[i]
                pair = (from_id, to_id)
                if pair not in best or far < best[pair]:
                    best[pair] = far
    return best


_DDL = """
ALTER TABLE journey_fare ADD COLUMN IF NOT EXISTS return_cents         INTEGER;
ALTER TABLE journey_fare ADD COLUMN IF NOT EXISTS weekly_sat_cents     INTEGER;
ALTER TABLE journey_fare ADD COLUMN IF NOT EXISTS distance_km          NUMERIC(6,1);
ALTER TABLE journey_fare ADD COLUMN IF NOT EXISTS saver_cents          INTEGER;
ALTER TABLE journey_fare ADD COLUMN IF NOT EXISTS day_pass_cents       INTEGER;
ALTER TABLE journey_fare ADD COLUMN IF NOT EXISTS three_day_pass_cents INTEGER;
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Price every MyCiTi journey by distance")
    ap.add_argument("--dry-run", action="store_true", help="measure and report, write nothing")
    args = ap.parse_args()

    conn = db.connect()
    try:
        cur = conn.cursor()
        if not args.dry_run:
            cur.execute(_DDL)
            conn.commit()

        pairs = distances(conn)
        print(f"{len(pairs)} stop pairs a MyCiTi bus runs between\n")

        counts: dict[str, int] = collections.Counter()
        rows = []
        for (from_id, to_id), far in pairs.items():
            label, peak, saver = band_for(far)
            counts[label] += 1
            rows.append((from_id, to_id, label, label, f"{far:.1f} km along the route", peak,
                         EFFECTIVE_FROM, saver, SEVEN_DAY_PASS, MONTHLY_PASS, DAY_PASS,
                         THREE_DAY_PASS, round(far, 1)))
        if not args.dry_run:
            cur.executemany(
                """
                INSERT INTO journey_fare (from_stop_id, to_stop_id, code, basis,
                    basis_from, basis_to, zone_approx, cash_cents, cash_effective_from,
                    saver_cents, weekly_cents, monthly_cents, day_pass_cents,
                    three_day_pass_cents, distance_km, computed_at)
                VALUES (%s, %s, %s, 'myciti_distance', %s, %s, FALSE, %s, %s,
                        %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (from_stop_id, to_stop_id) DO UPDATE SET
                    code = EXCLUDED.code, basis = EXCLUDED.basis,
                    basis_from = EXCLUDED.basis_from, basis_to = EXCLUDED.basis_to,
                    cash_cents = EXCLUDED.cash_cents,
                    cash_effective_from = EXCLUDED.cash_effective_from,
                    saver_cents = EXCLUDED.saver_cents,
                    weekly_cents = EXCLUDED.weekly_cents,
                    monthly_cents = EXCLUDED.monthly_cents,
                    day_pass_cents = EXCLUDED.day_pass_cents,
                    three_day_pass_cents = EXCLUDED.three_day_pass_cents,
                    distance_km = EXCLUDED.distance_km,
                    computed_at = now()
                """,
                rows,
            )
            conn.commit()

        for upper, peak, saver in BANDS:
            label = band_for(upper - 0.01 if upper else 1000)[0]
            print(f"  {label:<9} peak R{peak / 100:.2f}  saver R{saver / 100:.2f}  "
                  f"{counts[label]:>6} pairs")
        print(f"\n{sum(counts.values())} journeys {'would be ' if args.dry_run else ''}priced "
              f"from MyCiTi's distance bands")
        print(f"source: {SOURCE}, effective {EFFECTIVE_FROM}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
