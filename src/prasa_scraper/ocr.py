"""Read a timetable image into a grid, and refuse to believe it without checking.

Whole-page OCR of these images reaches about 98%, which is not good enough. The failures
are systematic - the leading 1 of an 11:xx hour drops, colons vanish - and two per cent of
a thousand departure times is twenty wrong answers presented to a rider as fact.

Three things make it trustworthy instead:

  the grid          the columns are ruled, so each cell is cut out and read on its own
                    rather than letting Tesseract guess where one time ends and the next
                    begins
  a whitelist       a cell can only contain digits and a colon, which is what stopped
                    train number 0100 being read as "otoo"
  the check         a train moves forwards, so its times increase down its own column.
                    Nothing else about the data is known, but that is enough: every
                    dropped-digit error breaks it and gets flagged

Cells that fail either check are returned as problems rather than silently dropped or
silently kept, because a missing train is a visible bug and a wrong time is not.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

try:
    import pytesseract

    if os.environ.get("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
except ImportError:      # pragma: no cover - the module is importable without OCR present
    pytesseract = None

# Trains are timed to the half minute, and PRASA prints that: the weekday sheets say
# 05:25 but the weekend sheets say 05:25:00 and 04:48:30. The seconds are real data - a
# train really does pass at 48 and a half minutes past - so they are read and kept, not
# trimmed off to fit a tidier pattern.
TIME = re.compile(r"^([0-2]?\d):([0-5]\d)(?::([0-5]\d))?$")

# What a station cell picks up besides the station.
#
# The A/D marker sits in a narrow column right of the name, and the rule between them
# reads as a stray letter - "FISH HOEK" came back as "FISH HOEK LA" and "SIMON'S TOWN" as
# "SIMON'S TOWN | D". Left in, those became part of the route name.
# The separator before the marker is required, not optional: without it the trailing D
# of "HARFIELD ROAD" is a marker and the station becomes "HARFIELD ROA".
# A trailing fragment of at most three characters, drawn only from what the marker
# column and the rule beside it can produce: the letters A and D, the shapes a thin
# rule is read as, and brackets. "RETREAT I)" is that fragment with the marker itself
# misread; "HARFIELD ROAD" is not, because ROAD is four characters of real name.
_MARKER_TAIL = re.compile(r"\s+[AD|lI1()\[\].]{1,3}\s*$", re.I)
# PRASA prints every time zero-padded - 04:25, 05:30, never 4:25. So a single-digit hour is
# not a valid reading of one of these cells, it is a dropped digit, and the crop that
# produced it should be rejected in favour of one that reads all four.
PADDED_TIME = re.compile(r"^([0-2]\d):([0-5]\d)(?::([0-5]\d))?$")
TRAIN_NO = re.compile(r"^\d{3,4}$")

# A cell holds a time or a train number, and nothing else.
CELL_CONFIG = "--psm 7 -c tessedit_char_whitelist=0123456789:"
# Station names are words; they get their own pass.
#
# psm 11 - sparse text - rather than 7. Treating the cell as one tight line joins the
# longest name on the sheet: "HARFIELD ROAD" comes back as "HARFIELDROAD", which is then
# a station nobody can search for. Sparse mode reads the two words apart, and is
# identical to psm 7 on every other label on the page.
LABEL_CONFIG = "--psm 11"

# The width these thresholds were measured at. PRASA does not render every page at the
# same size - the Central Line's later pages come out at 4358px against the usual 3250 -
# so the pixel distances below are scaled to whatever a page actually is. Measured in
# absolute pixels they were too small on the larger pages, and those pages failed
# detection outright.
REFERENCE_WIDTH = 3250

# Both conditions matter, because neither alone separates a table from the page's own
# furniture. On the Southern Line's weekend sheets the title bar and footer measure 40 to
# 104 pixels with 0 or 1 column rules; the shallowest real table - a three-station branch
# working - is 92 pixels, the same height, but has 24. A tall band with no columns is the
# Central Line's blue sheets, which is a detection failure worth reporting, not furniture.
MIN_TABLE_HEIGHT = 150


def _scale(width: int) -> float:
    return max(0.5, width / REFERENCE_WIDTH)


# Below this share of dark pixels a cell is the ".." filler - the train does not call
# there - and is worth no OCR call.
#
# Measured rather than guessed: on these sheets a cell holding a time carries 0.118 or
# more, and a ".." carries about 0.023. The first floor tried was 0.02, which let the
# dots through, and once in a while Tesseract turned one into a stray "5" that then had
# to be flagged. 0.06 sits in the empty gap between the two populations.
INK_FLOOR = 0.06


@dataclass
class Problem:
    kind: str          # 'shape' | 'order' | 'grid'
    detail: str
    row: int = -1
    column: int = -1


@dataclass
class Grid:
    """A timetable page, read."""
    heading: str
    # The banner printed on the image itself, e.g. "SOUTHERN LINE WEEKEND INBOUND
    # TIMETABLE : OCTOBER 2025". The PDF text layer does not carry it, and it is the only
    # place a page says which days it is for.
    title: str = ""
    stations: list[str] = field(default_factory=list)
    train_numbers: list[str] = field(default_factory=list)
    # times[row][column], '' where the train does not call there.
    times: list[list[str]] = field(default_factory=list)
    # Where each cell was on the page, so a flagged one can be re-read rather than guessed.
    boxes: list[list[tuple[int, int, int, int]]] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def unverified(self) -> set[tuple[int, int]]:
        """
        Which cells the checks could not vouch for, as (row, column).

        A cell that failed its shape check is already refused at load time - it is not a
        time, so there is nothing to insert. A cell that failed the ordering check is the
        dangerous one: 07:11 where the sheet says 17:11 is a perfectly well-formed time
        and a train a rider would miss by ten hours. Naming the flagged cells lets a
        forced load drop exactly those and keep the rest of a table that is otherwise
        sound, instead of choosing between all of it and none of it.
        """
        return {(p.row, p.column) for p in self.problems
                if p.row >= 0 and p.column >= 0}

    def counts(self) -> dict:
        filled = sum(1 for r in self.times for c in r if c)
        return {
            "stations": len(self.stations),
            "trains": len(self.train_numbers),
            "times": filled,
            "problems": len(self.problems),
        }


# Where the Windows installer puts Tesseract. It does not add itself to PATH, so a
# perfectly good installation is invisible to a shell that was not told about it.
_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""),
                 "Programs", "Tesseract-OCR", "tesseract.exe"),
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)

_checked = False


def _tesseract():
    """
    The OCR engine, or a refusal to start.

    Checked once, up front, and loudly. Every cell read is wrapped in a broad except so
    that one failed call costs that cell rather than a three-hour run - which means a
    missing binary would otherwise return an empty string forty thousand times and the
    pipeline would report "nothing timetable-shaped here" on page after page of perfectly
    legible timetables. A missing installation and a blank page would look identical, and
    the wrong one of those is easy to fix.
    """
    global _checked
    if pytesseract is None:
        raise RuntimeError(
            "pytesseract is not installed. pip install pytesseract, and install the "
            "Tesseract binary (winget install UB-Mannheim.TesseractOCR)."
        )
    if not _checked:
        if shutil.which(pytesseract.pytesseract.tesseract_cmd) is None:
            found = next((p for p in _TESSERACT_PATHS if p and os.path.isfile(p)), None)
            if found is None:
                raise RuntimeError(
                    "Tesseract is installed as a Python wrapper but the engine itself "
                    "cannot be found. Install it (winget install UB-Mannheim.TesseractOCR),"
                    " or point TESSERACT_CMD at the binary."
                )
            pytesseract.pytesseract.tesseract_cmd = found
        _checked = True
    return pytesseract


def _panel(gray: np.ndarray) -> tuple[int, int, int, int]:
    """The white table panel inside the red page border."""
    white = gray > 235
    rows, cols = white.mean(axis=1), white.mean(axis=0)
    top = int(np.argmax(rows > 0.5))
    bottom = gray.shape[0] - int(np.argmax(rows[::-1] > 0.5))
    left = int(np.argmax(cols > 0.5))
    right = gray.shape[1] - int(np.argmax(cols[::-1] > 0.5))
    return left, top, right, bottom


def _column_edges(ink: np.ndarray, min_gap: int | None = None) -> list[int]:
    """
    X positions of the ruled vertical lines, held to the spacing the table actually uses.

    Density alone is not enough to tell a rule from a coincidence. In a block only eight
    rows deep, the digits stack: the second character of 05:00, 05:04, 05:06 and their
    neighbours line up into a stripe as dark as a real rule, and an edge lands inside the
    cell. The time then reads as "05:" and the checker rejects a perfectly good cell.

    The columns are evenly spaced by construction, so the spacing settles it. The most
    common gap is the true column width; edges that do not sit on that lattice are the
    accidents and are dropped. Narrow structural columns before the data - the station
    name, the A/D marker - are kept as found, because they are genuinely not on it.
    """
    if min_gap is None:
        min_gap = max(6, int(12 * _scale(ink.shape[1])))
    profile = ink.mean(axis=0)
    hits = np.where(profile > 0.55)[0]
    found: list[int] = []
    for h in hits:
        if not found or h - found[-1] > min_gap:
            found.append(int(h))
    if len(found) < 6:
        return found

    gaps = [b - a for a, b in zip(found, found[1:])]
    wide = [g for g in gaps if g >= 30]
    if not wide:
        return found
    pitch = int(np.median(wide))
    tolerance = max(6, pitch // 5)

    # Walk from the right, where the last column edge is always a real rule, and keep only
    # the edges that fall a pitch apart.
    kept = [found[-1]]
    for x in reversed(found[:-1]):
        if kept[-1] - x >= pitch - tolerance:
            kept.append(x)
    kept.reverse()

    # Anything to the left of the first data column is structural, not on the lattice.
    head = [x for x in found if x < kept[0]]
    return head + kept


def _row_bands(ink: np.ndarray, label_width: int) -> list[tuple[int, int]]:
    """
    Y extents of each text row.

    Rows carry no ruled line between them, so they are found by their text: a band of ink
    in the station-name column is a row. The band is then grown to the midpoint of the gap
    on either side, because the times beside a label sit slightly taller than it and
    cropping to the label's own height slices the tops off the digits.
    """
    profile = ink[:, :label_width].mean(axis=1)

    # The threshold has to be measured, not chosen.
    #
    # The gap between two rows is not blank: the ruled column edges pass through it, so it
    # carries a low but non-zero amount of ink - 0.044 on the Southern Line against 0.11 to
    # 0.24 for a row of text. A fixed 0.02 called the gaps text and merged an entire table
    # into one band, which is why the Simon's Town workings were silently skipped.
    #
    # Sitting the threshold a third of the way from the quiet level to the busy one
    # separates them on every line, whatever the rules happen to weigh.
    floor = float(np.percentile(profile, 20))
    peak = float(np.percentile(profile, 90))
    threshold = floor + 0.35 * (peak - floor) if peak > floor else 0.02
    inked = profile > threshold
    min_band = max(6, int(10 * _scale(ink.shape[1])))
    bands: list[tuple[int, int]] = []
    start = None
    for y, on in enumerate(inked):
        if on and start is None:
            start = y
        elif not on and start is not None:
            if y - start >= min_band:
                bands.append((start, y))
            start = None
    if start is not None and len(inked) - start >= min_band:
        bands.append((start, len(inked)))

    grown: list[tuple[int, int]] = []
    for i, (y0, y1) in enumerate(bands):
        above = bands[i - 1][1] if i else max(0, y0 - 14)
        below = bands[i + 1][0] if i + 1 < len(bands) else min(len(inked), y1 + 14)
        grown.append(((y0 + above) // 2, (y1 + below) // 2))
    return grown


def _read(img: Image.Image, box: tuple[int, int, int, int], config: str) -> str:
    x0, y0, x1, y1 = box
    if x1 - x0 < 8 or y1 - y0 < 8:
        return ""
    crop = img.crop(box)
    if (np.array(crop) < 128).mean() < INK_FLOOR:
        return ""
    # Tesseract reads small type better when it is not small.
    bigger = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
    try:
        return _tesseract().image_to_string(bigger, config=config).strip()
    except RuntimeError:
        raise
    except Exception:      # noqa: BLE001
        # A run over these PDFs is tens of thousands of Tesseract calls and takes hours.
        # One of them failing - a temp file it could not write, a process killed - should
        # cost that cell, not the whole run. An empty read becomes a flagged cell further
        # down, which is visible; a crash three hours in is just lost work.
        return ""


# How far inside the ruled edges to cut a time cell. Tried in order.
CELL_INSETS = (0, 3, 2, 5)


def _read_time(img: Image.Image, box: tuple[int, int, int, int], inset_from: int = 3) -> str:
    """
    A time cell, read at several crops until one of them is a time.

    The margin matters far more than it should. "11:11" cut three pixels inside its rules
    reads as "1:11" - Tesseract drops one of four identical strokes - and cut flush to the
    rules it reads correctly. Two pixels the other way and it returns a bare "1". There is
    no single right inset, so several are tried and the first that yields a valid time
    wins.

    This is not guessing. Every candidate is the same cell, and only a reading that is
    actually a time is accepted; if none is, the last attempt is returned as-is so the
    checker can flag it.
    """
    x0, y0, x1, y1 = box
    base_left, base_right = x0 - inset_from, x1 + inset_from
    last = ""
    for inset in CELL_INSETS:
        b = (base_left + inset, y0, base_right - inset, y1)
        if b[2] - b[0] < 8:
            continue
        got = _read(img, b, CELL_CONFIG)
        if got and PADDED_TIME.match(got):
            return got
        last = got or last
    return last


def _blocks(ink: np.ndarray) -> list[tuple[int, int]]:
    """
    The y ranges of the separate tables stacked on one page.

    A page is not always one grid. The Southern Line inbound page carries three - the
    Simon's Town workings, the Fish Hoek workings, and the Retreat workings - drawn one
    under another and separated by a ruled line. They look like one table and are not:
    they have 54, 50 and 46 columns respectively, because each runs a different set of
    trains. Reading that page as a single grid put the third table's cells at the first
    table's column positions, silently mixing times between neighbouring trains, and
    produced departure times that looked entirely reasonable and were wrong.

    But a ruled line is not what makes two tables. The Northern Line page is divided by
    five rules into groups of stations - the Wellington branch, the Kraaifontein branch,
    the Stellenbosch branch, the Strand branch, and then everything from Bellville into
    town - and all five have the same 41 columns, because it is one timetable and those
    are the same 41 trains. Train 2500 leaves KRAAIFONTEIN at 04:30 and reaches CAPE TOWN
    at 05:45, crossing four of those rules on the way.

    Split there, it stopped being a journey. It became a route from Kraaifontein to
    Stikland and an unrelated one from Bellville to Cape Town, and a rider asking to go
    from Kraaifontein into the city was told no train does it. That is what sent Mukhethwa
    looking for a station he catches trains from.

    So the rule is the column layout, which is what actually distinguishes one table from
    another, and not the ink between the rows.
    """
    profile = ink.mean(axis=1)
    gap = max(5, int(8 * _scale(ink.shape[1])))
    min_table = max(24, int(40 * _scale(ink.shape[1])))
    rules, last = [], -99
    for y in np.where(profile > 0.55)[0]:
        if y - last > gap:
            rules.append(int(y))
            last = int(y)
    edges = [0] + rules + [ink.shape[0]]
    bands = list(zip(edges, edges[1:]))

    # A band too short to hold a table is a header, and it belongs to the table under it.
    #
    # The train numbers sit in their own 27px strip above the first rule. Dropped, the top
    # table lost its train numbers entirely; promoted to a table of its own, it became a
    # phantom with no stations. It is neither - it is the head of the block below, and it
    # shares that block's column layout, which is what makes merging safe.
    out: list[tuple[int, int]] = []
    carry: int | None = None
    for a, b in bands:
        if b - a < min_table:
            if carry is None:
                carry = a
            continue
        out.append((carry if carry is not None else a, b))
        carry = None

    return _merge_shared_columns(ink, out)


# How much of two bands' column rules must line up for them to be one table. High enough
# that two tables drawn for different numbers of trains never reach it - their rules fall
# at different pitches, so almost nothing lines up - and forgiving enough to survive a
# rule found in one band and missed in the other.
COLUMN_AGREEMENT = 0.9


def _same_columns(a: list[int], b: list[int], tol: int) -> bool:
    """
    Do two bands stand on the same column rules?

    Matched as sets rather than pairwise down the list. The edges come from a threshold
    over each band's own ink, and a band with denser text picks up a rule its neighbour
    misses - the Northern Line page reads 41 columns in one band and 42 in the next, off
    the same printed grid. Compared position by position, one extra edge at the front
    shifts every later comparison by a whole column, and two bands whose rules sit exactly
    on top of each other reported a 46-pixel disagreement.

    That is how Kraaifontein stayed lost after I thought I had found it: I checked the
    merge against an ink threshold the reader does not use, saw one clean band, and
    believed it.
    """
    if not a or not b:
        return False
    # A rule or two more in one band than the other is a threshold artefact. Many more is
    # a different table, drawn for a different set of trains.
    if abs(len(a) - len(b)) > 2:
        return False
    hits_a = sum(1 for x in a if any(abs(x - y) <= tol for y in b))
    hits_b = sum(1 for y in b if any(abs(x - y) <= tol for x in a))
    return (hits_a >= COLUMN_AGREEMENT * len(a)
            and hits_b >= COLUMN_AGREEMENT * len(b))


def _merge_shared_columns(ink: np.ndarray, bands: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Join neighbouring bands that are the same table, divided only by a rule."""
    if len(bands) < 2:
        return bands
    tol = max(3, int(6 * _scale(ink.shape[1])))
    edges = [_column_edges(ink[a:b]) for a, b in bands]

    merged: list[tuple[int, int]] = []
    current, current_edges = bands[0], edges[0]
    for band, cols in zip(bands[1:], edges[1:]):
        if _same_columns(current_edges, cols, tol):
            current = (current[0], band[1])
            # Keep the layout of the run's first band. Re-measuring the joined band would
            # be the same rules read again; what matters is that the next one matches.
        else:
            merged.append(current)
            current, current_edges = band, cols
    merged.append(current)
    return merged


