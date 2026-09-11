"""Reading one MyCiTi timetable page.

A page is a grid: stop names down the left, one column per departure, HH:MM in the cells.
Above it sit three lines that say which route, which days and which way:

    101: VREDEHOEK - GARDENS - CIVIC CENTRE (CLOCKWISE)
    MONDAYS TO FRIDAYS  Peak fare period  Saver fare period
    Direction: To 101 Vredehoek

pdfplumber finds the table on its own, which is the whole reason this package is a
hundred lines and the Golden Arrow parser is not. These PDFs are drawn with real ruling
lines; Golden Arrow's are scans of a grid, and PRASA's are images.

WHAT STILL NEEDS CARE.

A direction runs off the end of a page and continues on the next, with THE SAME STOPS and
more departures - route 214a spends three pages on one weekday direction. Read page by
page that is three routes to Marine Circle a day, each with a third of the service. So
pages are grouped by (day type, direction) and their columns joined, and the stop lists
are checked against each other rather than assumed: if they disagree the pages are not
continuations and joining them would invent departures.

Some pages carry two tables. The second is the fare-period legend, which has no times in
it, so the timetable is the one with times rather than the one that comes first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# "05:50", and nothing else. MyCiTi prints no footnote letters and no "via" - a stop a
# departure does not serve is simply blank - so anything that is not a clock is not a time.
TIME = re.compile(r"^([0-2]?\d):([0-5]\d)$")

# "101: VREDEHOEK - GARDENS - CIVIC CENTRE (CLOCKWISE)"
_TITLE = re.compile(r"^\s*([0-9A-Za-z]+)\s*:\s*(.+?)\s*$")

# "Direction: To 101 Vredehoek", "Direction: To T01a Civic Centre"
_DIRECTION = re.compile(r"Direction\s*:\s*(.+?)\s*$", re.I)

# The day a page is for. Ordered longest-first so "SUNDAYS AND PUBLIC HOLIDAYS" is not
# read as "SUNDAYS" with the rest ignored - they are the same day type here, but the
# habit is what keeps PUBLIC_HOLIDAY from being silently lost if MyCiTi ever splits them.
_DAY_TYPES = [
    ("SUNDAYS AND PUBLIC HOLIDAYS", "SUNDAY"),
    ("MONDAYS TO FRIDAYS", "WEEKDAY"),
    ("PUBLIC HOLIDAYS", "PUBLIC_HOLIDAY"),
    ("SATURDAYS", "SATURDAY"),
    ("SUNDAYS", "SUNDAY"),
]


@dataclass
class Page:
    """One page of one timetable, read."""
    number: int
    route: str                      # "101", "T01X"
    title: str                      # "VREDEHOEK - GARDENS - CIVIC CENTRE (CLOCKWISE)"
    day_type: str                   # WEEKDAY | SATURDAY | SUNDAY | PUBLIC_HOLIDAY
    direction: str                  # "To 101 Vredehoek"
    stops: list[str] = field(default_factory=list)
    # One list per stop, holding that stop's time for each departure. Blank where the
    # departure does not call there.
    times: list[list[str]] = field(default_factory=list)

    @property
    def columns(self) -> int:
        return max((len(r) for r in self.times), default=0)


def day_type_of(text: str) -> str | None:
    upper = text.upper()
    for phrase, value in _DAY_TYPES:
        if phrase in upper:
            return value
    return None


def _timetable(tables: list[list[list[str | None]]]) -> list[list[str | None]] | None:
    """
    The table with the departures in it.

    Some pages carry a second, smaller table for the fare-period legend. Picking the
    first would read the legend as a timetable on those pages and the timetable on the
    rest, which is the kind of difference that shows up as one route quietly having no
    service.
    """
    best, best_times = None, 0
    for t in tables:
        n = sum(1 for row in t for cell in row
                if cell and TIME.match(str(cell).strip()))
        if n > best_times:
            best, best_times = t, n
    return best


def read_page(page, number: int) -> Page | None:
    """One pdfplumber page as a Page, or None where there is no timetable on it."""
    lines = [l.strip() for l in (page.extract_text() or "").split("\n") if l.strip()]
    if not lines:
        return None

    title = _TITLE.match(lines[0])
    if not title:
        return None
    route, path = title.group(1).upper(), title.group(2)

    day_type = None
    direction = ""
    for line in lines[1:6]:
        day_type = day_type or day_type_of(line)
        found = _DIRECTION.search(line)
        if found and not direction:
            direction = found.group(1)
    if not day_type:
        return None

    grid = _timetable(page.extract_tables() or [])
    if not grid:
        return None

    out = Page(number=number, route=route, title=path, day_type=day_type,
               direction=direction or f"{route} service")
    for row in grid:
        if not row or not row[0]:
            continue
        name = re.sub(r"\s+", " ", str(row[0])).strip()
        if not name:
            continue
        # Column 1 is the Arr/Dep marker, which says where a vehicle turns round rather
        # than when it is anywhere. It is read and dropped, the same way the PRASA loader
        # drops its A/D column.
        cells = [("" if c is None else re.sub(r"\s+", " ", str(c)).strip())
                 for c in row[2:]]
        out.stops.append(name)
        out.times.append([c if TIME.match(c) else "" for c in cells])
    return out if out.stops else None


def read_pdf(pdf, route_hint: str | None = None) -> list[Page]:
    """Every page of one route's timetable."""
    pages = []
    for i, p in enumerate(pdf.pages, 1):
        read = read_page(p, i)
        if read:
            if route_hint:
                read.route = route_hint
            pages.append(read)
    return pages


@dataclass
class Run:
    """One direction on one kind of day, however many pages it took to print."""
    route: str
    title: str
    day_type: str
    direction: str
    pages: list[int]
    stops: list[str]
    times: list[list[str]]

    @property
    def trips(self) -> int:
        return max((len(r) for r in self.times), default=0)


def _same_stops(a: list[str], b: list[str]) -> bool:
    return [s.upper() for s in a] == [s.upper() for s in b]


def runs(pages: list[Page]) -> tuple[list[Run], list[str]]:
    """
    Pages joined into services, and anything that could not be joined.

    A direction that overflows a page continues on the next with the same stops and more
    departures. Joined on that condition and no other: two pages that disagree about the
    stops are not one service, and pretending otherwise would hang one direction's times
    on another direction's stops.
    """
    out: list[Run] = []
    notes: list[str] = []
    for page in pages:
        joined = False
        for run in out:
            if (run.day_type == page.day_type and run.direction == page.direction
                    and _same_stops(run.stops, page.stops)):
                width = page.columns
                for i, row in enumerate(run.times):
                    row.extend(page.times[i][:width]
                               + [""] * max(0, width - len(page.times[i])))
                run.pages.append(page.number)
                joined = True
                break
        if joined:
            continue
        if any(r.day_type == page.day_type and r.direction == page.direction for r in out):
            # Same heading, different stops. Real on the loop routes, where the outward
            # and return halves are both headed for the same terminus, so it is recorded
            # rather than warned about - but recorded, because a silent mismatch here is
            # how a page of times ends up against the wrong stops.
            notes.append(f"page {page.number}: {page.direction} ({page.day_type}) lists "
                         f"different stops from the earlier page with that heading; "
                         f"kept separate")
        out.append(Run(route=page.route, title=page.title, day_type=page.day_type,
                       direction=page.direction, pages=[page.number],
                       stops=list(page.stops), times=[list(r) for r in page.times]))
    return out, notes
