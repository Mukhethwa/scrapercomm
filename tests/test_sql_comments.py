"""No apostrophes in the SQL comments Spring parses.

Spring scans a native @Query for quoted ranges before Postgres ever sees it, and it does
not strip comments first. So one apostrophe inside a `--` line starts a string literal that
never ends, and the application refuses to start with:

    The string <SELECT sc.id AS "id", ... > starts a quoted range at N, but never ends it

The failure is at startup, not at compile time, and the message points at the whole query
rather than the comment - so it costs an hour the first time and, as it turns out, again
the second. Writing "the route's own name" in a comment above a SELECT is enough to take
the API down.

Only Java matters. The .sql files are run by psql and psycopg, which parse SQL properly and
do not care.
"""
from __future__ import annotations

import pathlib

JAVA = pathlib.Path(__file__).resolve().parent.parent / "backend" / "src" / "main" / "java"


def test_no_apostrophe_in_a_sql_comment():
    offenders = []
    for path in JAVA.rglob("*.java"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("--") and "'" in stripped:
                offenders.append(f"{path.name}:{number}: {stripped}")

    assert not offenders, (
        "an apostrophe in a SQL comment stops Spring parsing the query and the app will "
        "not start:\n  " + "\n  ".join(offenders))