def clean_station(raw: str) -> str:
    """A station name with the marker column's leavings taken off it."""
    # Sparse mode puts the marker on its own line; flatten before anything else.
    name = " ".join((raw or "").split()).split("|")[0]
    name = _MARKER_TAIL.sub("", name)
    return " ".join(name.split()).strip(" .-")


def read_page(image: Image.Image, heading: str = "") -> list[Grid]:
    """Every table on one page image, each read and checked on its own terms."""
    gray = image.convert("L")
    arr = np.array(gray)
    left, top, right, bottom = _panel(arr)
    ink = (arr < 200)[top:bottom, left:right]
    title = _read_title(gray, top)
    out = []
    for (y0, y1) in _blocks(ink):
        grid = _read_block(gray, ink, left, top, y0, y1, heading)
        grid.title = title
        out.append(grid)
    return [g for g in out if g.stations or g.problems]


def _read_title(gray: Image.Image, panel_top: int) -> str:
    """
    The banner above the table.
    
    Worth one OCR call per page because of what it settles: the Southern Line file is
    named "weekday" and page 4 of it is headed "SOUTHERN LINE WEEKEND INBOUND TIMETABLE".
    Trusting the filename would have loaded a Saturday service as a weekday one.
    """
    if panel_top < 20:
        return ""
    band = gray.crop((0, 0, gray.width, panel_top))
    # White text on the red banner: invert so Tesseract sees dark on light.
    inverted = Image.eval(band, lambda v: 255 - v)
    try:
        return " ".join(_tesseract().image_to_string(
            inverted, config="--psm 6").split())
    except Exception:      # noqa: BLE001 - a missing banner is not a failure
        return ""


