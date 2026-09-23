"""How old is the data we are serving, per operator.

    PYTHONPATH=src python -m gabs_scraper.freshness
    PYTHONPATH=src python -m gabs_scraper.freshness --check

Written to be run after a load, and on a schedule. --check exits non-zero when anything
is past its age, so a job that quietly stopped working is a failure somebody is told
about rather than a table that slowly goes out of date while every screen still looks
fine.

There is no clever measure here. A timetable has a last day it is valid, the operator
publishes replacements, and a loader either ran recently or did not. What made this worth
writing is that nothing was watching: on 23 September 2026 Golden Arrow's data was 18 days
old, 639 of 2,140 timetables had already ended, and Metrorail's and MyCiTi's loaders had
never recorded when they ran at all.
"""
from __future__ import annotations

import argparse
import sys

from . import db

# How long each operator's data may go without a load before it is called stale.
#
# Golden Arrow reissues weekly, so a fortnight is already two cycles behind. The other two
# change a few times a year and their timetables carry no end date, so the bar is the load
# itself rather than what it contains.
MAX_AGE_DAYS = {"gabs": 14, "myciti": 120, "metrorail": 120}

# What share of an operator's timetables may have ended before we call it stale.
#
# Never zero: Golden Arrow always has a few services whose last printed day has passed and
# which it has not reissued, and holding them is better than pretending the bus vanished.
MAX_EXPIRED_SHARE = 0.25


def rows(conn) -> list[tuple]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT o.code,
               count(t.id)                                                   AS timetables,
               max(t.scraped_at)::date                                       AS last_load,
               (now()::date - max(t.scraped_at)::date)                       AS age_days,
               count(*) FILTER (WHERE t.effective_to < now()::date)          AS expired
        FROM timetable t
        JOIN route r    ON r.id = t.route_id
        JOIN operator o ON o.id = r.operator_id
        GROUP BY o.code
        ORDER BY o.code
        """
    )
    out = cur.fetchall()
    cur.close()
    return out


def run(check: bool = False) -> int:
    conn = db.connect()
    problems = []
    print(f"{'operator':<12}{'timetables':>12}{'last load':>14}{'age':>8}{'expired':>10}")
    for code, timetables, last_load, age_days, expired in rows(conn):
        share = expired / timetables if timetables else 0.0
        age = "never" if age_days is None else f"{age_days}d"
        print(f"{code:<12}{timetables:>12}{str(last_load or '-'):>14}{age:>8}"
              f"{expired:>6} ({share:.0%})")

        limit = MAX_AGE_DAYS.get(code, 120)
        if age_days is None:
            problems.append(f"{code}: no load has ever been recorded")
        elif age_days > limit:
            problems.append(f"{code}: last loaded {age_days} days ago, limit is {limit}")
        if share > MAX_EXPIRED_SHARE:
            problems.append(f"{code}: {expired} of {timetables} timetables have ended "
                            f"({share:.0%}, limit {MAX_EXPIRED_SHARE:.0%})")
    conn.close()

    if problems:
        print("\nstale:")
        for p in problems:
            print(f"  {p}")
    else:
        print("\nevery operator is inside its limits")
    return 1 if (check and problems) else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Report how fresh each operator's data is")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero when anything is stale, for a scheduled job")
    sys.exit(run(check=ap.parse_args().check))


if __name__ == "__main__":
    main()
