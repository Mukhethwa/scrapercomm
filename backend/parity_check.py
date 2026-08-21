#!/usr/bin/env python3
"""Diff the Java API against the legacy FastAPI API, endpoint by endpoint.

The Strangler Fig cutover is only safe if the new service answers byte-identically.
This drives both servers over the same requests and reports any difference in status
code or JSON body.

Run both services against the SAME database, on different ports:

    # legacy
    PYTHONPATH=src python -m uvicorn gabs_scraper.api:app --port 8001
    # java
    mvn -f backend/pom.xml spring-boot:run -Dspring-boot.run.arguments=--server.port=8000

    python backend/parity_check.py --legacy http://localhost:8001 --java http://localhost:8000

Exits non-zero if anything differs, so it can gate a deployment.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

# Endpoints whose payload legitimately varies between calls (live third-party lookup).
SKIP_BODY_COMPARE = {"/api/geocode"}

# The one field the two services are allowed to disagree on. Several `schedule` rows
# describe the SAME physical bus (the site lists one service under multiple route
# names), which is exactly why the planner groups on timetable_number + direction +
# day_type. When two of those rows offer a departure at the same time, the winner is
# whichever the implementation happened to visit first: Python iterated a set, whose
# order the language does not define, and the Java port iterates (schedule, trip) order.
#
# This is NOT waved through. Any such difference is re-resolved through /api/trip_stops
# — the only thing the React client does with schedule_id — and the run fails unless
# both tuples yield the same stops at the same times.
SCHEDULE_ID_DIFF = re.compile(r"^\$\.options\[\d+\]\.departures\[\d+\]\.schedule_id: ")


def fetch(base: str, path: str) -> tuple[int, object]:
    # Generous, because this is a correctness gate and not a latency assertion.
    # /api/reachable_point currently takes 30-50s for a pin in a dense area: it issues one
    # query per (schedule, trip) anchor, and a Cape Town CBD pin matches ~61,000 of them.
    # A tighter timeout here would fail the gate for a reason that has nothing to do with
    # whether the two services agree.
    try:
        with urllib.request.urlopen(base + path, timeout=300) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body or b"null")
        except json.JSONDecodeError:
            return e.code, body.decode("utf-8", "replace")


def diff(a, b, path="$") -> list[str]:
    """Deep-compare two JSON values, reporting every mismatch with its location."""
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return [f"{path}: type {type(a).__name__} != {type(b).__name__}"]

    if isinstance(a, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: missing from legacy")
            elif key not in b:
                out.append(f"{path}.{key}: missing from java")
            else:
                out += diff(a[key], b[key], f"{path}.{key}")
        return out

    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out

    if isinstance(a, float) or isinstance(b, float):
        if abs(float(a) - float(b)) > 1e-9:
            return [f"{path}: {a!r} != {b!r}"]
        return []

    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def trip_stops(base: str, dep: dict) -> list:
    """What the React client fetches with a departure's (schedule, trip, seq range)."""
    _, body = fetch(base, f"/api/trip_stops?schedule_id={dep['schedule_id']}"
                          f"&trip_index={dep['trip_index']}"
                          f"&from_seq={dep['from_seq']}&to_seq={dep['to_seq']}")
    return [(s["name"], s["departure_time"], s["raw_value"]) for s in body.get("stops", [])]


