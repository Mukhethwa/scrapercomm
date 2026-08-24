"""Precompute the real road path of each leg (consecutive timing-point pair).

For every distinct (A -> B) pair of consecutive timing points we ask a routing service
for the driving path and cache it in ``leg_geometry`` as plain JSON. This is a one-time
job (~1,900 legs) and it is re-runnable: only legs not already cached are fetched, so
the usual outcome of a second run is "nothing to fetch" (use --force to redo all).

Two providers, chosen automatically:

* **OSRM** (default) - the public demo server, no account and no key. Slower to be
  polite to a free service, which only matters the first time.
* **Google Directions** - used when GOOGLE_MAPS_API_KEY is set. The key is read from
  the environment only and is never written anywhere.

Nothing here asks for credentials unless there is actually work to do, so a re-run on a
fully cached database needs no key and no network.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone

import requests

from . import db

GOOGLE_DIRECTIONS = "https://maps.googleapis.com/maps/api/directions/json"
OSRM_ROUTE = "https://router.project-osrm.org/route/v1/driving"
# The public OSRM demo is a free, shared service. One request at a time, with a pause.
OSRM_DELAY_S = 0.6
USER_AGENT = "gabs-timetable-scraper/0.1 (local dev)"

_DDL = """
CREATE TABLE IF NOT EXISTS leg_geometry (
    from_stop_id INTEGER NOT NULL REFERENCES stop(id) ON DELETE CASCADE,
    to_stop_id   INTEGER NOT NULL REFERENCES stop(id) ON DELETE CASCADE,
    path         JSONB,               -- [[lat,lon], ...] real driving path
    length_m     DOUBLE PRECISION,
    min_lat DOUBLE PRECISION, min_lon DOUBLE PRECISION,
    max_lat DOUBLE PRECISION, max_lon DOUBLE PRECISION,
    source       TEXT,
    fetched_at   TIMESTAMPTZ,
    PRIMARY KEY (from_stop_id, to_stop_id)
);
"""


class RoutingError(RuntimeError):
    """The provider refused us - a bad key, a spent quota, or a service that is down."""


# Kept under the old name so existing callers and except-clauses still work.
GoogleError = RoutingError


def ensure_table(conn) -> None:
    cur = conn.cursor()
    cur.execute(_DDL)
    conn.commit()


def decode_polyline(polyline_str: str) -> list[list[float]]:
    """Decode a Google encoded polyline into [[lat, lon], ...]."""
    index, lat, lng, out = 0, 0, 0, []
    n = len(polyline_str)
    while index < n:
        for is_lat in (True, False):
            shift, result = 0, 0
            while True:
                byte = ord(polyline_str[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lat:
                lat += delta
            else:
                lng += delta
        out.append([lat / 1e5, lng / 1e5])
    return out


def fetch_leg_google(session, a: tuple[float, float], b: tuple[float, float], key: str):
    params = {
        "origin": f"{a[0]},{a[1]}",
        "destination": f"{b[0]},{b[1]}",
        "mode": "driving",
        "key": key,
    }
    r = session.get(GOOGLE_DIRECTIONS, params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    status = js.get("status")
    if status == "OK" and js.get("routes"):
        route = js["routes"][0]
        leg = route["legs"][0]
        length_m = leg.get("distance", {}).get("value")
        pts: list[list[float]] = []
        for step in leg.get("steps", []):
            dec = decode_polyline(step["polyline"]["points"])
            if pts and dec and pts[-1] == dec[0]:
                dec = dec[1:]
            pts.extend(dec)
        if not pts:
            pts = decode_polyline(route["overview_polyline"]["points"])
        return pts, length_m
    if status in ("REQUEST_DENIED", "OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"):
        raise RoutingError(f"{status}: {js.get('error_message', '')}")
    return None, None  # ZERO_RESULTS / NOT_FOUND


def fetch_leg_osrm(session, a: tuple[float, float], b: tuple[float, float], _key=None):
    """Same contract as the Google fetcher, against the keyless OSRM demo server."""
    # OSRM takes lon,lat - the opposite order to everything else here.
    coords = f"{a[1]},{a[0]};{b[1]},{b[0]}"
    for attempt in range(4):
        r = session.get(f"{OSRM_ROUTE}/{coords}",
                        params={"overview": "full", "geometries": "geojson"},
                        timeout=30)
        # A shared free service; back off rather than hammer it.
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        js = r.json()
        code = js.get("code")
        if code == "Ok" and js.get("routes"):
            route = js["routes"][0]
            pts = [[lat, lon] for lon, lat in route["geometry"]["coordinates"]]
            return pts, route.get("distance")
        if code in ("NoRoute", "NoSegment"):
            return None, None
        raise RoutingError(f"osrm: {code} {js.get('message', '')}")
    raise RoutingError("osrm: still rate-limited after 4 attempts")


def distinct_legs(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT s1.stop_id AS a, s2.stop_id AS b,
               sa.lat, sa.lon, sb.lat, sb.lon
        FROM schedule_stop s1
        JOIN schedule_stop s2 ON s2.schedule_id = s1.schedule_id
                             AND s2.stop_sequence = s1.stop_sequence + 1
        JOIN stop sa ON sa.id = s1.stop_id
        JOIN stop sb ON sb.id = s2.stop_id
        WHERE sa.lat IS NOT NULL AND sb.lat IS NOT NULL AND s1.stop_id <> s2.stop_id
        """
    )
    return cur.fetchall()


