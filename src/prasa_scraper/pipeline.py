"""Read PRASA PDFs and load what checks out.

    PYTHONPATH=src python -m prasa_scraper.pipeline                 # everything
    PYTHONPATH=src python -m prasa_scraper.pipeline --pdf southern-line-weekday.pdf
    PYTHONPATH=src python -m prasa_scraper.pipeline --page 2 --dry-run

A page carries several tables, each read and checked on its own. One that fails its checks
is reported and held back, because the entire point of the checks is that times nobody has
looked at do not silently become departure times a rider trusts. --force loads anyway, for
when the problems have been reviewed and are understood.

A cell the checks flagged is never written, under --force or otherwise, so the question a
hold actually decides is whether an imperfect table is worth having at all. All-or-nothing
answered that badly at the margins: one unreadable cell out of 737 was hiding 24 stations
and a full day of service. --allow-unverified loads a table whose flagged cells are under
some share of it - those cells still do not load, so the affected stop reads as having no
published time rather than a wrong one.

Three per cent, measured rather than picked. Across the five PDFs the held tables fall in
two groups with nothing between them: three at 1.2, 1.9 and 2.8 per cent, then the next at
5.9 and up through 86. The first group is a table that read cleanly with a few cells of
noise in it; the second is a table that did not read. One per cent, which is what I chose
first, cut through the middle of the good group and held the Northern Line page - the one
with KRAAIFONTEIN on it - over 7 bad cells out of 601.

    PYTHONPATH=src python -m prasa_scraper.pipeline --allow-unverified 3
"""
from __future__ import annotations

import argparse
import glob
import os

from . import db_compat as db
from .images import page_images
from .load import load_page
from .ocr import read_page

PDF_DIR = os.path.join("data", "prasa", "pdfs")


def main() -> None:
    ap = argparse.ArgumentParser(description="Load Metrorail timetables from PRASA PDFs")
    ap.add_argument("--dir", default=PDF_DIR)
    ap.add_argument("--pdf", help="just this file")
    ap.add_argument("--page", type=int, help="just this page number")
    ap.add_argument("--dry-run", action="store_true", help="read and check, write nothing")
    ap.add_argument("--force", action="store_true", help="load tables that failed their checks")
    ap.add_argument("--fresh", action="store_true",
                    help="delete every Metrorail route first, so a page read differently "
                         "than last time leaves nothing of the old reading behind")
    ap.add_argument("--allow-unverified", type=float, default=0.0, metavar="PCT",
                    help="load a table if at most PCT%% of its cells are unverified; "
                         "those cells are still not written. 3 is the measured line "
                         "between a table that read and one that did not")
    args = ap.parse_args()

    paths = ([os.path.join(args.dir, args.pdf)] if args.pdf
             else sorted(glob.glob(os.path.join(args.dir, "*.pdf"))))

    conn = None if args.dry_run else db.connect()
    if conn and args.fresh:
        from .load import forget_everything
        gone = forget_everything(conn)
        print(f"cleared {gone['routes']} existing Metrorail routes")
        print(flush=True)
    loaded = held = skipped = 0
    try:
        for path in paths:
            for page in page_images(path):
                if args.page and page.page_number != args.page:
                    continue
                for index, grid in enumerate(read_page(page.image, page.heading), 1):
                    label = f"{os.path.basename(path)} p{page.page_number}.{index}"
                    counts = grid.counts()

                    # Problems first. A table whose grid could not be found has no
                    # stations either, and reporting that as "nothing here" hid real
                    # detection failures behind a message about empty pages.
                    # An orphaned header strip costs this table its train numbers and
                    # nothing else. Counting it beside a line that could not be read at
                    # all made the losses look far worse than they were.
                    if grid.problems and grid.problems[0].kind == "header":
                        print(f"  note  {label}: {grid.problems[0].detail}", flush=True)
                        skipped += 1
                        continue

                    if grid.problems and not (grid.stations and counts["times"]):
                        print(f"  FAIL  {label}: {grid.problems[0].kind}: "
                              f"{grid.problems[0].detail}", flush=True)
                        held += 1
                        continue

                    if not grid.stations or not counts["times"]:
                        print(f"  skip  {label}: nothing timetable-shaped here", flush=True)
                        skipped += 1
                        continue

                    # A table is held when anything in it is unproven. That is the right
                    # default and it is why this pipeline can be trusted at all - but it
                    # is all-or-nothing, and one unreadable cell out of 737 was costing a
                    # rider 24 stations and a whole day's service. Since a flagged cell is
                    # never written whatever happens, the choice is not between right and
                    # wrong times: it is between one stop reading "no published time" and
                    # the entire table being invisible. --allow-unverified names how much
                    # of that a run will accept, and defaults to none.
                    lost = len(grid.unverified())
                    share = 100.0 * lost / counts["times"] if counts["times"] else 100.0
                    tolerable = args.allow_unverified > 0 and share <= args.allow_unverified

                    if grid.problems and not args.force and not tolerable:
                        print(f"  HOLD  {label}: {len(grid.problems)} unresolved "
                              f"of {counts['times']} times", flush=True)
                        for problem in grid.problems[:4]:
                            print(f"          {problem.kind}: {problem.detail}", flush=True)
                        held += 1
                        continue

                    if grid.problems and tolerable and not args.force:
                        print(f"  part  {label}: {lost} of {counts['times']} times "
                              f"unverified ({share:.2f}%) - loading the rest", flush=True)

                    if args.dry_run:
                        print(f"  ok    {label}: {counts['stations']} stations, "
                              f"{counts['trains']} trains, {counts['times']} times", flush=True)
                        loaded += 1
                        continue

                    wrote = load_page(conn, grid, pdf_path=path,
                                      page_number=page.page_number * 100 + index)
                    print(f"  load  {label}: {wrote['route']} - {wrote['stops']} stops, "
                          f"{wrote['trips']} trips, {wrote['times']} times", flush=True)
                    loaded += 1
    finally:
        if conn:
            conn.close()

    print(f"\ntables loaded {loaded}, held {held}, skipped {skipped}", flush=True)


if __name__ == "__main__":
    main()