# What a platform number looks like: one or two digits, and never a clock.
_PLATFORM_NO = re.compile(r"^\d{1,2}$")


def _is_platform_row(label: str, cells: list[str]) -> bool:
    """
    Is this the PLATFORM NO row rather than a station?

    Both halves have to agree, because either alone is too eager. A label read as
    "PLATFORM NO" is the clear case, but OCR mangles it as readily as anything else - and
    a row of bare digits where a row of times belongs is the same fact stated by the data.
    Requiring the label to look like a platform heading OR the row to be entirely small
    integers, with at least a few of them, keeps a station whose times were badly read
    from being silently discarded as furniture.
    """
    if "PLATFORM" in (label or "").upper():
        return True
    filled = [c for c in cells if c]
    if len(filled) < 3:
        return False
    return all(_PLATFORM_NO.match(c) for c in filled)


def _read_block(gray, panel_ink, left, top, y0, y1, heading) -> Grid:
    """One table. Its columns are measured within itself, never inherited."""
    ink = panel_ink[y0:y1]

    grid = Grid(heading=heading)
    cols = _column_edges(ink)
    if len(cols) < 10:
        # No columns at all, on a band too shallow to hold a timetable, is the page's own
        # furniture: the red title bar at the top and the operator logos at the foot are
        # both split off as blocks. Calling those failed tables made a fully-read page
        # report two failures out of four blocks, and I read that as lost services and
        # went looking for a coverage problem that was not there.
        #
        # A real table is many rows deep. Anything under a few is not one, and saying so
        # is not the same as passing over a grid that could not be found.
        if len(cols) < 3 and (y1 - y0) < MIN_TABLE_HEIGHT:
            return grid
        grid.problems.append(Problem("grid", f"only {len(cols)} column rules found"))
        return grid

    rows = _row_bands(ink, cols[1] if len(cols) > 1 else 60)
    if len(rows) < 2:
        # A single row of text under a full set of column rules is the "TRAIN NO." strip
        # that _blocks failed to fold into the table beneath it. That is not a table which
        # could not be read - it is a table's header that ended up on its own - and
        # calling it a failure mixed a small, specific loss in with the serious ones.
        #
        # The loss is real though: the numbers in that strip are what a platform indicator
        # shows, and without the strip the trips below it load unlabelled. Its own kind,
        # so the run log can say which of those two things happened.
        grid.problems.append(Problem("header", f"train numbers not read ({len(rows)} rows)"))
        return grid
    top = top + y0

    def box(r: tuple[int, int], c0: int, c1: int, pad: int = 3):
        return (left + c0 + pad, top + r[0], left + c1 - pad, top + r[1])

    def read_row(r):
        return [_read_time(gray, box(r, cols[i], cols[i + 1]))
                for i in range(1, len(cols) - 1)]

    # Find the train-number row rather than assuming it is the first.
    #
    # It usually is, but not on every line: some pages carry a spanning title band above
    # it. Assuming position put the train numbers into the body, where every one of them
    # was then reported as "not a time" - the checker doing its job about the wrong row.
    # The header is the row whose cells are train numbers and never times.
    header_index, header_cells = -1, None
    for i, r in enumerate(rows[:2]):
        cells = read_row(r)
        filled = [c for c in cells if c]
        if not filled:
            continue
        if all(TRAIN_NO.match(c) for c in filled) and not any(TIME.match(c) for c in filled):
            header_index, header_cells = i, cells
            break
    if header_cells is None:
        # Only the first table on a page prints the train numbers; the ones below reuse
        # the header above them visually but not structurally. Left empty rather than
        # borrowed, because borrowing would put the wrong number against a train.
        header_index, header_cells = -1, []
    grid.train_numbers = header_cells

    for ri, r in enumerate(rows[header_index + 1:], start=header_index + 1):
        label = clean_station(_read(gray, box(r, cols[0], cols[1]), LABEL_CONFIG))
        cells = read_row(r)

        # Not every row of a timetable is a station.
        #
        # The Northern Line prints a PLATFORM NO row in the middle of the page, where
        # Bellville's arrivals become its departures. Its cells hold "5", "10", "3" - real
        # information, and not times. Once neighbouring bands are joined into the one
        # table they belong to, that row lands in the body, and every cell in it was
        # reported as a cell that should have been a time and was not. Forty complaints
        # about a row that is doing exactly what it is printed to do.
        if _is_platform_row(label, cells):
            continue

        grid.stations.append(label)
        grid.times.append(cells)
        grid.boxes.append([box(r, cols[i], cols[i + 1]) for i in range(1, len(cols) - 1)])

    _check(grid)
    _second_look(grid, gray)
    return grid


