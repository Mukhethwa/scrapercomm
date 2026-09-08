"""Find stations that are one place stored twice.

    PYTHONPATH=src python -m prasa_scraper.duplicates

A station stored under two spellings is a line the planner can never route through: a
journey ending at KALK BAY and one starting at KALKBAAI never join, and the app reports no
service on a line that runs every twenty minutes. stations.py collapses the variants it
knows about, and the ones it knows about are the ones somebody noticed.

VISHOEK is why this exists. The Southern Line's weekend outbound sheet is printed in
Afrikaans where the inbound one is not, and lists VISHOEK exactly where the inbound sheet
lists FISH HOEK. Nothing derived one from the other, nothing complained, and the only
reason it did not ship as two stations is that I happened to look at the page image. That
is not a process.

So this asks the loaded data the question directly: which stations look like each other,
and which look like a bus stop of the same name? It reports; it never merges. Deciding
that two spellings are one place is a claim about Cape Town, and it belongs in the alias
table where it can be read, not in a script that quietly rewrites rows.
"""
from __future__ import annotations

import argparse
import difflib

from . import db_compat as db
from .stations import key

# Pairs closer than this are worth a human look. Measured against the stations actually
# on these lines: VISHOEK to FISH HOEK is 0.80 and KALKBAAI to KALK BAY is 0.80, while the
# closest genuinely different pair is STEENBERG to MUIZENBERG at 0.63 and WYNBERG to
# STEENBERG at 0.62. Anywhere between those two clusters works; 0.70 sits in the middle.
SIMILAR = 0.70


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def main() -> None:
    ap = argparse.ArgumentParser(description="Report stations that may be one place twice")
    ap.add_argument("--threshold", type=float, default=SIMILAR)
    args = ap.parse_args()

    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.id, s.name, o.kind
            FROM stop s JOIN operator o ON o.id = s.operator_id
            ORDER BY o.kind, s.name
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    trains = [(i, n) for i, n, kind in rows if kind == "train"]
    buses = {key(n): (i, n) for i, n, kind in rows if kind == "bus"}

    # Two spellings of one station. The keys differ - anything that shares a key is
    # already one row - so what is left is a real difference in letters.
    print(f"{len(trains)} stations\n")
    print("stations that resemble each other:")
    found = 0
    for x, (id_a, a) in enumerate(trains):
        for id_b, b in trains[x + 1:]:
            score = _similar(key(a), key(b))
            if score >= args.threshold:
                print(f"  {score:.2f}  {a!r} ({id_a})  ~  {b!r} ({id_b})")
                found += 1
    if not found:
        print("  none")

    # A station and a bus stop of the same name are not a mistake - they are the two
    # places stop_interchange exists to join - but they are worth seeing in one list,
    # because that is where a change between a bus and a train can be made.
    print("\nstations sharing a name with a bus stop:")
    shared = [(n, buses[key(n)][1]) for _, n in trains if key(n) in buses]
    for station, stop in shared:
        print(f"  {station!r} is also a bus stop ({stop!r})")
    if not shared:
        print("  none")
    print(f"\n{found} pairs to look at, {len(shared)} shared with the bus network")


if __name__ == "__main__":
    main()