def choose_provider(name: str = "auto") -> tuple[str, object, str | None, float]:
    """Pick a routing provider. Returns (label, fetch function, key, delay)."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if name == "auto":
        name = "google" if key else "osrm"
    if name == "google":
        if not key:
            raise SystemExit(
                "GOOGLE_MAPS_API_KEY is not set. "
                "Either export it, or run without --provider google to use OSRM, "
                "which needs no key."
            )
        return "google:directions", fetch_leg_google, key, 0.05
    return "osrm:driving", fetch_leg_osrm, None, OSRM_DELAY_S


def precompute(force: bool = False, provider: str = "auto") -> dict:
    conn = db.connect()
    ensure_table(conn)
    cur = conn.cursor()
    legs = distinct_legs(conn)

    done = set()
    if not force:
        cur.execute("SELECT from_stop_id, to_stop_id FROM leg_geometry WHERE path IS NOT NULL")
        done = {(a, b) for a, b in cur.fetchall()}

    todo = [row for row in legs if force or (row[0], row[1]) not in done]
    stats = {"ok": 0, "empty": 0}
    print(f"legs total={len(legs)} todo={len(todo)}", flush=True)

    # Decide the provider only once we know there is something to fetch. A re-run on a
    # fully cached database is the common case and it needs neither key nor network.
    if not todo:
        print("every leg already has a road path - nothing to fetch", flush=True)
        conn.close()
        return stats

    source, fetch, key, delay = choose_provider(provider)
    print(f"fetching {len(todo)} leg(s) via {source}", flush=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for i, (a, b, alat, alon, blat, blon) in enumerate(todo, 1):
        pts, length_m = fetch(session, (alat, alon), (blat, blon), key)
        now = datetime.now(timezone.utc)
        if pts:
            lats = [p[0] for p in pts]
            lons = [p[1] for p in pts]
            cur.execute(
                """
                INSERT INTO leg_geometry (from_stop_id, to_stop_id, path, length_m,
                    min_lat, min_lon, max_lat, max_lon, source, fetched_at)
                VALUES (%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (from_stop_id, to_stop_id) DO UPDATE SET
                    path=EXCLUDED.path, length_m=EXCLUDED.length_m,
                    min_lat=EXCLUDED.min_lat, min_lon=EXCLUDED.min_lon,
                    max_lat=EXCLUDED.max_lat, max_lon=EXCLUDED.max_lon,
                    source=EXCLUDED.source, fetched_at=EXCLUDED.fetched_at
                """,
                (a, b, json.dumps(pts), length_m, min(lats), min(lons), max(lats),
                 max(lons), source, now),
            )
            stats["ok"] += 1
        else:
            stats["empty"] += 1
        conn.commit()
        if i % 100 == 0:
            print(f"  {i}/{len(todo)} ok={stats['ok']} empty={stats['empty']}", flush=True)
        time.sleep(delay)

    conn.close()
    print(f"done ok={stats['ok']} empty={stats['empty']}", flush=True)
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Precompute the road path of every leg")
    ap.add_argument("--force", action="store_true", help="refetch all legs")
    ap.add_argument("--provider", choices=("auto", "osrm", "google"), default="auto",
                    help="auto uses Google when GOOGLE_MAPS_API_KEY is set, else OSRM")
    args = ap.parse_args()
    precompute(force=args.force, provider=args.provider)
