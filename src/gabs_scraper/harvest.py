"""Harvest the list of timetable PDFs from Timetable.aspx.

The page is served through Cloudflare but responds normally to a request with a
browser User-Agent — no headless browser needed. Each A–W letter filter is an
ASP.NET postback; we GET the page once (to capture __VIEWSTATE et al.) then POST
each letter and scrape the ``window.open('Pdf/…')`` links.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

import requests

from .config import settings

# Letters that actually have routes (G, I, J, Q, U, X, Y, Z have none).
LETTERS = list("ABCDEFHKLMNOPRSTVW")

_REGULAR = re.compile(
    r"^(?P<route>.+)_from_(?P<frm>\d{8})_to_(?P<to>\d{8})_(?P<tt>\d+)$"
)
_PH = re.compile(r"^(?P<route>.+)___PH_(?P<date>\d{8})_(?P<tt>\d+)$")
_PDF_LINK = re.compile(r"window\.open\('(Pdf/[^']+\.pdf)'")


@dataclass
class ManifestEntry:
    route_name: str
    origin: str
    destination: str
    letter_group: str
    timetable_number: str
    is_public_holiday: bool
    effective_from: str | None  # 'YYYY-MM-DD'
    effective_to: str | None
    pdf_path: str
    pdf_url: str
    pdf_filename: str


def _yyyymmdd(s: str) -> str | None:
    if s == "99999999":
        return None
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def _route_name(raw: str) -> str:
    # '___' is the origin-destination separator; '_' is an intra-name space.
    return raw.replace("___", "-").replace("_", " ").strip()


def entry_from_pdf_path(path: str, base_url: str | None = None) -> ManifestEntry:
    base_url = base_url or settings.base_url
    parts = path.split("/")
    folder = parts[1] if len(parts) > 1 else ""
    letter = folder[:-3] if folder.lower().endswith("pdf") else folder[:1]
    filename = parts[-1]
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename

    m = _REGULAR.match(stem)
    if m:
        raw_route, is_ph = m.group("route"), False
        eff_from, eff_to = _yyyymmdd(m.group("frm")), _yyyymmdd(m.group("to"))
        tt = m.group("tt")
    else:
        m = _PH.match(stem)
        if not m:
            raise ValueError(f"Unrecognized PDF filename: {filename}")
        raw_route, is_ph = m.group("route"), True
        eff_from, eff_to = _yyyymmdd(m.group("date")), None
        tt = m.group("tt")

    name = _route_name(raw_route)
    origin, destination = (name.split("-", 1) + [""])[:2] if "-" in name else (name, "")
    return ManifestEntry(
        route_name=name,
        origin=origin.strip(),
        destination=destination.strip(),
        letter_group=letter.upper(),
        timetable_number=tt,
        is_public_holiday=is_ph,
        effective_from=eff_from,
        effective_to=eff_to,
        pdf_path=path,
        pdf_url=base_url.rstrip("/") + "/" + path,
        pdf_filename=filename,
    )


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {"User-Agent": settings.user_agent, "Accept-Language": "en-US,en;q=0.9"}
    )
    return s


def _hidden(name: str, html: str) -> str:
    m = re.search(rf'id="{re.escape(name)}"\s+value="([^"]*)"', html)
    return m.group(1) if m else ""


def fetch_all_paths(session: requests.Session | None = None) -> list[str]:
    session = session or _session()
    r = session.get(settings.timetable_url, timeout=60)
    r.raise_for_status()
    form = {
        "__VIEWSTATE": _hidden("__VIEWSTATE", r.text),
        "__VIEWSTATEGENERATOR": _hidden("__VIEWSTATEGENERATOR", r.text),
        "__EVENTVALIDATION": _hidden("__EVENTVALIDATION", r.text),
        "__EVENTARGUMENT": "",
    }
    seen: dict[str, str] = {}
    for letter in LETTERS:
        rr = session.post(
            settings.timetable_url, data={**form, "__EVENTTARGET": letter}, timeout=60
        )
        rr.raise_for_status()
        for p in _PDF_LINK.findall(rr.text):
            seen.setdefault(p.split("/")[-1], p)
    return list(seen.values())


def harvest(write: bool = True) -> list[ManifestEntry]:
    entries: list[ManifestEntry] = []
    for p in fetch_all_paths():
        try:
            entries.append(entry_from_pdf_path(p))
        except ValueError:
            continue
    entries.sort(key=lambda e: e.pdf_filename)
    if write:
        settings.ensure_dirs()
        settings.manifest_path.write_text(
            json.dumps([asdict(e) for e in entries], indent=1), encoding="utf-8"
        )
    return entries


if __name__ == "__main__":
    got = harvest()
    print(f"harvested {len(got)} timetable PDFs -> {settings.manifest_path}")