def _second_look(grid: Grid, gray: Image.Image) -> None:
    """
    Read the flagged cells again, larger, before giving up on them.

    Most of what survives the first pass is one of two confusions: the leading 1 of an
    11:xx hour lost, or a 0 read as a 9. Both are legibility problems rather than
    ambiguity in the source - the cell really does say what it says - so looking again at
    six times the size, with the line treated as a single word, usually settles it.

    A re-read is only accepted if it is a valid time AND the column then runs forwards.
    Nothing is inferred from its neighbours: a plausible time invented to fill a gap is
    exactly the failure this whole module exists to avoid.
    """
    if not grid.problems:
        return
    suspect = {(p.row, p.column) for p in grid.problems if p.kind in ("shape", "order")}
    changed = False
    for (ri, ci) in suspect:
        if ri < 0 or ri >= len(grid.boxes) or ci < 0 or ci >= len(grid.boxes[ri]):
            continue
        crop = gray.crop(grid.boxes[ri][ci])
        if crop.width < 8 or crop.height < 8:
            continue
        bigger = crop.resize((crop.width * 6, crop.height * 6), Image.LANCZOS)
        for config in ("--psm 8 -c tessedit_char_whitelist=0123456789:",
                       "--psm 13 -c tessedit_char_whitelist=0123456789:"):
            again = _tesseract().image_to_string(bigger, config=config).strip()
            if again and TIME.match(again) and again != grid.times[ri][ci]:
                grid.times[ri][ci] = again
                changed = True
                break

    if changed:
        grid.problems.clear()
        _check(grid)

    _restore_dropped_hour(grid)


