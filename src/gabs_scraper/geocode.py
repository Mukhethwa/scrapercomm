"""Geocode stop names to lat/lon (one-time enrichment).

Primary provider: Google Geocoding API (needs env var GOOGLE_MAPS_API_KEY).
Fallback provider: OpenStreetMap Nominatim (no key; <=1 req/sec).

Results (and which provider found them) are cached on the ``stop`` row. The API
key is read only from the environment — never stored in code, the DB, or the dump.
Re-run with force=True to re-geocode every stop from scratch.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

import requests

from . import db

NOMINATIM = "https://nominatim.openstreetmap.org/search"
GOOGLE = "https://maps.googleapis.com/maps/api/geocode/json"
USER_AGENT = "gabs-timetable-scraper/0.1 (local dev; contact: siphonkebe@gmail.com)"

# Greater Cape Town bias box (incl. Paarl / Wellington / Stellenbosch / Strand).
NOMINATIM_VIEWBOX = "18.28,-33.40,19.12,-34.45"       # left,top,right,bottom
GOOGLE_BOUNDS = "-34.45,18.28|-33.40,19.12"           # sw_lat,sw_lng|ne_lat,ne_lng

_DDL = [
    "ALTER TABLE stop ADD COLUMN IF NOT EXISTS lat double precision",
    "ALTER TABLE stop ADD COLUMN IF NOT EXISTS lon double precision",
    "ALTER TABLE stop ADD COLUMN IF NOT EXISTS geocoded_at timestamptz",
    "ALTER TABLE stop ADD COLUMN IF NOT EXISTS geocode_source text",
]


class GoogleAuthError(RuntimeError):
    """Google rejected the key / quota — stop trying Google, use the fallback."""


def ensure_columns(conn) -> None:
    cur = conn.cursor()
    for stmt in _DDL:
        cur.execute(stmt)
    conn.commit()



# The operator writes stop names for a timetable column, not for a gazetteer: words are
# abbreviated to fit and long ones are simply cut off. "LONG STR" is Long Street, one of
# the best-known roads in Cape Town, and no geocoder recognises "STR".
ABBREVIATIONS = {
    # Deliberately no bare "ST": it means Saint at the front of a name and Street at
    # the end, and guessing wrong sends the stop to another suburb.
    "STR": "Street", "STRT": "Street",
    "RD": "Road", "AVE": "Avenue", "AV": "Avenue",
    "DRV": "Drive", "DR": "Drive", "BLVD": "Boulevard", "BVD": "Boulevard",
    "CLSE": "Close", "CL": "Close", "CRES": "Crescent", "CRE": "Crescent",
    "LN": "Lane", "SQ": "Square", "PL": "Place", "TER": "Terrace",
    "STN": "Station", "TERM": "Terminus", "IND": "Industria",
    "SCH": "School", "HOSP": "Hospital", "CTR": "Centre", "CNTR": "Centre",
    "PK": "Park", "GDNS": "Gardens", "HGTS": "Heights", "VILL": "Village",
    "SNR": "Senior", "JUN": "Junior", "PREP": "Preparatory",
}


def expand(name: str) -> str:
    """"LONG STR" -> "Long Street". Whole words only, so STRAND is left alone."""
    out = []
    for word in name.split():
        bare = word.strip(".")
        out.append(ABBREVIATIONS.get(bare.upper(), word))
    return " ".join(out)


def variants(name: str, kind: str | None = None) -> list[str]:
    """
    The name, then progressively looser readings of it.

    Tried in order and the first hit wins, so a precise match is never traded for a vague
    one. The looser forms exist because of how these names reach us:

      "ARTSCAPE (HERTZOG BL"   the PDF column ran out mid-word, so drop the fragment
      "LONG STR"               an abbreviation no gazetteer knows
      "TRAMPOLINE-AZ BERMAN"   two landmarks joined; either half may be findable
      "CNR R300/EISLEBEN RD"   a junction, findable by the road it names

    Nominatim is rate limited to a request a second, so this is deliberately a handful of
    readings rather than every permutation.
    """
    seen: list[str] = []

    def add(candidate: str) -> None:
        candidate = " ".join(candidate.split()).strip(" ,-/")
        if candidate and candidate not in seen:
            seen.append(candidate)

    # A railway station and the suburb it is named after are not the same point, and the
    # suburb is what a plain search returns. Asking for the station first puts the pin on
    # the platform rather than somewhere in the neighbourhood around it.
    if kind == "train":
        add(f"{name} railway station")
        add(f"{expand(name)} railway station")
        add(f"{name} station")

    add(name)
    add(expand(name))

    # A truncated parenthetical: keep what came before it.
    if "(" in name:
        head = name.split("(")[0]
        add(head)
        add(expand(head))

    # A junction or a pair of landmarks: try each side on its own.
    for sep in ("/", " - ", "-"):
        if sep in name:
            for part in name.split(sep):
                if len(part.strip()) >= 4:
                    add(expand(part))
            break

    return seen


def geocode_google(session, name, key):
    params = {
        "address": f"{name}, Cape Town, South Africa",
        "key": key,
        "components": "country:ZA",
        "bounds": GOOGLE_BOUNDS,
        "region": "za",
    }
    r = session.get(GOOGLE, params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    status = js.get("status")
    if status == "OK" and js.get("results"):
        loc = js["results"][0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])
    if status == "ZERO_RESULTS":
        return None
    if status in ("REQUEST_DENIED", "OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT", "INVALID_REQUEST"):
        raise GoogleAuthError(f"{status}: {js.get('error_message', '')}")
    return None


def geocode_nominatim(session, name):
    params = {
        "q": f"{name}, Cape Town, South Africa",
        "format": "json",
        "limit": 1,
        "countrycodes": "za",
        "viewbox": NOMINATIM_VIEWBOX,
        "bounded": 0,
    }
    r = session.get(NOMINATIM, params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    if js:
        return float(js[0]["lat"]), float(js[0]["lon"])
    return None


def run(force: bool = False, retry_failed: bool = False) -> dict:
    key = os.environ.get("GOOGLE_MAPS_API_KEY") or None
    google_enabled = key is not None

    conn = db.connect()
    ensure_columns(conn)
    cur = conn.cursor()
    if force:
        cur.execute("""SELECT s.id, s.name, o.kind FROM stop s
                       LEFT JOIN operator o ON o.id = s.operator_id ORDER BY s.name""")
    elif retry_failed:
        # Everything still unplaced, including stops already marked "notfound" - the point
        # of a retry is that the readings tried have changed.
        cur.execute("""SELECT s.id, s.name, o.kind FROM stop s
                       LEFT JOIN operator o ON o.id = s.operator_id
                       WHERE s.lat IS NULL ORDER BY s.name""")
    else:
        cur.execute("""SELECT s.id, s.name, o.kind FROM stop s
                       LEFT JOIN operator o ON o.id = s.operator_id
                       WHERE s.geocoded_at IS NULL ORDER BY s.name""")
    rows = cur.fetchall()

    g = requests.Session(); g.headers.update({"User-Agent": USER_AGENT})
    n = requests.Session(); n.headers.update({"User-Agent": USER_AGENT})

    stats = {"google": 0, "nominatim": 0, "notfound": 0}
    print(f"geocoding {len(rows)} stops; primary={'google' if google_enabled else 'nominatim'}",
          flush=True)

    for i, (sid, name, kind) in enumerate(rows, 1):
        coords, source, matched = None, None, None

        # Each reading of the name in turn, stopping at the first that lands. The exact
        # name is always tried first, so a looser reading is only ever a last resort.
        for candidate in variants(name, kind):
            if google_enabled:
                try:
                    coords = geocode_google(g, candidate, key)
                    if coords:
                        source, matched = "google", candidate
                except GoogleAuthError as e:
                    print(f"  ! Google unavailable ({e}); falling back to Nominatim for the rest",
                          flush=True)
                    google_enabled = False
                except Exception:  # noqa: BLE001 — transient; try fallback
                    coords = None

            if coords is None:
                try:
                    coords = geocode_nominatim(n, candidate)
                    if coords:
                        source, matched = "nominatim", candidate
                except Exception:  # noqa: BLE001
                    coords = None
                time.sleep(1.1)  # honour Nominatim's rate limit (only when we call it)

            if coords:
                break

        now = datetime.now(timezone.utc)
        if coords:
            cur.execute(
                "UPDATE stop SET lat=%s, lon=%s, geocoded_at=%s, geocode_source=%s WHERE id=%s",
                (coords[0], coords[1], now, source, sid),
            )
            stats[source] += 1
            via = "" if matched == name else f" (as \"{matched}\")"
            print(f"[{i}/{len(rows)}] {name}{via}: {source} {coords[0]:.5f},{coords[1]:.5f}",
                  flush=True)
        else:
            cur.execute(
                "UPDATE stop SET lat=NULL, lon=NULL, geocoded_at=%s, geocode_source=%s WHERE id=%s",
                (now, "notfound", sid),
            )
            stats["notfound"] += 1
            print(f"[{i}/{len(rows)}] {name}: not found", flush=True)
        conn.commit()

    conn.close()
    print(f"done. google={stats['google']} nominatim={stats['nominatim']} "
          f"notfound={stats['notfound']}", flush=True)
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Geocode GABS stops (Google primary, OSM fallback)")
    ap.add_argument("--force", action="store_true", help="re-geocode every stop from scratch")
    ap.add_argument("--retry-failed", action="store_true",
                    help="re-try every stop that still has no coordinates")
    args = ap.parse_args()
    run(force=args.force, retry_failed=args.retry_failed)
