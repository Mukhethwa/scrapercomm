"""Point every timetable at a PDF Golden Arrow still publishes.

    PYTHONPATH=src python -m gabs_scraper.relink          # report
    PYTHONPATH=src python -m gabs_scraper.relink --fix    # and write

A timetable's pdf_url is the link the app shows under "About this timetable", and it is
the filename that was on the site the day we loaded it. Golden Arrow replaces those files
and deletes the old ones, so the link rots: 26 of 40 sampled were 404 by September, and a
rider following "Official timetable (PDF)" for BELLVILLE - CAPE TOWN got the operator's
own error page. A dead link is worse than none - it reads as our data being wrong about
the service rather than stale about a file.

So the current list is harvested and each timetable is matched to it BY NUMBER, which is
what identifies a service across reissues. A timetable that is no longer published loses
its link entirely, because there is nothing honest to point at: the app then offers the
operator's timetable page instead, which does not rot.

Run it whenever the app's data is refreshed. It costs one pass over Timetable.aspx and
writes nothing but links.
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from . import db
from .harvest import ManifestEntry, entry_from_pdf_path, fetch_all_paths


def _current() -> dict[tuple[str, bool], ManifestEntry]:
    """
    The live PDF for each (timetable number, public holiday or not).

    A number can have several files up at once - an old one still inside its dates and the
    reissue that replaces it. The one starting latest is the one a rider should read.
    """
    by_key: dict[tuple[str, bool], list[ManifestEntry]] = defaultdict(list)
    for path in fetch_all_paths():
        try:
            entry = entry_from_pdf_path(path)
        except ValueError:
            continue  # A filename in a shape we do not know is not a link we should hand out.
        by_key[(entry.timetable_number, entry.is_public_holiday)].append(entry)

    return {
        key: max(entries, key=lambda e: e.effective_from or "")
        for key, entries in by_key.items()
    }


def _places(name: str) -> set[str]:
    """The place names in a route name, for comparing one route to another."""
    return {w for w in name.replace("-", " ").upper().split() if len(w) > 2}


def _same_service(ours: str, theirs: str) -> bool:
    """
    Whether the file we found is the service we hold, not just the same number.

    Golden Arrow reuses numbers. 021201 is TYGERBERG HOSP - UWC in our data and
    CHATSWORTH - MALMESBURY on the site today, which is a different bus on the other side
    of the metro; linking it would answer a rider's question with someone else's
    timetable. Routes are renamed along the way too - TOWN CENTRE - NDABENI is published
    as EPPING - MUTUAL - so a shared place name is the test rather than an equal one.
    """
    return bool(_places(ours) & _places(theirs))


def run(fix: bool = False) -> dict:
    live = _current()
    conn = db.connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.id, t.timetable_number, t.is_public_holiday, t.pdf_url, r.name
        FROM timetable t JOIN route r ON r.id = t.route_id
        ORDER BY t.id
        """
    )
    rows = cur.fetchall()

    changed, dropped, already, mismatched = 0, 0, 0, 0
    for tid, number, is_ph, pdf_url, route_name in rows:
        entry = live.get((number, is_ph))
        if entry and not _same_service(route_name, entry.route_name):
            mismatched += 1
            entry = None
        wanted = entry.pdf_url if entry else None
        if wanted == pdf_url:
            already += 1
            continue
        if fix:
            if wanted:
                # The link only. pdf_filename is the file we downloaded and parsed, and
                # several timetables share a number, so rewriting it both loses that and
                # collides on its unique index.
                cur.execute("UPDATE timetable SET pdf_url=%s WHERE id=%s", (wanted, tid))
            else:
                cur.execute("UPDATE timetable SET pdf_url=NULL WHERE id=%s", (tid,))
        if wanted:
            changed += 1
        else:
            dropped += 1

    if fix:
        conn.commit()
    cur.close()
    conn.close()

    print(f"{len(rows)} timetables, {len(live)} PDFs published right now")
    print(f"  {already} already pointing at the current file")
    print(f"  {changed} {'repointed' if fix else 'to repoint'}")
    print(f"  {dropped} no longer published, {'link cleared' if fix else 'link would be cleared'}")
    print(f"  ({mismatched} of those had a file with their number that is a different route)")
    if not fix and (changed or dropped):
        print("\nrun with --fix to write these")
    return {"timetables": len(rows), "live": len(live), "changed": changed,
            "dropped": dropped, "mismatched": mismatched}


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh the official timetable PDF links")
    ap.add_argument("--fix", action="store_true", help="write the new links")
    run(fix=ap.parse_args().fix)


if __name__ == "__main__":
    main()
