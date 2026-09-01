"""Work out what each journey costs, once, into a table both services can just read.

The operator publishes 845 fares between about 193 broad *fare zones*. Our timetables
run between 527 fine-grained timing points, so almost no journey has a fare printed
against exactly its two stops. Three things are tried, in order, and every answer records
which one it came from so the app can say so:

    exact    both stops sit in zones with a published fare between them
    section  the nearest published fare either side that still covers the whole ride
    route    the fare for the trip's own route, end to end - the price a rider is
             actually sold when they board it

A journey that reaches none of those has no published fare, and is left empty. Guessing
one would be worse than saying nothing: it is money, and a rider would plan around it.

Resolving this per request would mean the same tricky logic in Java and in Python, kept
in step by hand. Precomputing it means one implementation and a primary-key lookup at
request time.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from . import db
from .fares import RIDES, ROUTE_ALIASES, _squash, _tokens

_DDL = """
CREATE TABLE IF NOT EXISTS journey_fare (
    from_stop_id    INTEGER NOT NULL REFERENCES stop(id) ON DELETE CASCADE,
    to_stop_id      INTEGER NOT NULL REFERENCES stop(id) ON DELETE CASCADE,
    code            TEXT,
    five_ride_cents INTEGER,
    weekly_cents    INTEGER,
    monthly_cents   INTEGER,
    per_ride_cents  INTEGER,
    transfers       TEXT,
    basis           TEXT NOT NULL,   -- exact | section | route
    basis_from      TEXT,            -- the fare zones the price is actually printed for
    basis_to        TEXT,
    computed_at     TIMESTAMPTZ,
    PRIMARY KEY (from_stop_id, to_stop_id)
);
"""


class Zones:
    """Fare-zone lookup by name, tolerant of how the two sources spell things."""

    def __init__(self, zone_names):
        self.by_squash: dict[str, list[str]] = {}
        self.by_tokens: dict[tuple, list[str]] = {}
        for zone in zone_names:
            # "Athlone / Athlone Industria" names two places, and a route may be
            # signed as either. Index every label, not just the whole string.
            for label in (p.strip() for p in zone.split("/")):
                if not label:
                    continue
                self.by_squash.setdefault(_squash(label), []).append(zone)
                self.by_tokens.setdefault(tuple(_tokens(label)), []).append(zone)

    def find(self, name: str) -> list[str]:
        alias = ROUTE_ALIASES.get(name.upper())
        if alias:
            name = alias
        want = tuple(_tokens(name))
        if not want:
            return []
        if want in self.by_tokens:
            return self.by_tokens[want]
        hit = self.by_squash.get(_squash(name))
        if hit:
            return hit
        for have, zones in self.by_tokens.items():
            if len(have) == len(want) and all(
                    a == b or a.startswith(b) or b.startswith(a)
                    for a, b in zip(have, want)):
                return zones
        # A named place inside a broader zone: "EPPING" priced as "Epping Industria".
        for have, zones in self.by_tokens.items():
            if have and len(want) > len(have) and all(
                    a == b for a, b in zip(want[:len(have)], have)):
                return zones
        return []


def _load(conn):
    cur = conn.cursor()
    cur.execute("SELECT origin_zone, destination_zone, code, five_ride_cents, "
                "weekly_cents, monthly_cents, transfers FROM fare")
    fares: dict[tuple[str, str], tuple] = {}
    for o, d, code, five, week, month, tr in cur.fetchall():
        row = (code, five, week, month, tr)
        fares[(o, d)] = row
        fares.setdefault((d, o), row)          # the page prints each pair one way only

    cur.execute("SELECT stop_id, zone FROM fare_zone_stop")
    stop_zones: dict[int, list[str]] = {}
    for sid, zone in cur.fetchall():
        stop_zones.setdefault(sid, []).append(zone)

    zone_names = sorted({z for pair in fares for z in pair})
    return fares, stop_zones, Zones(zone_names)


def _priced(fares, a_zones, b_zones):
    """The published fare between any zone of A and any zone of B."""
    for za in a_zones:
        for zb in b_zones:
            row = fares.get((za, zb))
            if row and row[1] is not None:
                return row, za, zb
    return None, None, None


def compute(conn) -> dict:
    cur = conn.cursor()
    for stmt in filter(str.strip, _DDL.split(";")):
        cur.execute(stmt)
    conn.commit()

    fares, stop_zones, zones = _load(conn)

    # Every trip in stop order, with the route it belongs to. One pass; the pairs are
    # derived from it rather than queried again per pair.
    cur.execute(
        """
        SELECT st.trip_id, ss.stop_sequence, ss.stop_id, r.origin, r.destination
        FROM stop_time st
        JOIN schedule_stop ss ON ss.id = st.schedule_stop_id
        JOIN schedule sc      ON sc.id = ss.schedule_id
        JOIN timetable t      ON t.id = sc.timetable_id
        JOIN route r          ON r.id = t.route_id
        WHERE st.cell_type <> 'NONE'
        ORDER BY st.trip_id, ss.stop_sequence
        """
    )
    trips: dict[int, list[int]] = {}
    trip_route: dict[int, tuple[str, str]] = {}
    for tid, _seq, sid, origin, dest in cur.fetchall():
        trips.setdefault(tid, []).append(sid)
        trip_route[tid] = (origin, dest)

    route_fare: dict[tuple[str, str], tuple] = {}

    def for_route(key):
        if key not in route_fare:
            row, za, zb = _priced(fares, zones.find(key[0]), zones.find(key[1]))
            route_fare[key] = (row, za, zb)
        return route_fare[key]

    resolved: dict[tuple[int, int], tuple] = {}
    # Every pair we ever saw, so the ones that stay unpriced can be counted once at the
    # end rather than once per trip that serves them.
    all_pairs: set[tuple[int, int]] = set()

    for tid, stops in trips.items():
        rkey = trip_route[tid]
        for i in range(len(stops)):
            for j in range(i + 1, len(stops)):
                a, b = stops[i], stops[j]
                if a == b or (a, b) in resolved:
                    continue
                # Not cached as a failure: another trip through the same two stops may
                # run a route that does have a published fare.
                all_pairs.add((a, b))
                row, za, zb = _priced(fares, stop_zones.get(a, []), stop_zones.get(b, []))
                basis = "exact"
                if row is None:
                    # Widen outward to the nearest priced stops that still enclose the
                    # whole ride, so the fare can never cover less than was travelled.
                    lo = next((k for k in range(i, -1, -1) if stop_zones.get(stops[k])), None)
                    hi = next((k for k in range(j, len(stops)) if stop_zones.get(stops[k])), None)
                    if lo is not None and hi is not None:
                        row, za, zb = _priced(fares, stop_zones[stops[lo]], stop_zones[stops[hi]])
                        basis = "section"
                if row is None:
                    row, za, zb = for_route(rkey)
                    basis = "route"
                if row is None:
                    continue
                resolved[(a, b)] = (row, za, zb, basis)

    counts = {"exact": 0, "section": 0, "route": 0}
    for _row, _za, _zb, basis in resolved.values():
        counts[basis] += 1
    counts["none"] = len(all_pairs) - len(resolved)

    cur.execute("DELETE FROM journey_fare")
    now = datetime.now(timezone.utc)
    for (a, b), ((code, five, week, month, transfers), za, zb, basis) in resolved.items():
        cur.execute(
            """
            INSERT INTO journey_fare (from_stop_id, to_stop_id, code, five_ride_cents,
                weekly_cents, monthly_cents, per_ride_cents, transfers, basis,
                basis_from, basis_to, computed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (from_stop_id, to_stop_id) DO UPDATE SET
                code=EXCLUDED.code, five_ride_cents=EXCLUDED.five_ride_cents,
                weekly_cents=EXCLUDED.weekly_cents, monthly_cents=EXCLUDED.monthly_cents,
                per_ride_cents=EXCLUDED.per_ride_cents, transfers=EXCLUDED.transfers,
                basis=EXCLUDED.basis, basis_from=EXCLUDED.basis_from,
                basis_to=EXCLUDED.basis_to, computed_at=EXCLUDED.computed_at
            """,
            (a, b, code, five, week, month,
             None if five is None else round(five / RIDES["five_ride"]),
             transfers, basis, za, zb, now),
        )
    conn.commit()
    counts["pairs"] = len(resolved)
    return counts


def run() -> dict:
    conn = db.connect()
    try:
        return compute(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    argparse.ArgumentParser(description="Precompute a fare for every journey").parse_args()
    c = run()
    total = c["exact"] + c["section"] + c["route"] + c["none"]
    print(f"journey pairs priced : {c['pairs']}")
    for k in ("exact", "section", "route", "none"):
        print(f"  {k:8}: {c[k]:6}  ({100 * c[k] / max(total, 1):.1f}%)")