def reconcile_schedule_ids(base: str, legacy_body, java_body, problems: list[str]) -> list[str]:
    """Drop schedule_id differences that resolve to an identical journey breakdown.

    Anything that does not resolve identically — or resolves to nothing — is kept as a
    failure, so a genuinely wrong schedule_id can never slip through.
    """
    remaining = [p for p in problems if not SCHEDULE_ID_DIFF.match(p)]
    if len(remaining) == len(problems):
        return problems

    for lo, jo in zip(legacy_body.get("options", []), java_body.get("options", [])):
        for ld, jd in zip(lo.get("departures", []), jo.get("departures", [])):
            if ld.get("schedule_id") == jd.get("schedule_id"):
                continue
            legacy_stops = trip_stops(base, ld)
            java_stops = trip_stops(base, jd)
            if not java_stops:
                remaining.append(
                    f"schedule_id {jd['schedule_id']}/trip {jd['trip_index']} resolves to no stops")
            elif legacy_stops != java_stops:
                remaining.append(
                    f"schedule_id {ld['schedule_id']} vs {jd['schedule_id']}: "
                    f"different breakdown ({len(legacy_stops)} vs {len(java_stops)} stops)")
    return remaining


def discover(base: str) -> list[str]:
    """Build the request list from live data, so real ids and stop names are exercised."""
    paths = ["/api/health", "/api/routes", "/api/areas", "/api/stops", "/api/stops?q=bell"]

    _, routes = fetch(base, "/api/routes")
    route_ids = [r["id"] for r in routes.get("routes", [])[:5]]
    paths += [f"/api/routes/{rid}" for rid in route_ids]

    for rid in route_ids[:3]:
        _, detail = fetch(base, f"/api/routes/{rid}")
        for tt in detail.get("timetables", [])[:2]:
            paths.append(f"/api/timetables/{tt['id']}")

    _, stops = fetch(base, "/api/stops?limit=6")
    stop_ids = [s["id"] for s in stops.get("stops", [])]
    paths += [f"/api/stops/{sid}/reachable" for sid in stop_ids[:3]]

    # Journeys and plans between real, connected stop pairs.
    for sid in stop_ids[:3]:
        _, reach = fetch(base, f"/api/stops/{sid}/reachable")
        targets = [t["id"] for t in reach.get("reachable", [])[:2]]
        for tid in targets:
            paths.append(f"/api/journeys?from={sid}&to={tid}")
            paths.append(f"/api/plan?from={sid}&to={tid}")
            paths.append(f"/api/nearby_origins?lat=-33.93&lon=18.46&to={tid}")

    # Pin-based planning around the Cape Town CBD.
    paths += [
        "/api/locate?lat=-33.9249&lon=18.4241",
        "/api/reachable_point?lat=-33.9249&lon=18.4241",
        "/api/plan?from_lat=-33.9249&from_lon=18.4241&to_lat=-33.9022&to_lon=18.6295",
    ]

    # Error contracts.
    paths += [
        "/api/routes/99999999",
        "/api/timetables/99999999",
        "/api/stops/99999999/reachable",
        "/api/journeys?from=1",
        "/api/plan",
    ]
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--legacy", default="http://localhost:8001", help="FastAPI base URL")
    ap.add_argument("--java", default="http://localhost:8000", help="Spring Boot base URL")
    ap.add_argument("--path", action="append", help="check only these paths")
    args = ap.parse_args()

    paths = args.path or discover(args.legacy)
    failures = 0

    for path in paths:
        legacy_status, legacy_body = fetch(args.legacy, path)
        java_status, java_body = fetch(args.java, path)

        problems = []
        if legacy_status != java_status:
            problems.append(f"status {legacy_status} != {java_status}")
        if path.split("?")[0] not in SKIP_BODY_COMPARE:
            problems += diff(legacy_body, java_body)

        reconciled = 0
        if problems and path.startswith("/api/plan?"):
            before = len(problems)
            problems = reconcile_schedule_ids(args.legacy, legacy_body, java_body, problems)
            reconciled = before - len(problems)

        if problems:
            failures += 1
            print(f"FAIL {path}")
            for p in problems[:15]:
                print(f"       {p}")
            if len(problems) > 15:
                print(f"       ... and {len(problems) - 15} more")
        elif reconciled:
            print(f"ok   {path}  ({reconciled} schedule_id tie-breaks verified equivalent)")
        else:
            print(f"ok   {path}")

    print(f"\n{len(paths) - failures}/{len(paths)} endpoints identical")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
