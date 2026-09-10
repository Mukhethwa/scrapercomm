"""What the app answers today, so tomorrow can be compared to it.

    PYTHONPATH=src python -m gabs_scraper.corpus --record    # after you are happy
    PYTHONPATH=src python -m gabs_scraper.corpus --check     # after any change

This exists because of a specific, repeated failure. Every fix in September 2026 was
correct in the case it was aimed at and wrong somewhere nobody looked:

    a rule that a journey must start at a printed time      removed journeys with a change
                                                            from 291 of the 629 stops
    taking the four nearest stops to a place                hid CAPE TOWN, the stop 219
                                                            routes run to
    re-geocoding a stop with its town as context            moved 19 stops onto the town

Tests did not catch these and mostly could not have. A unit test is written at the same
moment as the code and by the same person, so it encodes the same misunderstanding: a test
for "a departure must have a boarding time" would have passed while half the network lost
its connections, because the rule was the bug.

What catches this class is not a test of the rule. It is a record of the ANSWERS - a few
hundred real journeys, the ones a rider would actually ask for - kept in the repository and
compared after every change. It does not need to know which answer is right. It only needs
to notice that a journey that existed this morning does not exist tonight, and say so
while the change is still in your hands.

Nothing here fails a build on its own. A shrinking number is sometimes the point - removing
journeys that could not be timed was deliberate - so this reports and leaves the judgement
where it belongs. What it removes is the possibility of not noticing.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request

from . import db

API = os.environ.get("COMMUTTR_API", "http://localhost:8000/api")
CORPUS = os.path.join("data", "corpus.json")

# Generous. A slow answer is still an answer, and is worth recording as one.
TIMEOUT_S = 180

# Journeys chosen to spread across the way the app is actually used, and to include every
# case that has broken: a place to a place, a stop to a stop, one network and both, a stop
# whose timetable prints no departure at all, and a pair with a single possible interchange.
PLACES = [
    ("Kraaifontein", -33.8477778, 18.7161111),
    ("Cape Town CBD", -33.9288301, 18.4172197),
    ("Khayelitsha", -34.0403, 18.6773),
    ("Woodstock", -33.9270, 18.4450),
    ("Bellville", -33.8930, 18.6290),
    ("Mitchells Plain", -34.0330, 18.6180),
]

# Named with the network they belong to, because a name alone is ambiguous and picking
# wrongly makes the corpus lie. RETREAT is a station and a bus stop 800m apart, and a first
# draft of this recorded "KRAAIFONTEIN to CAPE TOWN: no journey" - which was true, and only
# because it had paired the railway station with the bus terminus. Stops are unique per
# operator; a fixture that forgets it measures nothing.
STOP_PAIRS = [
    ("BUH REIN", "bus", "BELLVILLE", "bus"),        # every first leg untimed
    ("BUH REIN", "bus", "SPEKENAM", "bus"),         # one possible interchange
    ("CAPE GATE", "bus", "CAPE TOWN", "bus"),
    ("GUGULETU", "bus", "KENRIDGE", "bus"),
    ("KRAAIFONTEIN", "train", "CAPE TOWN", "train"),  # the Northern Line
    ("WYNBERG", "bus", "CAPE TOWN", "bus"),
    ("ATLANTIS", "bus", "CAPE TOWN", "bus"),
    ("FISH HOEK", "train", "CAPE TOWN", "train"),
]

SEARCHES = ["kraaifontein", "woodst", "gugulethu", "bellville", "obs", "cape town"]


def get(path: str, **params):
    """
    One question, or None if the app could not answer it in time.

    A timeout is recorded rather than raised. A journey the app can no longer answer in
    three minutes is exactly the kind of change this exists to notice, and a run that dies
    on the first slow one notices nothing at all - the first attempt at this baseline was
    killed by a cold connections query for WYNBERG, which takes 15 seconds warm.
    """
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
            return json.load(r)
    except Exception as e:      # noqa: BLE001
        print(f"      no answer: {e}", flush=True)
        return None


def stop_ids() -> dict[tuple[str, str], int]:
    """Stop ids by name AND network, because one name can be two places."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.name, o.kind, min(s.id)
            FROM stop s JOIN operator o ON o.id = s.operator_id
            GROUP BY s.name, o.kind
            """
        )
        return {(n, k): i for n, k, i in cur.fetchall()}
    finally:
        conn.close()


def snapshot() -> dict:
    """
    What the app says right now, reduced to the facts worth comparing.

    Counts and the first departure, not whole payloads. A diff of whole payloads is
    unreadable and fires on things nobody cares about, like the order of two equally good
    options; a diff of "this journey has 6 options, boarding at 05:10" is a sentence.
    """
    ids = stop_ids()
    out: dict = {"places": {}, "stops": {}, "searches": {}}

    for name, lat, lon in PLACES:
        for other, olat, olon in PLACES:
            if name >= other:
                continue
            print(f"  {name} -> {other}", flush=True)
            plan = get("plan", from_lat=lat, from_lon=lon, to_lat=olat, to_lon=olon)
            # null, not zero. A question the app could not answer in time is not the same
            # answer as "nothing runs", and recording it as 0 would let a journey that
            # timed out today look identical to one that never existed - the corpus
            # reporting "nothing changed" about the very thing it is here to notice.
            options = plan["options"] if plan else None
            out["places"][f"{name} -> {other}"] = {
                "options": len(options) if options is not None else None,
                "by_bus": sum(1 for o in options if o["operator_kind"] == "bus")
                          if options is not None else None,
                "by_train": sum(1 for o in options if o["operator_kind"] == "train")
                            if options is not None else None,
                "first": first_departure(options or []),
            }

    for a, akind, b, bkind in STOP_PAIRS:
        if (a, akind) not in ids or (b, bkind) not in ids:
            continue
        print(f"  {a} ({akind}) -> {b} ({bkind})", flush=True)
        plan = get("plan", **{"from": ids[(a, akind)], "to": ids[(b, bkind)]})
        conns = get("connections", **{"from": ids[(a, akind)], "to": ids[(b, bkind)]})
        out["stops"][f"{a} ({akind}) -> {b} ({bkind})"] = {
            "direct": len(plan["options"]) if plan else None,
            "with_a_change": len(conns["connections"]) if conns else None,
            "first": first_departure(plan["options"] if plan else []),
        }

    for q in SEARCHES:
        answer = get("geocode", q=q)
        out["searches"][q] = [x["name"] for x in answer["results"]] if answer else None

    return out


def first_departure(options: list) -> str | None:
    """The earliest boarding time offered, as a rider would read it."""
    times = [o["departures"][0]["board_raw"] for o in options if o["departures"]]
    return sorted(times)[0] if times else None


def compare(old: dict, new: dict) -> list[str]:
    """Every way today differs from the recorded day, in plain sentences."""
    notes: list[str] = []
    for section in ("places", "stops"):
        for key in sorted(set(old.get(section, {})) | set(new.get(section, {}))):
            was, now = old.get(section, {}).get(key), new.get(section, {}).get(key)
            if was is None:
                notes.append(f"  NEW      {key}")
                continue
            if now is None:
                notes.append(f"  GONE     {key} is no longer asked")
                continue
            for field, label in (("options", "options"), ("direct", "direct journeys"),
                                 ("with_a_change", "journeys with a change"),
                                 ("by_bus", "by bus"), ("by_train", "by train")):
                if field not in was or was[field] == now.get(field):
                    continue
                before_n, after_n = was[field], now.get(field)
                if after_n is None:
                    notes.append(f"  TIMEOUT  {key}: {label} was {before_n}, "
                                 f"no answer in time")
                elif before_n is None:
                    notes.append(f"  answered {key}: {label} now {after_n}, "
                                 f"previously no answer in time")
                else:
                    arrow = "LOST" if after_n < before_n else "gained"
                    notes.append(f"  {arrow:<8} {key}: {label} {before_n} -> {after_n}")
            if was.get("first") != now.get("first"):
                notes.append(f"  changed  {key}: first departure "
                             f"{was.get('first')} -> {now.get('first')}")

    for q in sorted(set(old.get("searches", {})) | set(new.get("searches", {}))):
        was, now = old.get("searches", {}).get(q), new.get("searches", {}).get(q)
        if was != now:
            notes.append(f"  changed  search {q!r}: {was} -> {now}")
    return notes


def main() -> None:
    ap = argparse.ArgumentParser(description="Record and compare what the app answers")
    ap.add_argument("--record", action="store_true",
                    help="write today as the baseline; do this when you are happy")
    ap.add_argument("--check", action="store_true", help="compare today with the baseline")
    ap.add_argument("--file", default=CORPUS)
    args = ap.parse_args()

    if not (args.record or args.check):
        ap.error("choose --record or --check")

    print(f"asking {API} for {len(PLACES) * (len(PLACES) - 1) // 2} place journeys, "
          f"{len(STOP_PAIRS)} stop journeys and {len(SEARCHES)} searches", flush=True)
    now = snapshot()

    if args.record:
        os.makedirs(os.path.dirname(args.file), exist_ok=True)
        with open(args.file, "w", encoding="utf-8") as fh:
            json.dump(now, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"recorded to {args.file}")
        return

    if not os.path.exists(args.file):
        raise SystemExit(f"no baseline at {args.file}; run --record first")
    with open(args.file, encoding="utf-8") as fh:
        before = json.load(fh)

    notes = compare(before, now)
    if not notes:
        print("\nnothing the corpus covers has changed")
        return
    print(f"\n{len(notes)} difference(s) from the recorded answers:\n")
    for note in notes:
        print(note)
    print("\nA smaller number is not automatically wrong - removing journeys that could "
          "not be\ntimed was deliberate. Read each line and decide. What this removes is "
          "the chance of\nnot noticing.")


if __name__ == "__main__":
    main()
