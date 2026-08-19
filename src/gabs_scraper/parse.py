"""Parse a GABS timetable PDF into structured dataclasses.

Each PDF page holds one direction (a route path title) with one or more day-type
sections (MONDAYS TO FRIDAYS, SATURDAYS, SUNDAYS, PUBLIC HOLIDAYS…). A section is
a fixed-width, pipe-delimited grid: rows = stops, columns = trips. Cells hold a
departure time (optionally with a footnote letter), ``via`` (passes, no set time),
or ``--`` (not served on that trip). Public-holiday PDFs sometimes bundle several
unrelated routes across pages, so each schedule keeps its own label / number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pdfplumber

_SEP = re.compile(r"^-{5,}$")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})([A-Za-z]*)$")
_NOTE = re.compile(r"^([A-Za-z0-9])\s*-\s*(.+)$")
_EFF = re.compile(r"EFFECTIVE\s+DATE:\s*(\d{4})/(\d{2})/(\d{2})", re.I)
_TTNUM = re.compile(r"TIMETABLE\s+NUMBER:\s*([\d ]+)", re.I)
_DAYTYPE_KW = re.compile(
    r"\b(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY|"
    r"PUBLIC HOLIDAY|WEEKDAY|DAILY|SCHOOL)S?\b",
    re.I,
)
_NONE_TOKENS = {"", "-", "--", "---"}


@dataclass
class StopTime:
    stop_name: str
    cell_type: str            # 'TIME' | 'VIA' | 'NONE'
    departure_time: str | None  # 'HH:MM'
    note_code: str | None
    raw_value: str


@dataclass
class Trip:
    trip_index: int
    note_codes: list[str]
    times: list[StopTime]


@dataclass
class Schedule:
    page_number: int
    direction_index: int
    direction_label: str
    day_type: str             # WEEKDAY|SATURDAY|SUNDAY|PUBLIC_HOLIDAY|OTHER
    day_label: str
    section_timetable_number: str | None
    section_effective_date: str | None  # 'YYYY-MM-DD'
    no_service: bool
    stops: list[str]
    trips: list[Trip]


@dataclass
class Note:
    code: str
    description: str


@dataclass
class ParsedTimetable:
    timetable_number: str | None
    page_count: int
    raw_text: str
    schedules: list[Schedule] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)


def _day_type(day_label: str) -> str:
    up = day_label.upper()
    if "PUBLIC HOLIDAY" in up:
        return "PUBLIC_HOLIDAY"
    if "SUNDAY" in up:
        return "SUNDAY"
    if "SATURDAY" in up:
        return "SATURDAY"
    if any(k in up for k in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY",
                             "FRIDAY", "WEEKDAY", "DAILY", "SCHOOL")):
        return "WEEKDAY"
    return "OTHER"


def _is_disclaimer(line: str) -> bool:
    up = line.upper()
    return (
        up.startswith("EVERY EFFORT")
        or up.startswith("BE HELD LIABLE")
        or up.startswith("OPERATED SUBJECT")
        or up.startswith("SERVICE ENQUIRIES")
        or up.startswith("LAST UPDATED")
    )


def _is_section_header(line: str) -> bool:
    if "EFFECTIVE DATE" in line.upper():
        return True
    return bool(_DAYTYPE_KW.search(line)) and len(line) < 80


def _parse_cell(raw: str) -> tuple[str, str | None, str | None]:
    v = raw.strip()
    if v in _NONE_TOKENS:
        return "NONE", None, None
    if v.lower() == "via":
        return "VIA", None, None
    m = _TIME.match(v)
    if m:
        hh, mm, suffix = int(m.group(1)), m.group(2), (m.group(3) or "")
        note = suffix.strip() or None
        if 0 <= hh <= 23 and 0 <= int(mm) <= 59:
            return "TIME", f"{hh:02d}:{mm}", note
        return "TIME", None, note  # out-of-range (e.g. 24:xx); keep raw only
    return "NONE", None, None


def _new_section(header: str) -> dict:
    day_label = header
    eff = None
    m = _EFF.search(header)
    if m:
        eff = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        day_label = header[: m.start()].strip()
    tt = None
    m2 = _TTNUM.search(header)
    if m2:
        tt = m2.group(1).replace(" ", "").strip() or None
        if day_label == header:  # no EFFECTIVE DATE trimmed it yet
            day_label = header[: m2.start()].strip()
    no_service = "NO SERVICE" in header.upper()
    day_label = re.sub(r"[-\s]*NO SERVICE.*$", "", day_label, flags=re.I).strip()
    return {"day_label": day_label, "eff": eff, "tt": tt,
            "no_service": no_service, "rows": []}


def _build_schedule(sec: dict, page_number: int, direction_label: str) -> Schedule:
    # A section may WRAP: routes with >22 trips continue in stacked blocks that
    # repeat the same stops with the next batch of trip columns, separated by an
    # all-dashes pipe row. Split into blocks, then concatenate them horizontally
    # (align rows by stop name) so blocks add trips, not duplicate stops.
    blocks: list[list[tuple[str, list[str]]]] = [[]]
    for row in sec["rows"]:
        cells = [c.strip() for c in row.split("|")][1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if not cells or not cells[0]:
            continue
        if not re.search(r"[A-Za-z0-9]", cells[0]):  # separator between wrapped blocks
            if blocks[-1]:
                blocks.append([])
            continue
        blocks[-1].append((cells[0], cells[1:]))
    blocks = [b for b in blocks if b]

    stops: list[str] = []
    rows: dict[str, list[str]] = {}
    filled = 0  # columns accumulated across blocks so far
    for block in blocks:
        width = max((len(c) for _, c in block), default=0)
        seen: set[str] = set()
        for name, cells in block:
            if name not in rows:
                stops.append(name)
                rows[name] = [""] * filled
            if len(rows[name]) < filled:
                rows[name] += [""] * (filled - len(rows[name]))
            rows[name] += (cells + [""] * width)[:width]
            seen.add(name)
        for name in stops:  # stops absent in this block: pad the block's columns
            if name not in seen:
                rows[name] += [""] * width
        filled += width

    matrix = [rows[name] for name in stops]
    ncols = filled
    for r in matrix:
        r.extend([""] * (ncols - len(r)))

    active = [
        c for c in range(ncols)
        if any(_parse_cell(matrix[r][c])[0] != "NONE" for r in range(len(matrix)))
    ]

    trips: list[Trip] = []
    for ti, c in enumerate(active):
        cells: list[StopTime] = []
        codes: set[str] = set()
        for r, stop in enumerate(stops):
            raw = matrix[r][c]
            ctype, dt, note = _parse_cell(raw)
            if note:
                codes.add(note)
            cells.append(StopTime(stop, ctype, dt, note, raw))
        trips.append(Trip(ti, sorted(codes), cells))

    return Schedule(
        page_number=page_number,
        direction_index=page_number - 1,
        direction_label=direction_label,
        day_type=_day_type(sec["day_label"]),
        day_label=sec["day_label"],
        section_timetable_number=sec["tt"],
        section_effective_date=sec["eff"],
        no_service=sec["no_service"] or not trips,
        stops=stops,
        trips=trips,
    )


def _parse_page(lines: list[str], page_number: int) -> tuple[list[Schedule], list[Note]]:
    schedules: list[Schedule] = []
    notes: list[Note] = []
    direction_label = ""
    sec: dict | None = None
    in_abbrev = False

    for line in lines:
        st = line.strip()
        if not st or _SEP.match(st):
            continue
        if st.upper().startswith("ABBREVIATIONS"):
            if sec is not None:
                schedules.append(_build_schedule(sec, page_number, direction_label))
                sec = None
            in_abbrev = True
            continue
        if _is_disclaimer(st):
            in_abbrev = False
            continue
        if in_abbrev:
            m = _NOTE.match(st)
            if m:
                notes.append(Note(m.group(1), m.group(2).strip()))
            continue
        if st.startswith("|"):
            if sec is not None:
                sec["rows"].append(st)
            continue
        if _is_section_header(st):
            if sec is not None:
                schedules.append(_build_schedule(sec, page_number, direction_label))
            sec = _new_section(st)
        elif sec is None and not schedules:
            direction_label = (direction_label + " " + st).strip() if direction_label else st

    if sec is not None:
        schedules.append(_build_schedule(sec, page_number, direction_label))
    return schedules, notes


def parse_pdf(path: str) -> ParsedTimetable:
    schedules: list[Schedule] = []
    all_notes: list[Note] = []
    pages_text: list[str] = []

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for pidx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages_text.append(text)
            page_sched, page_notes = _parse_page(text.splitlines(), pidx)
            schedules.extend(page_sched)
            all_notes.extend(page_notes)

    dedup: dict[str, str] = {}
    for n in all_notes:
        dedup.setdefault(n.code, n.description)
    notes = [Note(c, d) for c, d in dedup.items()]

    tt = next((s.section_timetable_number for s in schedules
               if s.section_timetable_number), None)
    return ParsedTimetable(
        timetable_number=tt,
        page_count=page_count,
        raw_text="\n\n".join(pages_text),
        schedules=schedules,
        notes=notes,
    )
