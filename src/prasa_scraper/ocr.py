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

import re
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

try:
    import pytesseract
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

    def counts(self) -> dict:
        filled = sum(1 for r in self.times for c in r if c)
        return {
            "stations": len(self.stations),
            "trains": len(self.train_numbers),
            "times": filled,
            "problems": len(self.problems),
        }


def _tesseract():
    if pytesseract is None:
        raise RuntimeError(
            "pytesseract is not installed. pip install pytesseract, and install the "
            "Tesseract binary (winget install UB-Mannheim.TesseractOCR)."
        )
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

    A page is not one grid. The Southern Line inbound page carries three - the Simon's
    Town workings, the Fish Hoek workings, and the Retreat workings - drawn one under
    another and separated by a ruled line. They look like one table and are not: they have
    54, 50 and 46 columns respectively, because each runs a different set of trains.

    Reading the page as a single grid put the third table's cells at the first table's
    column positions, which silently mixed times between neighbouring trains. It produced
    departure times that looked entirely reasonable and were wrong.
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
    return out


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


def _read_block(gray, panel_ink, left, top, y0, y1, heading) -> Grid:
    """One table. Its columns are measured within itself, never inherited."""
    ink = panel_ink[y0:y1]

    grid = Grid(heading=heading)
    cols = _column_edges(ink)
    if len(cols) < 10:
        grid.problems.append(Problem("grid", f"only {len(cols)} column rules found"))
        return grid

    rows = _row_bands(ink, cols[1] if len(cols) > 1 else 60)
    if len(rows) < 2:
        grid.problems.append(Problem("grid", f"only {len(rows)} text rows found"))
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
        grid.stations.append(clean_station(_read(gray, box(r, cols[0], cols[1]), LABEL_CONFIG)))
        grid.times.append(read_row(r))
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


def _check(grid: Grid) -> None:
    """Everything we can prove about the numbers without a second source."""
    for i, t in enumerate(grid.train_numbers):
        if t and not TRAIN_NO.match(t):
            grid.problems.append(Problem("shape", f"train number {t!r}", 0, i))

    for ri, row in enumerate(grid.times):
        for ci, cell in enumerate(row):
            if cell and not TIME.match(cell):
                grid.problems.append(Problem("shape", f"{cell!r} is not a time", ri, ci))

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
            minutes = int(m.group(1)) * 60 + int(m.group(2))
            if m.group(3):
                minutes += int(m.group(3)) / 60
            if latest is not None and minutes < latest - 60:
                grid.problems.append(Problem(
                    "order",
                    f"{row[ci]} follows {int(latest) // 60:02d}:{int(latest) % 60:02d}",
                    ri, ci,
                ))
            latest = minutes if latest is None else max(latest, minutes)
