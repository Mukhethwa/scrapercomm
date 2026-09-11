"""Put a read MyCiTi timetable into the tables the other two operators already use.

Nothing here is new shape. A route is a named path, a schedule is a direction on a kind of
day, a trip is one run along it, a stop_time is when that run reaches a place - which is
what the planner reads, so MyCiTi needs no new query to be plannable.

Three things are MyCiTi's own and are handled here rather than in the schema:

  operator    stops are unique per operator, so Civic Centre the MyCiTi station is its own
              row. It is not Golden Arrow's CAPE TOWN and must not inherit its departures

  the number  a rider looks for "D01" on the front of the bus, the way a Metrorail rider
              looks for the line. It is the timetable number, which the app already shows

  a service   spans pages rather than sitting on one, so the unit loaded is a joined run
              and the key has to name the run rather than the page
"""
from __future__ import annotations

import hashlib
import os

from . import db_compat as db
from .parse import Run

OPERATOR_CODE = "myciti"
OPERATOR_NAME = "MyCiTi"
# A bus. Not because the vehicles look like Golden Arrow's - they do not, and the stations
# have platforms - but because `kind` answers "what does a rider walk to and board", and
# the answer is a kerb-side stop rather than a railway station. Everything in the planner
# that branches on kind is asking that question.
OPERATOR_KIND = "bus"


def operator_id(cur) -> int:
    cur.execute(
        """
        INSERT INTO operator (code, name, kind) VALUES (%s, %s, %s)
        ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind
        RETURNING id
        """,
        (OPERATOR_CODE, OPERATOR_NAME, OPERATOR_KIND),
    )
    return cur.fetchone()[0]


def route_name(run: Run) -> str:
    """
    "101: Vredehoek - Gardens - Civic Centre (clockwise)".

    The number leads because it is what is painted on the bus and printed at the stop.
    Golden Arrow has nothing equivalent - it names routes and numbers only timetables -
    so this reads differently from a GABS label on purpose.
    """
    return f"{run.route}: {run.title.title() if run.title.isupper() else run.title}"


def direction_label(run: Run) -> str:
    """
    "101 to Vredehoek", from the page's own "Direction: To 101 Vredehoek".

    Rewritten rather than stored verbatim: the sheet's wording puts the route number in
    the middle of the phrase, which reads as a stutter beside a card already headed with
    the route.
    """
    text = run.direction.strip()
    lowered = text.lower()
    if lowered.startswith("to "):
        rest = text[3:].strip()
        # "101 Vredehoek" or "T01a Civic Centre" - drop the number if it repeats the route.
        first, _, tail = rest.partition(" ")
        if tail and first.upper().rstrip("ABCX").startswith(run.route.rstrip("ABCX")[:3]):
            return f"{run.route} to {tail.strip()}"
        return f"{run.route} to {rest}"
    return text or run.route


def forget_everything(conn) -> dict:
    """
    Remove every MyCiTi row, so a reload cannot leave half of an old reading behind.

    Scoped to this operator by construction: it walks down from the operator's own routes
    and stops, and touches nothing belonging to Golden Arrow or Metrorail.
    """
    cur = conn.cursor()
    cur.execute("SELECT id FROM operator WHERE code = %s", (OPERATOR_CODE,))
    row = cur.fetchone()
    if not row:
        return {}
    op = row[0]
    counts = {}
    cur.execute("""
        DELETE FROM stop_time st USING trip t, schedule s, timetable tt, route r
        WHERE st.trip_id = t.id AND t.schedule_id = s.id AND s.timetable_id = tt.id
          AND tt.route_id = r.id AND r.operator_id = %s""", (op,))
    counts["stop_time"] = cur.rowcount
    cur.execute("""
        DELETE FROM trip t USING schedule s, timetable tt, route r
        WHERE t.schedule_id = s.id AND s.timetable_id = tt.id AND tt.route_id = r.id
          AND r.operator_id = %s""", (op,))
    counts["trip"] = cur.rowcount
    cur.execute("""
        DELETE FROM schedule_stop ss USING schedule s, timetable tt, route r
        WHERE ss.schedule_id = s.id AND s.timetable_id = tt.id AND tt.route_id = r.id
          AND r.operator_id = %s""", (op,))
    counts["schedule_stop"] = cur.rowcount
    cur.execute("""
        DELETE FROM schedule s USING timetable tt, route r
        WHERE s.timetable_id = tt.id AND tt.route_id = r.id AND r.operator_id = %s""", (op,))
    counts["schedule"] = cur.rowcount
    cur.execute("DELETE FROM timetable tt USING route r "
                "WHERE tt.route_id = r.id AND r.operator_id = %s", (op,))
    counts["timetable"] = cur.rowcount
    cur.execute("DELETE FROM route WHERE operator_id = %s", (op,))
    counts["route"] = cur.rowcount
    conn.commit()
    return counts


