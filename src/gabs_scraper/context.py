"""Rebuild the planner's precomputed floors and ceilings after a load.

    PYTHONPATH=src python -m gabs_scraper.context          # report
    PYTHONPATH=src python -m gabs_scraper.context --fix    # and rebuild

See sql/planner_context.sql for what trip_stop_context holds and why. In short: the
timetable prints a time at timing points and "via" everywhere else, so every search worked
out the nearest printed times around a stop with a window over every departure of every
trip that touches it. From a hub that is hundreds of thousands of rows per request.

This is the same arithmetic, done once per load. It has to run after ANY loader writes
departures - Golden Arrow, MyCiTi or Metrorail - because a stale copy would answer with
the last load's times, which is worse than a slow query. The refresh scripts run it; if
you load by hand, run it by hand.

Reports how far behind it is rather than only rebuilding, so "is it stale" is a question
with an answer.
"""
from __future__ import annotations

import argparse

from . import db

VIEW = "trip_stop_context"


def _exists(cur) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (VIEW,))
    return cur.fetchone()[0]


def _counts(cur) -> tuple[int, int]:
    """Rows the view holds, and rows it should hold."""
    cur.execute(f"SELECT count(*) FROM {VIEW}")
    held = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM stop_time WHERE cell_type <> 'NONE'")
    return held, cur.fetchone()[0]


def run(fix: bool = False) -> dict:
    conn = db.connect()
    cur = conn.cursor()

    if not _exists(cur):
        print(f"{VIEW} does not exist yet. Create it once:")
        print("  docker exec -i gabs_pg psql -U gabs -d gabs < sql/planner_context.sql")
        cur.close()
        conn.close()
        return {"exists": False}

    held, wanted = _counts(cur)
    behind = wanted - held
    print(f"{VIEW}: {held:,} rows, timetable has {wanted:,} timed cells "
          f"({behind:+,} behind)")

    if fix:
        # CONCURRENTLY, so searches keep answering from the old rows while this runs
        # rather than blocking on it. It needs its own transaction.
        conn.autocommit = True
        cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {VIEW}")
        held, wanted = _counts(cur)
        print(f"rebuilt: {held:,} rows")
    elif behind:
        print("\nrun with --fix to rebuild it")

    cur.close()
    conn.close()
    return {"exists": True, "rows": held, "expected": wanted, "behind": wanted - held}


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild the planner's precomputed context")
    ap.add_argument("--fix", action="store_true", help="rebuild it")
    run(fix=ap.parse_args().fix)


if __name__ == "__main__":
    main()
