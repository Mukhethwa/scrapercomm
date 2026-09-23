"""Download the Cape Town timetables PRASA publishes, so trains refresh like everything else.

    PYTHONPATH=src python -m prasa_scraper.fetch            # report what is published
    PYTHONPATH=src python -m prasa_scraper.fetch --download  # and fetch what changed

Golden Arrow and MyCiTi have fetched their own data since the beginning. Metrorail did not:
the spreadsheets in data/prasa/xlsx arrived by hand in September, and a scheduled refresh
re-read those same files forever while writing a new scraped_at each time - so the status
page would have called train data fresh for as long as nobody noticed. This closes that.

PRASA runs WordPress. The schedules are a custom post type, each carrying an attachment:

    /admin/wp-json/wp/v2/cape-town-trains?per_page=100   the list, with an attachment id
    /admin/wp-json/wp/v2/media/<id>                      the attachment, with its URL

Files are named after the post's TITLE rather than the URL's basename, deliberately. The
published names do not say what they are - the public holiday sheets are called
"PPH-central-line-outbound.xlsx" - and prasa_scraper.load reads the day type out of the
sheet's banner AND its filename. Named as PRASA names them, a public holiday timetable
loads as a weekday one and puts holiday trains on a Tuesday, which is worse than not having
it. Named from the title, it says "Public Holiday" and is read as one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.request

BASE = "https://www.prasa.com/admin/wp-json/wp/v2"
POST_TYPE = "cape-town-trains"
ATTACHMENT_FIELD = "train_schedule_excel_document"
SHEET_DIR = os.path.join("data", "prasa", "xlsx")
UA = {"User-Agent": "Mozilla/5.0 (compatible; Commuttr/1.0; +https://commuttr.co.za)"}


def _get(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _name_from(title: str) -> str:
    """A filename that still says what the timetable is for.

    HTML entities out (PRASA writes "Simon&#8217;s"), punctuation out, spaces to hyphens.
    """
    t = re.sub(r"&#\d+;|&[a-z]+;", "", title)
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-")
    return f"{t}.xlsx"


def published() -> list[dict]:
    """Every Cape Town timetable PRASA lists, with the file behind it."""
    out = []
    for post in _get(f"{BASE}/{POST_TYPE}?per_page=100"):
        title = (post.get("title") or {}).get("rendered", "") or f"post-{post.get('id')}"
        media_id = (post.get("acf") or {}).get(ATTACHMENT_FIELD)
        url = None
        if media_id:
            try:
                url = _get(f"{BASE}/media/{media_id}").get("source_url")
            except Exception:  # noqa: BLE001 - one broken attachment is not a failed run
                url = None
        out.append({"title": re.sub(r"&#\d+;", "'", title), "url": url,
                    "filename": _name_from(title)})
    return out


def run(download: bool = False, out_dir: str = SHEET_DIR) -> dict:
    items = published()
    listed = len(items)
    missing = [i for i in items if not i["url"]]
    print(f"{listed} timetables listed by PRASA, {listed - len(missing)} with a file")
    for i in missing:
        # PRASA's own listing, not ours. Say which, so it can be asked for.
        print(f"  no file published: {i['title']}")

    if not download:
        print("\nrun with --download to fetch them")
        return {"listed": listed, "missing": len(missing)}

    os.makedirs(out_dir, exist_ok=True)
    new = changed = same = failed = 0
    for i in items:
        if not i["url"]:
            continue
        path = os.path.join(out_dir, i["filename"])
        try:
            req = urllib.request.Request(i["url"], headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
        except Exception as ex:  # noqa: BLE001
            print(f"  FAILED {i['filename']}: {ex!r}")
            failed += 1
            continue
        before = None
        if os.path.exists(path):
            with open(path, "rb") as f:
                before = hashlib.sha256(f.read()).hexdigest()
        after = hashlib.sha256(body).hexdigest()
        if before is None:
            new += 1
            print(f"  new     {i['filename']}")
        elif before != after:
            changed += 1
            print(f"  changed {i['filename']}")
        else:
            same += 1
            continue
        with open(path, "wb") as f:
            f.write(body)

    # Anything here that PRASA no longer lists is superseded. Without this the directory
    # only grows, the loader reads both the old file and the new one, and the same service
    # is loaded twice under two names - the app then offers a train that was withdrawn
    # looking exactly as authoritative as one that runs.
    keep = {i["filename"] for i in items if i["url"]}
    gone = 0
    if failed == 0:
        # Only when every download worked. A network failure must not be read as "PRASA
        # has withdrawn this", which would delete the only copy we hold.
        for name in sorted(os.listdir(out_dir)):
            if name.endswith(".xlsx") and name not in keep:
                os.remove(os.path.join(out_dir, name))
                print(f"  removed {name} - no longer published")
                gone += 1
    else:
        print("  (not removing anything: a download failed, so the list is not trustworthy)")

    print(f"\n{new} new, {changed} changed, {same} unchanged, {gone} withdrawn, {failed} failed")
    if new or changed or gone:
        print("load them:  PYTHONPATH=src python -m prasa_scraper.sheets --fresh")
    return {"listed": listed, "missing": len(missing), "new": new, "changed": changed,
            "same": same, "withdrawn": gone, "failed": failed}


def main() -> None:
    ap = argparse.ArgumentParser(description="Download PRASA's Cape Town timetables")
    ap.add_argument("--download", action="store_true", help="fetch them, not just list them")
    ap.add_argument("--dir", default=SHEET_DIR)
    args = ap.parse_args()
    run(download=args.download, out_dir=args.dir)


if __name__ == "__main__":
    main()
