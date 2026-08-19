"""Pure geo helpers: distance from a point to a polyline, and how far along it.

Uses a local equirectangular projection (accurate at city scale) for point-to-segment
math, and haversine for along-path distances. No external dependencies.
"""
from __future__ import annotations

import math

_R = 6371000.0  # earth radius (m)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _R * math.asin(math.sqrt(a))


def _xy(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    x = math.radians(lon) * math.cos(math.radians(lat0)) * _R
    y = math.radians(lat) * _R
    return x, y


def point_to_segment_m(plat, plon, alat, alon, blat, blon) -> tuple[float, float]:
    """Distance (m) from P to segment A-B, and the clamped projection param t in [0,1]."""
    lat0 = (alat + blat) / 2
    px, py = _xy(plat, plon, lat0)
    ax, ay = _xy(alat, alon, lat0)
    bx, by = _xy(blat, blon, lat0)
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        t = 0.0
    else:
        t = ((px - ax) * dx + (py - ay) * dy) / seg2
        t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy), t


def locate_on_path(path, length_m, plat: float, plon: float) -> tuple[float, float]:
    """Nearest distance (m) from P to the polyline, and fraction f in [0,1] along it
    (along-path distance to the closest projection / total length)."""
    if not path:
        return float("inf"), 0.0
    if len(path) < 2:
        return haversine_m(plat, plon, path[0][0], path[0][1]), 0.0

    total = length_m or 0.0
    if not total:
        for i in range(len(path) - 1):
            total += haversine_m(path[i][0], path[i][1], path[i + 1][0], path[i + 1][1])

    best_d, best_along, cum = float("inf"), 0.0, 0.0
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        seglen = haversine_m(a[0], a[1], b[0], b[1])
        d, t = point_to_segment_m(plat, plon, a[0], a[1], b[0], b[1])
        if d < best_d:
            best_d = d
            best_along = cum + t * seglen
        cum += seglen

    f = best_along / total if total > 0 else 0.0
    return best_d, max(0.0, min(1.0, f))
