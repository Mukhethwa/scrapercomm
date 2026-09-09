"""Read Metrorail timetables from the spreadsheets PRASA publishes.

    PYTHONPATH=src python -m prasa_scraper.sheets --dry-run
    PYTHONPATH=src python -m prasa_scraper.sheets --fresh

PRASA publishes every Cape Town timetable as an .xlsx on

    https://www.prasa.com/train-schedules/cape-town

and the whole OCR pipeline beside this file exists because nobody had found that. Panel
detection, block splitting, column-rule matching, the row threshold, the cell crop insets,
the dropped-hour repair, reading ".." as a colon - all of it is the cost of working from
photographs of these spreadsheets. Here the times are datetime values and the station names
are strings.

So this module is small, and that is the point. It does no guessing, has nothing to check
the reader against, and cannot misread a 7 as a 1. What it does have to handle is the
shape of the sheets, which varies:

    the header row      usually row 3, but Monte Vista Outbound puts PLATFORM NO. above
                        TRAIN NO. and pushes it to row 4
    repeated stations   the Saturday sheets list each station twice, arrival then
                        departure, sometimes marked (A) and (D) and sometimes not
    two spellings       Southern Saturday lists KALKBAAI and KALK BAY as consecutive rows,
                        the same station either side of an arrival/departure pair

Everything after the reading - canonical station names, route naming, day types, what
reaches the database - is the same code the OCR path uses. One source of truth for what a
timetable means, two ways of getting the numbers out.

The OCR pipeline is not obsolete. It reads the PDFs already in data/prasa/pdfs, which are
the only copy of some services, and it is what any operator publishing images will need.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import os
import re

import openpyxl

from . import db_compat as db
from .load import load_page
from .ocr import Grid
from .stations import canonical, key

SHEET_DIR = os.path.join("data", "prasa", "xlsx")

# Rows that head a table rather than name a station.
_HEADER = re.compile(r"TRAIN\s*NO", re.I)
_PLATFORM = re.compile(r"PLATFORM", re.I)

# The lines these sheets cover. Matched against the sheet's title and its filename, most
# specific first, because "Monte Vista (Bellville to cape Town Inbound)" names its line
# and never says the word "Line" - and a pattern general enough to catch that also catches
# "Monte Vista Saturday Bellville to Cape Town" and calls it a line.
_LINES = ("Cape Flats", "Monte Vista", "Southern", "Northern", "Central")


def _text(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _time(value) -> str:
    """
    A cell as the timetable prints it, or empty where no train calls.

    PRASA times its trains to the half minute and the spreadsheet holds real time values,
    so the seconds come through exactly rather than being read off an image. ".." is the
    sheet saying this train does not stop here, which is the same as nothing.
    """
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        value = value.time()
    if isinstance(value, datetime.time):
        return f"{value.hour:02d}:{value.minute:02d}" + (
            f":{value.second:02d}" if value.second else ":00")
    text = _text(value)
    return "" if not any(c.isdigit() for c in text) else text


def line_of(title: str, filename: str) -> str:
    """
    Which line this sheet is for.

    Matched against a list of the lines rather than parsed out of the wording. The sheets
    name themselves five different ways - "Central Line Inbound", "Monte Vista Inbound",
    "Monte Vista (Bellville to cape Town Inbound)", and one whose only text above the
    header is "PLATFORM NO." - and a pattern loose enough to cover all of them produced
    "Monte Vista Saturday Bellville to Cape Town Line". A short list of the five lines is
    both shorter and right.
    """
    haystack = f"{title} {os.path.basename(filename).replace('-', ' ')}"
    for line in _LINES:
        if re.search(re.escape(line), haystack, re.I):
            return f"{line} Line"
    return "Metrorail"


def direction_of(title: str, filename: str) -> str:
    haystack = f"{title} {os.path.basename(filename)}"
    return "OUTBOUND" if re.search(r"OUTBOUND", haystack, re.I) else "INBOUND"


def _same_station(a: str, b: str) -> bool:
    """
    Two consecutive rows naming one station.

    Compared through the same key the rest of the scraper uses, so KALKBAAI and KALK BAY -
    which the Southern Saturday sheet prints as consecutive rows, being the arrival and the
    departure of one call - are recognised as the one station they are.
    """
    strip = lambda n: re.sub(r"\((?:A|D)\)", "", n or "")
    return bool(a) and bool(b) and key(canonical(strip(a))) == key(canonical(strip(b)))


def read_sheet(path: str) -> Grid:
    """One spreadsheet, as the same Grid the OCR path produces."""
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))

    header_at = None
    for i, row in enumerate(rows[:8]):
        label = _text(row[0] if row else "")
        if _HEADER.search(label):
            header_at = i
            break
    if header_at is None:
        raise ValueError(f"no TRAIN NO row in {os.path.basename(path)}")

    # Anything above the header that is not a header is the title and the day type.
    banner = " ".join(_text(r[0]) for r in rows[:header_at]
                      if r and _text(r[0]) and not _PLATFORM.search(_text(r[0])))
    title = banner or os.path.basename(path).replace("-", " ")

    grid = Grid(heading=f"{line_of(banner, path)} {direction_of(banner, path)}")
    # The day type is read from the sheet where it says, and from the filename where it
    # does not: Monte Vista Outbound's only text above the header is "PLATFORM NO.".
    grid.title = f"{banner} {os.path.basename(path).replace('-', ' ')}"
    grid.train_numbers = [_text(v) for v in rows[header_at][1:]]

    for row in rows[header_at + 1:]:
        if not row:
            continue
        label = _text(row[0])
        if not label or _PLATFORM.search(label):
            continue
        times = [_time(v) for v in row[1:]]
        if not any(times):
            continue

        # One call, not two.
        #
        # The Saturday sheets list every station twice - the arrival, then the departure,
        # sometimes marked (A) and (D) and sometimes only by being repeated. Measured
        # across 330 such pairs on the Southern Line, they differ by exactly one minute in
        # 324 and not at all in the other six.
        #
        # Kept as two rows, a twenty-seven station line becomes fifty-four stops, and the
        # app tells a rider their journey has twice the stops it has. One minute is not
        # worth that. The departure is the one kept, because it is the time a train leaves
        # and the time every other timetable prints.
        if grid.stations and _same_station(grid.stations[-1], label):
            grid.stations[-1] = label
            grid.times[-1] = [new or old for new, old in
                              zip(times + [""] * len(grid.times[-1]), grid.times[-1])]
            continue

        grid.stations.append(label)
        grid.times.append(times)
    return grid


def main() -> None:
    ap = argparse.ArgumentParser(description="Load Metrorail timetables from PRASA's spreadsheets")
    ap.add_argument("--dir", default=SHEET_DIR)
    ap.add_argument("--file", help="just this spreadsheet")
    ap.add_argument("--dry-run", action="store_true", help="read and report, write nothing")
    ap.add_argument("--fresh", action="store_true",
                    help="delete every Metrorail route first, so what loads is what these "
                         "sheets say and nothing left over from an earlier reading")
    ap.add_argument("--skip", default="Rugby",
                    help="ignore files whose name contains this; the rugby specials are "
                         "one-off event services, not the published timetable")
    args = ap.parse_args()

    paths = ([os.path.join(args.dir, args.file)] if args.file
             else sorted(glob.glob(os.path.join(args.dir, "*.xlsx"))))
    if args.skip:
        paths = [p for p in paths if args.skip.lower() not in os.path.basename(p).lower()]

    conn = None if args.dry_run else db.connect()
    if conn and args.fresh:
        from .load import forget_everything
        print(f"cleared {forget_everything(conn)['routes']} existing Metrorail routes\n",
              flush=True)

    loaded = 0
    try:
        for path in paths:
            name = os.path.basename(path)
            grid = read_sheet(path)
            counts = grid.counts()
            if args.dry_run:
                print(f"  ok    {name}: {counts['stations']} stations, "
                      f"{counts['trains']} trains, {counts['times']} times "
                      f"[{grid.heading} / {grid.title}]", flush=True)
                loaded += 1
                continue
            wrote = load_page(conn, grid, pdf_path=path, page_number=1)
            print(f"  load  {name}: {wrote['route']} - {wrote['stops']} stops, "
                  f"{wrote['trips']} trips, {wrote['times']} times", flush=True)
            loaded += 1
    finally:
        if conn:
            conn.close()

    print(f"\n{loaded} timetables read")


if __name__ == "__main__":
    main()