def load_run(conn, run: Run, *, pdf_path: str) -> dict:
    """Load one direction on one kind of day. Returns what it wrote."""
    cur = conn.cursor()
    op = operator_id(cur)

    name = route_name(run)
    cur.execute(
        """
        INSERT INTO route (name, origin, destination, operator_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (name, operator_id) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (name, run.stops[0], run.stops[-1], op),
    )
    route_id = cur.fetchone()[0]

    # One timetable row per SERVICE, not per file and not per page.
    #
    # pdf_filename is unique, and one file holds six services across up to fourteen pages.
    # Keyed on the file alone every service would upsert onto one row and overwrite the
    # last; keyed on the page, a service printed across three pages would become three
    # routes each with a third of the departures.
    key = f"{os.path.basename(pdf_path)}#{run.day_type}#{run.direction}"
    sha = hashlib.sha256(open(pdf_path, "rb").read()).hexdigest()
    cur.execute(
        """
        INSERT INTO timetable (route_id, timetable_number, pdf_filename, pdf_sha256,
                               page_count, parse_status)
        VALUES (%s, %s, %s, %s, %s, 'parsed')
        ON CONFLICT (pdf_filename) DO UPDATE SET
            route_id = EXCLUDED.route_id, timetable_number = EXCLUDED.timetable_number,
            parse_status = 'parsed'
        RETURNING id
        """,
        (route_id, run.route, key, sha, len(run.pages)),
    )
    timetable_id = cur.fetchone()[0]

    # Loading the same service twice must not double it.
    cur.execute("DELETE FROM schedule WHERE timetable_id = %s", (timetable_id,))
    cur.execute(
        """
        INSERT INTO schedule (timetable_id, page_number, direction_index, direction_label,
                              day_type, day_label)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (timetable_id, run.pages[0], 0, direction_label(run),
         run.day_type, run.day_type.replace("_", " ").title()),
    )
    schedule_id = cur.fetchone()[0]

    stop_ids: list[int] = []
    for seq, stop in enumerate(run.stops):
        cur.execute(
            "INSERT INTO stop (name, operator_id) VALUES (%s, %s) "
            "ON CONFLICT (name, operator_id) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id",
            (stop, op),
        )
        sid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO schedule_stop (schedule_id, stop_id, stop_sequence) "
            "VALUES (%s, %s, %s) ON CONFLICT (schedule_id, stop_sequence) DO NOTHING "
            "RETURNING id",
            (schedule_id, sid, seq),
        )
        row = cur.fetchone()
        stop_ids.append(row[0] if row else 0)

    written = trips = 0
    for ci in range(run.trips):
        column = [row[ci] if ci < len(row) else "" for row in run.times]
        if not any(column):
            continue          # a drawn column with no service in it
        trips += 1
        cur.execute(
            "INSERT INTO trip (schedule_id, trip_index, label) VALUES (%s, %s, %s) "
            "RETURNING id",
            # The route number, which is what the bus displays. Golden Arrow trips carry
            # nothing here and Metrorail carries the train number; all three answer the
            # same question - what does a rider look for as it pulls in.
            (schedule_id, ci, run.route),
        )
        trip_id = cur.fetchone()[0]
        for ri, value in enumerate(column):
            if not value or ri >= len(stop_ids) or not stop_ids[ri]:
                continue
            # 'TIME' upper case, which is what every query comparing cell_type expects.
            # The PRASA loader wrote it lower case once and no train connection was
            # possible on any line until it was found.
            cur.execute(
                "INSERT INTO stop_time (trip_id, schedule_stop_id, cell_type, "
                "departure_time, raw_value) VALUES (%s, %s, 'TIME', %s, %s)",
                (trip_id, stop_ids[ri], value, value),
            )
            written += 1

    conn.commit()
    return {"route": name, "route_id": route_id, "timetable_id": timetable_id,
            "schedule_id": schedule_id, "stops": len([s for s in stop_ids if s]),
            "trips": trips, "times": written}
