"""Fetch, read and load every MyCiTi timetable.

    PYTHONPATH=src python -m myciti_scraper.pipeline --dry-run
    PYTHONPATH=src python -m myciti_scraper.pipeline

Reads what is already in data/myciti and fetches only what is missing, so a re-run after a
parser change costs nothing at the far end.

--dry-run reads every PDF and reports what it WOULD write, which is the step worth running
first: the reading is where this can go wrong, and forty-seven files is enough that a
mistake would otherwise be found one route at a time.
"""
from __future__ import annotations

import argparse
import glob
import logging
import os

from . import db_compat as db
from .download import DEST, fetch, index
from .load import forget_everything, load_run
from .parse import read_pdf, runs

logging.disable(logging.ERROR)     # pdfplumber narrates font problems it then works around


def read_all(paths: list[str]) -> tuple[list[tuple[str, object]], list[str]]:
    """Every service in every file, with anything that could not be read."""
    import pdfplumber

    out, notes = [], []
    for path in sorted(paths):
        route = os.path.basename(path).replace("-timetable.pdf", "").upper()
        try:
            with pdfplumber.open(path) as pdf:
                pages = read_pdf(pdf, route)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{route}: could not be opened - {type(e).__name__}: {e}")
            continue
        if not pages:
            notes.append(f"{route}: no timetable found on any page")
            continue
        found, page_notes = runs(pages)
        notes.extend(f"{route}: {n}" for n in page_notes)
        if not found:
            notes.append(f"{route}: pages read but no service came out of them")
        for run in found:
            out.append((path, run))
    return out, notes


def main() -> None:
    ap = argparse.ArgumentParser(description="Load every MyCiTi timetable")
    ap.add_argument("--dry-run", action="store_true",
                    help="read and report, write nothing")
    ap.add_argument("--no-fetch", action="store_true",
                    help="use what is already in data/myciti")
    args = ap.parse_args()

    if not args.no_fetch:
        rows = index()
        have = sum(1 for r in rows if os.path.exists(os.path.join(DEST, r["filename"])))
        print(f"{len(rows)} routes published, {have} already on disk")
        if have < len(rows):
            print(f"fetching {len(rows) - have}...")
            fetch(rows)
        print()

    paths = sorted(glob.glob(os.path.join(DEST, "*.pdf")))
    print(f"reading {len(paths)} files...")
    services, notes = read_all(paths)

    routes = {os.path.basename(p) for p, _ in services}
    stops = {s for _, r in services for s in r.stops}
    trips = sum(r.trips for _, r in services)
    times = sum(1 for _, r in services for row in r.times for c in row if c)
    days = sorted({r.day_type for _, r in services})
    print(f"\n{len(services)} services across {len(routes)} routes")
    print(f"  {len(stops)} distinct stop names")
    print(f"  {trips} departures, {times:,} published times")
    print(f"  day types: {', '.join(days)}")
    if notes:
        print(f"\n{len(notes)} thing(s) worth a look:")
        for n in notes[:20]:
            print(f"  {n}")

    if args.dry_run:
        print("\ndry run: nothing written")
        return

    conn = db.connect()
    try:
        gone = forget_everything(conn)
        if gone:
            print(f"\ncleared previous load: " +
                  ", ".join(f"{v} {k}" for k, v in gone.items() if v))
        written = {"routes": set(), "trips": 0, "times": 0, "stops": set()}
        for path, run in services:
            got = load_run(conn, run, pdf_path=path)
            written["routes"].add(got["route"])
            written["trips"] += got["trips"]
            written["times"] += got["times"]
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM stop s JOIN operator o ON o.id = s.operator_id "
                    "WHERE o.code = 'myciti'")
        stop_rows = cur.fetchone()[0]
        print(f"\nloaded {len(written['routes'])} routes, {stop_rows} stops, "
              f"{written['trips']} departures, {written['times']:,} times")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