def _column_bounds(grid: Grid, ri: int, ci: int) -> tuple[float | None, float | None]:
    """
    The nearest trustworthy times above and below a cell, in minutes.

    PADDED_TIME rather than TIME: a neighbour that is itself missing an hour digit cannot
    be used to prove anything, and two damaged cells in a row would otherwise agree with
    each other into a confident wrong answer.
    """
    before = after = None
    for r in range(ri - 1, -1, -1):
        m = PADDED_TIME.match(grid.times[r][ci] if ci < len(grid.times[r]) else "")
        if m:
            before = _minutes(m)
            break
    for r in range(ri + 1, len(grid.times)):
        m = PADDED_TIME.match(grid.times[r][ci] if ci < len(grid.times[r]) else "")
        if m:
            after = _minutes(m)
            break
    return before, after


def _restore_dropped_hour(grid: Grid) -> None:
    """
    Put back a leading hour digit the reader dropped, where the column proves which.

    PRASA pads its hours: the sheets print 05:25, never 5:25. So a cell that came back
    with a single-digit hour is not a time PRASA printed - it is a two-digit hour with
    the first digit lost, and there are exactly two candidates, 0x and 1x. That is not a
    guess to fill a gap; the minutes were read, and the tens digit has two possible
    values rather than ten.

    Which one is settled by the column, not chosen for plausibility. A train runs
    forwards, so the reading has to sit between the published time above it and the one
    below. If both candidates fit, or neither does, nothing is written and the cell stays
    flagged - the whole point of the checks is that an unproven time is worse than none.

    This is what was holding whole tables back. One cell read as "7:11" in a column that
    had reached 17:09 held 304 verified times off the site, and "5:27:00" under 15:18
    held another 30.
    """
    suspect = {(p.row, p.column) for p in grid.problems if p.kind in ("order", "shape")}
    for ri, ci in sorted(suspect):
        if ri < 0 or ci < 0 or ri >= len(grid.times) or ci >= len(grid.times[ri]):
            continue
        cell = grid.times[ri][ci]
        m = TIME.match(cell or "")
        if not m or len(m.group(1)) != 1:
            continue          # a padded hour is what the sheet prints; nothing was lost

        before, after = _column_bounds(grid, ri, ci)
        fits = []
        for tens in ("0", "1"):
            candidate = tens + cell
            cm = TIME.match(candidate)
            if not cm:
                continue
            mins = _minutes(cm)
            if before is not None and mins < before:
                continue
            if after is not None and mins > after:
                continue
            fits.append(candidate)

        if len(fits) == 1:
            grid.times[ri][ci] = fits[0]

    if grid.problems:
        grid.problems.clear()
        _check(grid)


