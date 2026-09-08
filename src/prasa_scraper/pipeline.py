"""Read PRASA PDFs and load what checks out.

    PYTHONPATH=src python -m prasa_scraper.pipeline                 # everything
    PYTHONPATH=src python -m prasa_scraper.pipeline --pdf southern-line-weekday.pdf
    PYTHONPATH=src python -m prasa_scraper.pipeline --page 2 --dry-run

A page carries several tables, each read and checked on its own. One that fails its checks
is reported and held back, because the entire point of the checks is that times nobody has
looked at do not silently become departure times a rider trusts. --force loads anyway, for
when the problems have been reviewed and are understood.
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
    args = ap.parse_args()

    paths = ([os.path.join(args.dir, args.pdf)] if args.pdf
             else sorted(glob.glob(os.path.join(args.dir, "*.pdf"))))

    conn = None if args.dry_run else db.connect()
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
                    if grid.problems and not (grid.stations and counts["times"]):
                        print(f"  FAIL  {label}: {grid.problems[0].kind}: "
                              f"{grid.problems[0].detail}", flush=True)
                        held += 1
                        continue

                    if not grid.stations or not counts["times"]:
                        print(f"  skip  {label}: nothing timetable-shaped here", flush=True)
                        skipped += 1
                        continue

                    if grid.problems and not args.force:
                        print(f"  HOLD  {label}: {len(grid.problems)} unresolved "
                              f"of {counts['times']} times", flush=True)
                        for problem in grid.problems[:4]:
                            print(f"          {problem.kind}: {problem.detail}", flush=True)
                        held += 1
                        continue

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
