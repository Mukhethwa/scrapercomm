"""Stations that bend their own line, put back where the line says they are.

    PYTHONPATH=src python -m prasa_scraper.repair_positions          # report
    PYTHONPATH=src python -m prasa_scraper.repair_positions --fix    # and repair

prasa_scraper.positions asks whether a station is far from everything else on its line.
That catches a station in the wrong town and misses one just offshore: FALSE BAY was
geocoded to the bay it is named after, 22 km from Muizenberg, under that check's 25 km and
in the middle of the sea. A rider planning Buh Rein to Kalk Bay saw the map draw their
train out into False Bay and turn around.

So the question this asks is the one gabs_scraper.stop_positions asks of bus stops: a
station sits BETWEEN its neighbours, so riding A - B - C should be about as far as riding
A - C. FALSE BAY adds 46.6 km to Muizenberg - Lakeside, which no station on a line does.

The repair is the line itself as context. A station's neighbours bound a box, the name
plus "railway station" is searched inside that box, and a candidate is accepted only if it
MEASURES better: the bend it forced has to be gone, not merely smaller. Nominatim knows
these three by name and places all of them within the box.

Where nothing qualifies the coordinates are cleared, which is what prasa_scraper.positions
does: a station with no position still plans journeys, because a journey is planned by
stop id, and the map draws nothing rather than something wrong.
"""
from __future__ import annotations

import argparse
import math
import time

import requests

