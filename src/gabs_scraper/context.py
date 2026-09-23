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
from pathlib import Path

from . import db

VIEW = "trip_stop_context"
SQL_PATH = Path(__file__).resolve().parents[2] / "sql" / "planner_context.sql"


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
        # Create it rather than report it missing. The planner's queries now read this
        # view, so a database without it answers no searches at all - which makes it part
        # of the schema, and a setup step somebody has to remember is a setup step
        # somebody forgets. On a new database this is the whole of "install it".
        if not fix:
            print(f"{VIEW} does not exist. Run with --fix to create it.")
            cur.close()
            conn.close()
            return {"exists": False}
        print(f"{VIEW} does not exist; creating it from {SQL_PATH.name}")
        conn.rollback()  # the existence check opened one; autocommit needs none open
        conn.autocommit = True
        cur.execute(SQL_PATH.read_text(encoding="utf-8"))
        held, wanted = _counts(cur)
        print(f"created: {held:,} rows")
        cur.close()
        conn.close()
        return {"exists": True, "rows": held, "expected": wanted, "behind": wanted - held}

    held, wanted = _counts(cur)
    behind = wanted - held
    print(f"{VIEW}: {held:,} rows, timetable has {wanted:,} timed cells "
          f"({behind:+,} behind)")

    if fix:
        # CONCURRENTLY, so searches keep answering from the old rows while this runs
        # rather than blocking on it. It cannot run inside a transaction, and the counts
        # above opened one, so close that first.
        conn.rollback()
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
