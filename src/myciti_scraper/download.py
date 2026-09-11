"""Fetch the route timetables MyCiTi publishes, once.

    PYTHONPATH=src python -m myciti_scraper.download --list
    PYTHONPATH=src python -m myciti_scraper.download

The index page lists one PDF per route and names each one in its link text - "101
Vredehoek - Gardens - Civic Centre (clockwise)" - which is the route label a rider reads,
so both are taken from the same fetch rather than guessed from the filename.

Deliberately slow. One page and forty-seven files is not a crawl, but it is somebody
else's server and there is no reason to ask for them all at once.
"""
from __future__ import annotations

import argparse
import html as H
import os
import re
import time
import urllib.request

BASE = "https://www.myciti.org.za"
INDEX = f"{BASE}/en/timetables/timetable-downloads/"
DEST = os.path.join("data", "myciti")

# A courteous agent with a contactable name, which is what the robots convention asks for.
UA = {"User-Agent": "commuttr-scraper/1.0 (+https://github.com/commuttr)"}

# Between requests. The whole set is forty-seven files; a second and a half each is a
# minute and a bit, and costs nobody anything.
PAUSE_S = 1.5

_LINK = re.compile(r'<a[^>]+href="(/docs/route-timetables/([^"/]+)\.pdf)"[^>]*>(.*?)</a>',
                   re.I | re.S)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def index() -> list[dict]:
    """Every route the page offers: its number, the label it prints, and where the PDF is."""
    req = urllib.request.Request(INDEX, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        page = r.read().decode("utf-8", "replace")

    seen: set[str] = set()
    out: list[dict] = []
    for href, slug, label in _LINK.findall(page):
        name = slug.replace("-timetable", "")
        if name in seen:
            continue
        seen.add(name)
        text = _text(label)
        # "101 Vredehoek - Gardens - Civic Centre (clockwise)" -> number and the rest.
        number, _, rest = text.partition(" ")
        out.append({
            "route": name.upper(),
            "label": text,
            # What the route actually joins, with the number taken off the front so it is
            # not printed twice on a card that already shows the number.
            "path": rest.strip() or text,
            "url": BASE + href,
            "filename": f"{name}-timetable.pdf",
        })
    return out


def fetch(rows: list[dict], dest: str = DEST) -> list[str]:
    """Download anything not already on disk. Returns the paths that are now present."""
    os.makedirs(dest, exist_ok=True)
    paths = []
    for i, row in enumerate(rows):
        path = os.path.join(dest, row["filename"])
        paths.append(path)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            continue
        req = urllib.request.Request(row["url"], headers=UA)
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read()
        with open(path, "wb") as fh:
            fh.write(body)
        print(f"  {row['route']:<6} {len(body):>9,} bytes  {row['path'][:52]}", flush=True)
        if i + 1 < len(rows):
            time.sleep(PAUSE_S)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch the MyCiTi route timetables")
    ap.add_argument("--list", action="store_true", help="show what is published, fetch nothing")
    args = ap.parse_args()

    rows = index()
    print(f"{len(rows)} routes published\n")
    if args.list:
        for r in rows:
            print(f"  {r['route']:<6} {r['path']}")
        return
    have = sum(1 for r in rows if os.path.exists(os.path.join(DEST, r["filename"])))
    print(f"{have} already on disk, fetching {len(rows) - have}\n")
    fetch(rows)
    print(f"\nall {len(rows)} timetables in {DEST}")


if __name__ == "__main__":
    main()