from . import db_compat as db

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Commuttr/1.0 (+https://commuttr.co.za)"

# The bend a station forces on its own line before it is called wrong.
#
# Real lines do bend: the Northern Line turns at Bellville and the Southern runs around
# the mountain. The largest bend any correctly placed station forces is a few kilometres,
# and the three found here force 35, 47 and 70.
DETOUR_KM = 15.0

# What a repaired station has to get down to. A station between its neighbours adds almost
# nothing to the ride; anything still adding kilometres has not been found.
REPAIRED_KM = 3.0

# How far outside its neighbours a station may be looked for.
PAD_KM = 5.0

# Two stations this close are one station read twice, which is a geocoder giving up.
SAME_PLACE_KM = 0.1


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    inner = (math.sin(lat1) * math.sin(lat2)
             + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return 6371.0 * math.acos(max(-1.0, min(1.0, inner)))


def _lines(cur) -> dict[int, list[tuple]]:
    """Every train schedule as its ordered stops: [(stop_id, name, lat, lon), ...]."""
    cur.execute(
        """
        SELECT sc.id, ss.stop_sequence, s.id, s.name, s.lat, s.lon
        FROM schedule sc
        JOIN timetable t  ON t.id = sc.timetable_id
        JOIN route r      ON r.id = t.route_id
        JOIN operator o   ON o.id = r.operator_id AND o.kind = 'train'
        JOIN schedule_stop ss ON ss.schedule_id = sc.id
        JOIN stop s       ON s.id = ss.stop_id
        ORDER BY sc.id, ss.stop_sequence
        """
    )
    lines: dict[int, list[tuple]] = {}
    for sched, _seq, sid, name, lat, lon in cur.fetchall():
        lines.setdefault(sched, []).append((sid, name, lat, lon))
    return lines


def _detours(lines: dict[int, list[tuple]], moved: dict[int, tuple[float, float]] | None = None):
    """
    The worst bend each station forces, and who it sits between when it does.

    [moved] answers the same question with a station somewhere else, which is how a
    candidate is measured before anything is written.
    """
    moved = moved or {}

    def at(sid, lat, lon):
        return moved.get(sid) if sid in moved else (None if lat is None else (lat, lon))

    worst: dict[int, float] = {}
    between: dict[int, tuple] = {}
    for stops in lines.values():
        for i in range(1, len(stops) - 1):
            (a_id, a_name, a_lat, a_lon) = stops[i - 1]
            (b_id, _b_name, b_lat, b_lon) = stops[i]
            (c_id, c_name, c_lat, c_lon) = stops[i + 1]
            a, b, c = at(a_id, a_lat, a_lon), at(b_id, b_lat, b_lon), at(c_id, c_lat, c_lon)
            if not (a and b and c):
                continue
            detour = km(a, b) + km(b, c) - km(a, c)
            if detour > worst.get(b_id, 0.0):
                worst[b_id] = detour
                between[b_id] = (a_name, c_name, a, c)
    return worst, between


def _search(session: requests.Session, name: str, box: tuple[float, float, float, float]):
    """The station by name, inside the box its neighbours make. None if it is not there."""
    lat_min, lat_max, lon_min, lon_max = box
    params = {
        "q": f"{name} railway station",
        "format": "json",
        "limit": 3,
        "countrycodes": "za",
        # left,top,right,bottom
        "viewbox": f"{lon_min:.5f},{lat_max:.5f},{lon_max:.5f},{lat_min:.5f}",
        "bounded": 1,
    }
    r = session.get(NOMINATIM, params=params, timeout=30)
    r.raise_for_status()
    return [(float(h["lat"]), float(h["lon"]), h.get("display_name", "")) for h in r.json()]


def run(fix: bool = False) -> dict:
    conn = db.connect()
    cur = conn.cursor()
    lines = _lines(cur)
    worst, between = _detours(lines)

    cur.execute("SELECT id, lat, lon FROM stop WHERE lat IS NOT NULL")
    everything = [(sid, (lat, lon)) for sid, lat, lon in cur.fetchall()]
    names = {sid: name for stops in lines.values() for sid, name, _, _ in stops}

    suspects = sorted(((d, sid) for sid, d in worst.items() if d > DETOUR_KM), reverse=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    repaired, cleared, kept = [], [], []
    for detour, sid in suspects:
        name = names[sid]
        a_name, c_name, a, c = between[sid]
        pad = PAD_KM / 111.0
        box = (min(a[0], c[0]) - pad, max(a[0], c[0]) + pad,
               min(a[1], c[1]) - pad, max(a[1], c[1]) + pad)

        best = None
        try:
            for lat, lon, label in _search(session, name, box):
                if any(sid2 != sid and km((lat, lon), p) < SAME_PLACE_KM for sid2, p in everything):
                    continue
                after, _ = _detours(lines, {sid: (lat, lon)})
                if after.get(sid, 0.0) <= REPAIRED_KM:
                    best = (lat, lon, label, after.get(sid, 0.0))
                    break
        except requests.RequestException as exc:
            print(f"  {name}: could not ask Nominatim ({exc})")
        time.sleep(1.1)  # Nominatim's usage policy is one request a second.

        if best:
            lat, lon, label, after = best
            repaired.append((name, detour, after, lat, lon, label))
            if fix:
                cur.execute(
                    "UPDATE stop SET lat=%s, lon=%s, geocode_source='osm-by-line' WHERE id=%s",
                    (lat, lon, sid),
                )
        else:
            cleared.append((name, detour, a_name, c_name))
            if fix:
                cur.execute("UPDATE stop SET lat=NULL, lon=NULL WHERE id=%s", (sid,))

    if fix:
        conn.commit()
    cur.close()
    conn.close()

    print(f"{len(worst)} stations measured against their own line, "
          f"{len(suspects)} bend it by more than {DETOUR_KM:.0f} km")
    for name, before, after, lat, lon, label in repaired:
        print(f"  {name}: {before:.1f} km -> {after:.1f} km at {lat:.4f},{lon:.4f}  {label[:60]}")
    for name, before, a_name, c_name in cleared:
        print(f"  {name}: {before:.1f} km between {a_name} and {c_name}, nothing found - "
              f"{'cleared' if fix else 'would be cleared'}")
    if not fix and (repaired or cleared):
        print("\nrun with --fix to write these")
    if fix and repaired:
        print("\nleg_geometry is built from stop positions, so rebuild the paths that "
              "touch these stations:\n  PYTHONPATH=src python -m gabs_scraper.geometry")
    return {"measured": len(worst), "repaired": len(repaired), "cleared": len(cleared), "kept": kept}


def main() -> None:
    ap = argparse.ArgumentParser(description="Put stations back on their own line")
    ap.add_argument("--fix", action="store_true", help="write the repairs")
    run(fix=ap.parse_args().fix)


if __name__ == "__main__":
    main()