def _minutes(m: re.Match) -> float:
    """A matched time as minutes past midnight, seconds included."""
    total = int(m.group(1)) * 60 + int(m.group(2))
    return total + int(m.group(3)) / 60 if m.group(3) else total


def _check(grid: Grid) -> None:
    """Everything we can prove about the numbers without a second source."""
    for i, t in enumerate(grid.train_numbers):
        if t and not TRAIN_NO.match(t):
            grid.problems.append(Problem("shape", f"train number {t!r}", 0, i))

    for ri, row in enumerate(grid.times):
        for ci, cell in enumerate(row):
            if not cell:
                continue
            m = TIME.match(cell)
            if not m:
                grid.problems.append(Problem("shape", f"{cell!r} is not a time", ri, ci))
            elif len(m.group(1)) == 1:
                # PRASA prints 05:25, never 5:25, so an unpadded hour is a digit the
                # reader lost rather than a time the sheet published. Flagged wherever it
                # appears, not only where it breaks the column: in a sparse column 07:11
                # for 17:11 offends no ordering and would have loaded as a train ten
                # hours early. Most of these are then repaired outright - see
                # _restore_dropped_hour - and what is left stays flagged and unwritten.
                grid.problems.append(
                    Problem("shape", f"{cell!r} has an unpadded hour", ri, ci))

    # A train runs forwards. Anything that goes back more than an hour is a misread, not a
    # service crossing midnight - these are weekday daytime timetables.
    width = max((len(r) for r in grid.times), default=0)
    for ci in range(width):
        latest = None
        for ri, row in enumerate(grid.times):
            if ci >= len(row):
                continue
            m = TIME.match(row[ci] or "")
            if not m:
                continue
            minutes = _minutes(m)
            if latest is not None and minutes < latest - 60:
                grid.problems.append(Problem(
                    "order",
                    f"{row[ci]} follows {int(latest) // 60:02d}:{int(latest) % 60:02d}",
                    ri, ci,
                ))
            latest = minutes if latest is None else max(latest, minutes)
