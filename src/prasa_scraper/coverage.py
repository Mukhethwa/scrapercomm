"""Which stations are printed on the sheets, and which of those a rider can actually find.

    PYTHONPATH=src python -m prasa_scraper.coverage

Every other check in this scraper is internal. Is this cell shaped like a time, does this
column run forwards, do these bands share a column layout - all of them ask whether what
was read is self-consistent, and a table that failed its checks answers all three by
saying nothing at all. From the inside, a page whose grid was never found is
indistinguishable from a page with nothing on it.

That is how KRAAIFONTEIN went missing. It is printed on the Northern Line sheet with
trains from 04:30, the band it sits in was read as a table of its own, and nothing
anywhere noticed that a station on the page had not reached the database. Mukhethwa found
it by remembering a train he catches. That does not scale to the stations nobody on this
project has personally used.

So this reads the source and asks the only question that matters for coverage: is every
station printed on these pages one a rider can search for? It reads the label column only
- a few hundred OCR calls rather than tens of thousands - because the names are the whole
question and the times are not.

It reports two directions, and the second one matters as much as the first:

    missing   printed on a sheet, absent from the database. A station nobody can plan with.
    unprinted in the database, on no sheet. Usually a misread name that became its own
              station, which is the same fault seen from the other side.
"""
from __future__ import annotations

import argparse
import glob
import os

import numpy as np

from . import db_compat as db
from .images import page_images
from .ocr import (LABEL_CONFIG, _blocks, _column_edges, _is_platform_row, _panel, _read,
                  _read_time, _row_bands, clean_station)
from .stations import canonical, key

PDF_DIR = os.path.join("data", "prasa", "pdfs")

# A row of a timetable is a station if it is not one of the two rows that are not.
_NOT_STATIONS = ("TRAIN", "PLATFORM", "NO")


def printed_stations(path: str) -> dict[str, set[int]]:
    """Every station name printed in this PDF, and the pages it appears on."""
    found: dict[str, set[int]] = {}
    for page in page_images(path):
        arr = np.array(page.image.convert("L"))
        left, top, right, bottom = _panel(arr)
        if bottom - top < 50:
            continue
        ink = (arr < 200)[top:bottom, left:right]
        gray = page.image.convert("L")

        for y0, y1 in _blocks(ink):
            band = ink[y0:y1]
            cols = _column_edges(band)
            if len(cols) < 10:
                continue
            rows = _row_bands(band, cols[1] if len(cols) > 1 else 60)
            if len(rows) < 2:
                continue
            for r in rows:
                box = (left + cols[0] + 3, top + y0 + r[0], left + cols[1] - 3, top + y0 + r[1])
                name = clean_station(_read(gray, box, LABEL_CONFIG))
                if not name or any(w in name.upper() for w in _NOT_STATIONS):
                    continue
                # The platform row's label is often unreadable; its cells give it away.
                cells = [_read_time(gray, (left + cols[i] + 3, top + y0 + r[0],
                                           left + cols[i + 1] - 3, top + y0 + r[1]))
                         for i in range(1, min(len(cols) - 1, 6))]
                if _is_platform_row(name, cells):
                    continue
                found.setdefault(canonical(name), set()).add(page.page_number)
    return found


def loaded_stations() -> dict[str, int]:
    """What a rider can search for: station name to id."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.name, s.id FROM stop s JOIN operator o ON o.id = s.operator_id
            WHERE o.code = 'metrorail'
            """
        )
        return {name: sid for name, sid in cur.fetchall()}
    finally:
        conn.close()


def stations_without_departures() -> list[tuple[str, int]]:
    """
    Loaded, searchable, and no use to anybody.

    A station reaches the database as soon as its name is read, whether or not a single
    time in its row survived. A rider searching it then gets a stop that exists and a
    screen that says no service - which looks like the network, and is us.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.name, count(st.id) AS times
            FROM stop s
            JOIN operator o          ON o.id = s.operator_id
            LEFT JOIN schedule_stop ss ON ss.stop_id = s.id
            LEFT JOIN stop_time st     ON st.schedule_stop_id = ss.id
            WHERE o.code = 'metrorail'
            GROUP BY s.name
            HAVING count(st.id) = 0
            ORDER BY s.name
            """
        )
        return [(name, int(times)) for name, times in cur.fetchall()]
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare the printed stations with the loaded ones")
    ap.add_argument("--dir", default=PDF_DIR)
    ap.add_argument("--pdf", help="just this file")
    args = ap.parse_args()

    paths = ([os.path.join(args.dir, args.pdf)] if args.pdf
             else sorted(glob.glob(os.path.join(args.dir, "*.pdf"))))

    loaded = loaded_stations()
    loaded_keys = {key(n) for n in loaded}
    printed: dict[str, set[str]] = {}

    for path in paths:
        name = os.path.basename(path)
        pages = printed_stations(path)
        print(f"\n{name}: {len(pages)} stations printed", flush=True)
        missing = sorted(s for s in pages if key(s) not in loaded_keys)
        for station in missing:
            where = ", ".join(f"p{p}" for p in sorted(pages[station]))
            print(f"  MISSING  {station}  ({where})", flush=True)
        if not missing:
            print("  every station on these pages is loaded", flush=True)
        for station in pages:
            printed.setdefault(key(station), set()).add(name)

    # The other direction. A station in the database that appears on no sheet is usually a
    # name read badly enough to become a station of its own - the same fault as a missing
    # one, seen from the other side, and just as invisible without asking.
    unprinted = sorted(n for n in loaded if key(n) not in printed)
    print(f"\n{len(loaded)} stations loaded, {len(printed)} distinct names printed")
    if unprinted:
        print("in the database but on no sheet:")
        for n in unprinted:
            print(f"  UNPRINTED  {n} (id {loaded[n]})")
    else:
        print("every loaded station appears on a sheet")

    idle = stations_without_departures()
    if idle:
        print(f"\nloaded but with no departures at all ({len(idle)}):")
        for name, _ in idle:
            print(f"  NO SERVICE  {name}")
    else:
        print("every loaded station has at least one departure")


if __name__ == "__main__":
    main()
