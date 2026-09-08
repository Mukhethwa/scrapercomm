"""Put a read timetable into the same tables Golden Arrow uses.

The schema was built for buses but describes nothing bus-shaped: a route is a named path,
a schedule is a direction and a day type, a trip is one run along it, a stop_time is when
that run reaches a place. Trains fit without bending anything, which is why the planner
needs no new query to answer for them.

Two things differ and are handled here rather than in the schema:

  operator   stops are unique per operator now, so CAPE TOWN the station is a different
             row from CAPE TOWN the bus terminus, and neither can silently claim the
             other's departures

  arrival    PRASA marks a row A or D where a train terminates and starts again. Golden
             Arrow has no equivalent, so the marker column is read and dropped, and the
             row it belongs to is loaded as an ordinary calling point
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, timezone

from . import db_compat as db
from .ocr import TIME, Grid
from .stations import canonical, key

OPERATOR_CODE = "metrorail"

# "#SouthernLineCT : INBOUND Simons Town - Cape Town station"
_LINE = re.compile(r"#(\w+?)Line", re.I)
_DIRECTION = re.compile(r"\b(INBOUND|OUTBOUND)\b", re.I)
_EFFECTIVE = re.compile(r"Effective from\s+(\d{1,2})\s+(\w+)\s+(\d{4})", re.I)

# Which days a sheet is for.
#
# The filenames all say "weekday" and they are not all weekday: page 4 of the Southern
# Line PDF is headed "SOUTHERN LINE WEEKEND INBOUND TIMETABLE". Loading that as a weekday
# service would have offered a rider a Saturday train on a Tuesday morning, which is the
# kind of wrong that gets somebody to a platform for nothing.
_DAY_TYPES = [
    ("SATURDAY", "SATURDAY"),
    ("SUNDAY", "SUNDAY"),
    ("PUBLIC HOLIDAY", "PUBLIC_HOLIDAY"),
    # Kept as WEEKEND rather than resolved to SATURDAY. The sheet says "weekend" and does
    # not say whether Sunday differs; calling it Saturday would be inventing a fact about
    # Sunday, and calling it both would be inventing two.
    ("WEEKEND", "WEEKEND"),
    ("WEEKDAY", "WEEKDAY"),
]


def day_type_of(*texts: str) -> str | None:
    """The day type printed on the page, or None if it does not say."""
    joined = " ".join(t or "" for t in texts).upper()
    for needle, value in _DAY_TYPES:
        if needle in joined:
            return value
    return None

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


def operator_id(cur) -> int:
    cur.execute("SELECT id FROM operator WHERE code = %s", (OPERATOR_CODE,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError("operator 'metrorail' is missing; apply sql/operators.sql")
    return row[0]


def line_name(heading: str) -> str:
    m = _LINE.search(heading or "")
    return f"{m.group(1)} Line".replace("CT", "").strip() if m else "Metrorail"


def direction(heading: str) -> str:
    m = _DIRECTION.search(heading or "")
    return m.group(1).upper() if m else "INBOUND"


def route_name(grid: Grid) -> str:
    """
    Named by where the train actually starts and ends on this page.

    The heading names the line's endpoints, which is not always this page's path - the
    Southern Line has separate Simon's Town and Fish Hoek workings. The station list is
    what the trains on this page really call at, so it names the route.

    Canonical spellings, the same ones the stops are stored under. The weekend sheet
    prints KALKBAAI and the weekday one KALK BAY, so without this the same line appears
    twice in the catalogue under two names for one place.
    """
    stations = [canonical(s) for s in grid.stations if s]
    if len(stations) >= 2:
        return f"{stations[0]} - {stations[-1]}"
    return line_name(grid.heading).upper()


def effective_from(text: str) -> date | None:
    m = _EFFECTIVE.search(text or "")
    if not m:
        return None
    day, month, year = m.group(1), m.group(2).lower(), m.group(3)
    if month not in MONTHS:
        return None
    return date(int(year), MONTHS[month], int(day))


def _marker_column(grid: Grid) -> int | None:
    """
    Which column is the A/D marker rather than a train.

    It sits between the station names and the first train, holds a letter in nearly every
    row, and never holds a time. Identified rather than assumed, because the layout is not
    ours to rely on.
    """
    for ci in range(min(3, max((len(r) for r in grid.times), default=0))):
        cells = [r[ci] for r in grid.times if ci < len(r) and r[ci]]
        if not cells:
            continue
        if not any(TIME.match(c) for c in cells):
            return ci
    return None


def load_page(conn, grid: Grid, *, pdf_path: str, page_number: int,
              day_type: str | None = None) -> dict:
    """Load one page. Returns what it wrote, so a caller can report on it."""
    cur = conn.cursor()
    op = operator_id(cur)
    skip = _marker_column(grid)
    # What the page says it is, then what the caller asked for, then a weekday.
    day_type = day_type_of(grid.heading, grid.title) or day_type or "WEEKDAY"

    name = route_name(grid)
    cur.execute(
        """
        INSERT INTO route (name, origin, destination, operator_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (name) DO UPDATE SET operator_id = EXCLUDED.operator_id
        RETURNING id
        """,
        (name, (grid.stations or [None])[0], (grid.stations or [None])[-1], op),
    )
    route_id = cur.fetchone()[0]

    # One timetable row per table, not per file.
    #
    # timetable.pdf_filename is UNIQUE, and a PRASA PDF holds a dozen tables across its
    # pages. Keyed on the filename alone every table upserted onto the same row, each
    # overwriting the last one's route, and the schedules piled up against whichever
    # route happened to be written last - twelve schedules on one route, named after two
    # stations that never shared a service. The page and table number make the key
    # describe what it actually identifies.
    filename = f"{os.path.basename(pdf_path)}#{page_number}"
    sha = hashlib.sha256(open(pdf_path, "rb").read()).hexdigest()
    cur.execute(
        """
        INSERT INTO timetable (route_id, timetable_number, effective_from, pdf_filename,
                               pdf_sha256, parse_status)
        VALUES (%s, %s, %s, %s, %s, 'parsed')
        ON CONFLICT (pdf_filename) DO UPDATE SET
            route_id = EXCLUDED.route_id, parse_status = 'parsed'
        RETURNING id
        """,
        (route_id, None, effective_from(grid.heading), filename, sha),
    )
    timetable_id = cur.fetchone()[0]

    # Loading the same table twice must not double it.
    cur.execute("DELETE FROM schedule WHERE timetable_id = %s", (timetable_id,))
    cur.execute(
        """
        INSERT INTO schedule (timetable_id, page_number, direction_index, direction_label,
                              day_type, day_label)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (timetable_id, page_number, 0, f"{line_name(grid.heading)} {direction(grid.heading)}",
         day_type, day_type.replace("_", " ").title()),
    )
    schedule_id = cur.fetchone()[0]

    # Stops, in the order the train calls at them.
    stop_ids: list[int] = []
    for seq, station in enumerate(grid.stations):
        if not station:
            stop_ids.append(0)
            continue
        # Find it however it was spelled last time, before adding it again under a new
        # spelling. Two rows for one station is two halves of a line that never meet.
        name = canonical(station)
        cur.execute(
            """
            SELECT id FROM stop
            WHERE operator_id = %s
              AND upper(regexp_replace(name, '[^A-Za-z0-9]', '', 'g')) = %s
            LIMIT 1
            """,
            (op, key(name)),
        )
        found = cur.fetchone()
        if found:
            sid = found[0]
        else:
            cur.execute(
                "INSERT INTO stop (name, operator_id) VALUES (%s, %s) "
                "ON CONFLICT (name, operator_id) DO UPDATE SET name = EXCLUDED.name "
                "RETURNING id",
                (name, op),
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

    written = 0
    trips = 0
    columns = max((len(r) for r in grid.times), default=0)
    for ci in range(columns):
        if ci == skip:
            continue
        # A column holding no times at all is not a service. The tables are drawn with a
        # fixed number of columns and leave the unused ones as "..", so creating a trip
        # for each would put dozens of empty runs on every route.
        if not any(ci < len(r) and TIME.match(r[ci] or "") for r in grid.times):
            continue
        trips += 1
        number = grid.train_numbers[ci] if ci < len(grid.train_numbers) else None
        cur.execute(
            "INSERT INTO trip (schedule_id, trip_index, label) VALUES (%s, %s, %s) RETURNING id",
            (schedule_id, ci, number or None),
        )
        trip_id = cur.fetchone()[0]
        for ri, row in enumerate(grid.times):
            if ci >= len(row) or not row[ci] or ri >= len(stop_ids) or not stop_ids[ri]:
                continue
            m = TIME.match(row[ci])
            if not m:
                continue          # already reported by the checker; never guessed at
            cur.execute(
                "INSERT INTO stop_time (trip_id, schedule_stop_id, cell_type, "
                "departure_time, raw_value) VALUES (%s, %s, 'time', %s, %s)",
                (trip_id, stop_ids[ri],
                 f"{m.group(1).zfill(2)}:{m.group(2)}"
                 + (f":{m.group(3)}" if m.group(3) else ""),
                 row[ci]),
            )
            written += 1

    conn.commit()
    return {"route": name, "route_id": route_id, "timetable_id": timetable_id,
            "schedule_id": schedule_id, "stops": len([s for s in stop_ids if s]),
            "trips": trips, "times": written}
