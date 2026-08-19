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


def run(force: bool = False) -> dict:
    key = os.environ.get("GOOGLE_MAPS_API_KEY") or None
    google_enabled = key is not None

    conn = db.connect()
    ensure_columns(conn)
    cur = conn.cursor()
    if force:
        cur.execute("SELECT id, name FROM stop ORDER BY name")
    else:
        cur.execute("SELECT id, name FROM stop WHERE geocoded_at IS NULL ORDER BY name")
    rows = cur.fetchall()

    g = requests.Session(); g.headers.update({"User-Agent": USER_AGENT})
    n = requests.Session(); n.headers.update({"User-Agent": USER_AGENT})

    stats = {"google": 0, "nominatim": 0, "notfound": 0}
    print(f"geocoding {len(rows)} stops; primary={'google' if google_enabled else 'nominatim'}",
          flush=True)

    for i, (sid, name) in enumerate(rows, 1):
        coords, source = None, None

        if google_enabled:
            try:
                coords = geocode_google(g, name, key)
                if coords:
                    source = "google"
            except GoogleAuthError as e:
                print(f"  ! Google unavailable ({e}); falling back to Nominatim for the rest",
                      flush=True)
                google_enabled = False
            except Exception:  # noqa: BLE001 — transient; try fallback
                coords = None

        if coords is None:
            try:
                coords = geocode_nominatim(n, name)
                if coords:
                    source = "nominatim"
            except Exception:  # noqa: BLE001
                coords = None
            time.sleep(1.1)  # honour Nominatim's rate limit (only when we call it)

        now = datetime.now(timezone.utc)
        if coords:
            cur.execute(
                "UPDATE stop SET lat=%s, lon=%s, geocoded_at=%s, geocode_source=%s WHERE id=%s",
                (coords[0], coords[1], now, source, sid),
            )
            stats[source] += 1
            print(f"[{i}/{len(rows)}] {name}: {source} {coords[0]:.5f},{coords[1]:.5f}", flush=True)
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
    run(force=ap.parse_args().force)
