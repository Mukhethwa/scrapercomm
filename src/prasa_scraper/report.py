"""Read every PRASA page and say how well it went, without touching the database.

The point is to see the failures before trusting any of it. Run it after adding new PDFs,
or after changing anything in ocr.py.

    PYTHONPATH=src python -m prasa_scraper.report
"""
from __future__ import annotations

import argparse
import glob
import os

from .images import page_images
from .ocr import read_page

PDF_DIR = os.path.join("data", "prasa", "pdfs")


def main() -> None:
    ap = argparse.ArgumentParser(description="OCR every PRASA page and report accuracy")
    ap.add_argument("--dir", default=PDF_DIR)
    ap.add_argument("--limit-pages", type=int, default=0, help="stop after N pages per PDF")
    args = ap.parse_args()

    totals = {"pages": 0, "times": 0, "problems": 0, "unreadable": 0}
    for path in sorted(glob.glob(os.path.join(args.dir, "*.pdf"))):
        name = os.path.basename(path)
        pages = page_images(path)
        print(f"\n{name}  ({len(pages)} pages with a bitmap)")
        for pi, page in enumerate(pages, 1):
            if args.limit_pages and pi > args.limit_pages:
                break
            tables = read_page(page.image, page.heading)
            totals["pages"] += 1
            head = (page.heading or "")[:56]
            print(f"  p{page.page_number:<3} {head:58} {len(tables)} table(s)")
            if not tables:
                totals["unreadable"] += 1
            for index, grid in enumerate(tables, 1):
                c = grid.counts()
                totals["times"] += c["times"]
                totals["problems"] += c["problems"]
                print(f"      .{index}  stations={c['stations']:<3} trains={c['trains']:<3} "
                      f"times={c['times']:<5} problems={c['problems']}")
                for problem in grid.problems[:3]:
                    print(f"           {problem.kind}: {problem.detail}")

    good = totals["times"] - totals["problems"]
    print(f"\n{'=' * 70}")
    print(f"pages read      : {totals['pages']}  ({totals['unreadable']} with no stations)")
    print(f"times recognised: {totals['times']}")
    print(f"flagged         : {totals['problems']}")
    if totals["times"]:
        print(f"clean           : {good} ({100 * good / totals['times']:.2f}%)")


if __name__ == "__main__":
    main()
