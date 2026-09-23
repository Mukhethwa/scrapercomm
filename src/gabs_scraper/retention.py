"""Forget who searched, once the counting no longer needs to know.

    PYTHONPATH=src python -m gabs_scraper.retention          # report
    PYTHONPATH=src python -m gabs_scraper.retention --fix    # and forget

The privacy policy tells riders: "The id this app made is kept for up to 12 months and
then removed from those rows, which leaves the counts and takes away the thread between
them." Nothing did that. A promise in a policy that no job keeps is worse than no promise,
because it is the sentence somebody quotes back at you.

So: after MONTHS_KEPT, search_analytics.device_id and place_search.device_id are set to
NULL. The rows stay, because the counts are the point - how many searches, which routes,
which places nobody could find. What goes is the thread that says two of them came from
the same phone, which is only worth keeping while it can answer "how many people used
this in the last year".

Nothing is deleted. A count that disappears would take the demand history with it, and
that history is the part the City and the operators are being sold.
"""
from __future__ import annotations

import argparse

from . import db

# How long an anonymous install id is worth keeping.
#
# Twelve months because the questions it answers are yearly ones: how many people, coming
# back how often, over a year of seasons and school terms. Past that it is a thread nobody
# is pulling, and the policy says it goes.
MONTHS_KEPT = 12

TABLES = ("search_analytics", "place_search")


def run(fix: bool = False) -> dict:
    conn = db.connect()
    cur = conn.cursor()
    counts: dict[str, int] = {}

    for table in TABLES:
        column = "searched_at"
        cur.execute(
            f"""
            SELECT count(*) FROM {table}
            WHERE device_id IS NOT NULL
              AND {column} < now() - make_interval(months => %s)
            """,
            (MONTHS_KEPT,),
        )
        counts[table] = cur.fetchone()[0]
        if fix and counts[table]:
            cur.execute(
                f"""
                UPDATE {table} SET device_id = NULL
                WHERE device_id IS NOT NULL
                  AND {column} < now() - make_interval(months => %s)
                """,
                (MONTHS_KEPT,),
            )

    if fix:
        conn.commit()

    cur.execute("SELECT count(*) FILTER (WHERE device_id IS NOT NULL), count(*) FROM search_analytics")
    with_id, total = cur.fetchone()
    cur.close()
    conn.close()

    due = sum(counts.values())
    print(f"rows older than {MONTHS_KEPT} months still carrying an id: {due}")
    for table, n in counts.items():
        print(f"  {table}: {n}")
    print(f"searches held: {total}, of which {with_id} can still be counted by phone")
    if due and not fix:
        print("\nrun with --fix to forget them")
    return {"due": due, "forgotten": due if fix else 0, "searches": total}


def main() -> None:
    ap = argparse.ArgumentParser(description="Drop anonymous ids the policy says to drop")
    ap.add_argument("--fix", action="store_true", help="write the change")
    run(fix=ap.parse_args().fix)


if __name__ == "__main__":
    main()
