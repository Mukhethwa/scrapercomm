"""Things that must be true of any answer the planner gives.

Every planner bug found in September 2026 was found by hand, by Mukhethwa, on whatever
journey he happened to try - a bus with no departure time, a place that could reach no
train, the stop every route runs to missing from a search. None of them would have been
caught by the tests that existed, because those mock the services and check the shape of
the JSON. The shape was never wrong.

So these assert the CONTENT, against the running app, and each one names the bug it exists
to catch. They skip when the API is not up, in the same spirit as the database fixture in
test_load: a test that cannot run says so rather than passing quietly.

They are deliberately few and deliberately cheap. A place-to-place search takes seconds, so
this samples the network rather than sweeping it - the sweeps live in their own modules
(prasa_scraper.reachability, gabs_scraper.stop_positions) and are run deliberately.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request

import pytest

API = "http://localhost:8000/api"

# Somewhere in the Cape Town CBD, and the town of Kraaifontein - the two ends of the
# journey that surfaced most of these faults.
CBD = (-33.9288301, 18.4172197)
KRAAIFONTEIN = (-33.8477778, 18.7161111)


def get(path: str, **params):
    query = urllib.parse.urlencode(params)
    url = f"{API}/{path}?{query}" if query else f"{API}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=240) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"API not reachable at {API}: {e}")


@pytest.fixture(scope="module")
def kraaifontein_plan():
    return get("plan", from_lat=KRAAIFONTEIN[0], from_lon=KRAAIFONTEIN[1],
               to_lat=CBD[0], to_lon=CBD[1])


def test_every_departure_says_when_to_be_at_the_stop(kraaifontein_plan):
    """
    A departure with no boarding time is not a departure.

    The screen offered a DIRECT BUS with "no set time", a fare and an Add to Planner
    button - an invitation to catch a bus at an unknown moment - and it buried the train
    that actually runs the journey.
    """
    for option in kraaifontein_plan["options"]:
        for dep in option["departures"]:
            assert dep["board_minutes"] is not None, (
                f"{option['route_label']} offers a departure with no boarding time")


def test_a_place_reaches_both_networks(kraaifontein_plan):
    """
    Kraaifontein to Cape Town is served by Golden Arrow and by Metrorail.

    It returned the train alone, because the walk to nearby stops took the four nearest
    and CAPE TOWN - the terminus 219 routes run to - is the tenth nearest to a CBD pin.
    """
    kinds = {o["operator_kind"] for o in kraaifontein_plan["options"]}
    assert "train" in kinds, "no train offered from Kraaifontein to Cape Town"
    assert "bus" in kinds, "no bus offered from Kraaifontein to Cape Town"


def test_boarding_is_named_as_a_stop_or_a_span(kraaifontein_plan):
    """
    A rider boards AT a stop or BETWEEN two of them, and is told which.

    "Board at near STELLENBOSCH ART-BRENTWOOD PARK" was two wordings at once and neither
    told anybody where to stand.
    """
    for option in kraaifontein_plan["options"]:
        label = option["board_label"]
        assert label and not label.startswith("near "), f"unusable board label: {label!r}"


def test_a_place_beside_a_station_can_reach_trains():
    """
    A pin is matched against the road a bus drives, and rail has no such thing.

    So a place could only ever reach buses, whatever stood next to it: the destinations
    list for Kraaifontein said "on one bus" with the Northern Line running past it.
    """
    r = get("reachable_point", lat=KRAAIFONTEIN[0], lon=KRAAIFONTEIN[1])
    kinds = {x["operator_kind"] for x in r["reachable"]}
    assert "train" in kinds, "a point in Kraaifontein reaches no train"
    assert "bus" in kinds, "a point in Kraaifontein reaches no bus"


def test_every_destination_says_which_network_gets_you_there():
    """
    CAPE TOWN the station and CAPE TOWN the bus stop are both reachable and are not the
    same place. A row that does not say which leaves the rider to guess.
    """
    r = get("reachable_point", lat=KRAAIFONTEIN[0], lon=KRAAIFONTEIN[1])
    for row in r["reachable"]:
        assert row["operator_kind"] in ("bus", "train"), row


def test_a_journey_with_a_change_says_when_to_leave():
    """
    The rule above, in the path a rider reaches when nothing runs straight through.

    It was applied to direct plans only, so 18 of 26 connections could not say when to be
    at the first stop - and that list is the whole answer when there is no direct bus.
    """
    stops = get("stops", q="", limit=5000)["stops"]
    by_name = {s["name"]: s["id"] for s in stops if s["operator_kind"] == "bus"}
    a, b = by_name.get("GUGULETU"), by_name.get("KENRIDGE")
    if not (a and b):
        pytest.skip("sample stops not in this database")
    for c in get("connections", **{"from": a, "to": b})["connections"]:
        assert c["legs"][0]["board_minutes"] is not None, (
            "a journey with a change cannot say when to leave home")


def test_a_stop_with_no_printed_times_still_reaches_the_network():
    """
    BUH REIN to BELLVILLE, which worked for months and then did not.

    Golden Arrow prints times at timing points and "via" everywhere else, and 291 of the
    629 stops never get a printed departure at all - all 648 of BUH REIN's first legs are
    untimed. A rule that every journey must start at a printed time therefore cut nearly
    half the network out of the connections list, and the screen said "No way to get there
    by bus" about a journey that plainly exists.

    A bus cannot reach you before it has left the last stop it does have a time for, so
    that time is a floor: "board from 05:30". Not a promise, and worth vastly more than
    nothing.
    """
    stops = get("stops", q="", limit=5000)["stops"]
    by_name = {s["name"]: s["id"] for s in stops if s["operator_kind"] == "bus"}
    a, b = by_name.get("BUH REIN"), by_name.get("BELLVILLE")
    if not (a and b):
        pytest.skip("sample stops not in this database")

    found = get("connections", **{"from": a, "to": b})["connections"]
    assert found, "BUH REIN can reach BELLVILLE with a change; the app must say so"
    for c in found:
        assert c["legs"][0]["board_minutes"] is not None, (
            "and it must still say when to be at the first stop")


def test_the_app_does_not_offer_what_it_will_then_refuse():
    """
    Whatever the app lists as reachable with a change, it must actually deliver.

    Mukhethwa clicked SPEKENAM out of the "you can reach these stops near BELLVILLE" list
    and got "No way to get there by bus". Both answers were right about their own
    question: the list asked whether an interchange exists, the engine asked whether a
    rider could make the journey. On the only trips joining BUH REIN to SPEKENAM the
    timetable prints no time at BUH REIN and none anywhere before it, so there is nothing
    to tell a rider about when to be there.

    An offer the app withdraws when taken up is worse than a shorter list.

    Sampled, not swept: each destination is a separate query and there are 171 of them.
    """
    stops = get("stops", q="", limit=5000)["stops"]
    by_name = {s["name"]: s["id"] for s in stops if s["operator_kind"] == "bus"}
    origin = by_name.get("BUH REIN")
    if not origin:
        pytest.skip("sample stop not in this database")

    offered = get(f"stops/{origin}/reachable")["connecting"]
    assert offered, "BUH REIN should reach plenty with one change"

    refused = []
    for destination in offered[::20]:
        answer = get("connections", **{"from": origin, "to": destination["id"]})
        if not answer["connections"]:
            refused.append(destination["name"])
    assert not refused, ("offered as reachable with a change and then refused: "
                         + ", ".join(refused))


def test_a_repaired_stop_does_not_land_on_another_stop():
    """
    A re-geocoded stop must not come to rest on top of a different one.

    The failure it guards is a geocoder giving up quietly: asked for "Spekenam, Bellville"
    and finding no Spekenam, it answers with Bellville. That scores a perfect 0.0 km
    detour, because a town centre sits on the route through the town, so the measure waved
    nineteen of them through - ROUTE 1 and ROUTE 2 both landing on BELLVILLE, GATTI'S
    FACTORY on CLAREMONT. Two stops at one point are indistinguishable to a planner.

    Only stops the repair moved. Co-located stops that predate it exist and are a separate,
    older question - AIRPORT IND 1, 2 and 3 have always shared a point - and failing this
    for them would report someone else's problem as this one.
    """
    from gabs_scraper import db

    try:
        conn = db.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {e}")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.name, b.name
            FROM stop a
            JOIN stop b ON b.id <> a.id
                       AND 6371000 * acos(least(1,
                             cos(radians(a.lat)) * cos(radians(b.lat))
                               * cos(radians(b.lon) - radians(a.lon))
                           + sin(radians(a.lat)) * sin(radians(b.lat)))) < 50
            WHERE a.geocode_source = 'route-context' AND a.lat IS NOT NULL
              AND b.lat IS NOT NULL
            """
        )
        clashes = [f"{x} == {y}" for x, y in cur.fetchall()]
    finally:
        conn.close()

    assert not clashes, ("a repaired stop landed on another stop, which means the "
                         "geocoder answered with the town: " + "; ".join(clashes[:10]))


def test_a_price_on_screen_is_a_price_somebody_pays(kraaifontein_plan):
    """
    Every fare the app shows is a cash fare or a train ticket, never a Gold Card price.

    The app led with the five-ride price divided by five for months. It is the right
    number for nobody: a card holder has already bought their rides and does not price a
    journey, and a cash payer is charged something else - R18.00 against R26.80 between
    Bellville and Welgemoed. The card figures still come through the API, because the
    fare table holds them; what must not happen is one reaching a screen.
    """
    # What the operators actually publish. A price on screen has to be one of these; a
    # number arrived at by dividing a card product is not, and that is the whole test.
    PRASA_SINGLES = {1000, 1200, 1400, 1500}

    for option in kraaifontein_plan["options"]:
        fare = option.get("fare")
        if not fare or fare.get("cash_cents") is None:
            # No cash fare means the app shows no price at all, which is intended.
            continue
        cash = fare["cash_cents"]
        if option["operator_kind"] == "train":
            assert cash in PRASA_SINGLES, (
                f"a train fare of {cash} is not one of PRASA's four published singles")
        else:
            # Golden Arrow's cash fares are whole or half rands off a printed notice,
            # never a fifth of a card product - R134/5 = R26.80 would fail this.
            assert cash % 50 == 0, (
                f"a bus cash fare of {cash} is not a published figure; the card price "
                f"divided by five looks exactly like this")


def test_a_train_journey_carries_the_whole_ticket_range():
    """
    Metrorail sells four tickets for one journey and the detail view lists them.

    Unlike Golden Arrow's card products these are choices a rider makes at the window, so
    a missing one is a missing option rather than clutter removed.
    """
    stops = get("stops", q="", limit=5000)["stops"]
    trains = {s["name"]: s["id"] for s in stops if s["operator_kind"] == "train"}
    a, b = trains.get("KRAAIFONTEIN"), trains.get("CAPE TOWN")
    if not (a and b):
        pytest.skip("stations not in this database")

    options = get("plan", **{"from": a, "to": b})["options"]
    fares = [o["fare"] for o in options if o.get("fare")]
    assert fares, "a train journey between two stations must have a fare"
    fare = fares[0]

    for field in ("cash_cents", "return_cents", "weekly_cents",
                  "weekly_sat_cents", "monthly_cents"):
        assert fare.get(field), f"a train fare is missing {field}"

    assert fare["return_cents"] == fare["cash_cents"] * 2, "a return is two singles"
    assert fare["weekly_cents"] > fare["return_cents"], "a week costs more than a return"
    assert fare["monthly_cents"] > fare["weekly_sat_cents"], "a month costs more than a week"
    assert fare["distance_km"], "the band comes from the distance, so it must be carried"


def test_the_search_box_offers_areas_and_not_buildings():
    """
    A pin becomes a journey by matching the road a bus drives, so naming a school claims
    a bus passes a spot nothing published says a bus stops at.
    """
    results = get("geocode", q="kraaifontein")["results"]
    names = [r["name"] for r in results]
    assert "Kraaifontein" in names, f"the suburb itself is missing from {names}"
    assert not any("School" in n or "Shelter" in n for n in names), names


def test_the_chip_and_the_suggestions_agree():
    """
    A place offered under Metro Rail must have a station a rider can walk to.

    The search box offers places and nothing else now, and the operator chip filters them,
    so the two can contradict each other in a way they could not before: Hout Bay under
    Metro Rail is an invitation to a dead end, its nearest station being ten kilometres
    away. The table said so correctly and the Nominatim fallback, asking whether ANY
    service reached the place, said otherwise - so the filter has to hold on both paths.

    Asked by OPERATOR rather than by kind. The chip names a company, and with MyCiTi and
    Golden Arrow both running buses, "is there a bus near here" is no longer the question
    the chip is asking.
    """
    for query, absent in (("hout bay", "Hout Bay"), ("atlantis", "Atlantis")):
        names = [r["name"] for r in
                 get("geocode", q=query, operator="metrorail")["results"]]
        assert absent not in names, (
            f"{absent} was offered under a Metrorail filter and has no station near it")

    # And the same places are there when the rider has not narrowed anything.
    for query, present in (("hout bay", "Hout Bay"), ("atlantis", "Atlantis")):
        names = [r["name"] for r in get("geocode", q=query)["results"]]
        assert present in names, f"{present} vanished from an unfiltered search"


def test_words_nobody_chose_are_not_a_place():
    """
    The app plans between places it knows, and typing is not choosing.

    A rider typed "random place" into the destination box and the screen answered "No
    direct bus or train goes to random place from here" - a claim about the network,
    about somewhere that does not exist. The API is the half that can be asserted here:
    a query matching nothing must return nothing, so there is never a place for the
    screen to plan to.
    """
    for nonsense in ("random place", "zzz nowhere", "asdfghjkl"):
        results = get("geocode", q=nonsense)["results"]
        assert results == [], f"{nonsense!r} was offered as a place: {results}"


def test_a_place_is_offered_once():
    """
    OpenStreetMap maps Atlantis as a node and again as an outline.

    Two identical suggestions is a choice with no difference behind it, and the menu now
    holds nothing but places, so a duplicate is half the list.
    """
    names = [r["name"] for r in get("geocode", q="atlantis")["results"]]
    assert len(names) == len(set(names)), f"duplicate suggestions: {names}"


def test_every_stop_can_still_be_reached_by_naming_a_place():
    """
    The search box no longer offers stops, so a stop with no place near it is a
    destination nobody can ask for.

    Eight were like that - FALSE BAY, FISANTEKRAAL, KALBASKRAAL, DASSENBERG among them -
    and were added to the gazetteer from the stops themselves. This is the check that
    made dropping stop suggestions safe, so it stays.
    """
    from gabs_scraper import db

    try:
        conn = db.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {e}")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.name FROM stop s
            WHERE s.lat IS NOT NULL AND NOT EXISTS (
              SELECT 1 FROM area a WHERE a.served
                AND 6371000 * acos(least(1,
                      cos(radians(a.lat)) * cos(radians(s.lat))
                        * cos(radians(s.lon) - radians(a.lon))
                    + sin(radians(a.lat)) * sin(radians(s.lat)))) <= 2500)
            """
        )
        orphans = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    assert not orphans, ("no place within walking distance, so a rider cannot ask for "
                         "these at all: " + ", ".join(orphans))


def test_an_area_is_only_offered_where_the_network_goes():
    """Ceres is a real town and no service in this database reaches it."""
    assert get("geocode", q="Ceres")["results"] == []


# ---------------------------------------------------------------------------
# Which way an approximate time points.
# ---------------------------------------------------------------------------

BOUND_WORDS = ("from ", "by ", "about ")


def _minutes(clock: str) -> int:
    h, m = clock[:5].split(":")
    return int(h) * 60 + int(m)


def _printed(schedule_id: int, trip_index: int) -> list[tuple[int, int]]:
    """(stop_sequence, minutes) for every stop this trip publishes a time for."""
    trip = get("trip_stops", schedule_id=schedule_id, trip_index=trip_index,
               from_seq=0, to_seq=9999)
    return [(s["stop_sequence"], _minutes(s["departure_time"]))
            for s in trip["stops"] if s["cell_type"] == "TIME" and s["departure_time"]]


def _bounds_in(plan) -> list[dict]:
    """Every approximate end-time in a plan, with what the trip around it prints."""
    out = []
    for option in plan["options"]:
        for d in option["departures"]:
            for end, seq_key, label_key in (("board", "from_seq", "board_label"),
                                            ("arrive", "to_seq", "alight_label")):
                raw = d[f"{end}_raw"]
                if not d[f"{end}_approx"] or ":" not in raw:
                    continue
                out.append({
                    "route": option["route_label"], "label": option[label_key],
                    "end": end, "raw": raw, "seq": d[seq_key],
                    "printed": _printed(d["schedule_id"], d["trip_index"]),
                })
    return out


def misdirected(bounds) -> list[str]:
    """
    Which of these bounds point away from the times the timetable prints.

    A function rather than a loop inside the test, so the rule can be shown a bound that
    IS wrong - see test_the_rule_would_have_caught_it below. An invariant nobody has
    watched fail is an invariant nobody knows is running.
    """
    wrong = []
    for b in bounds:
        if not b["printed"]:
            continue
        when = _minutes(b["raw"].split(" ", 1)[1])
        seq = b["seq"]
        # from_seq rounds UP to the stop ahead of the rider, to_seq rounds DOWN to the
        # one behind - so "at or behind" differs by an end.
        if b["end"] == "board":
            behind = [m for s, m in b["printed"] if s < seq]
            ahead = [m for s, m in b["printed"] if s >= seq]
        else:
            behind = [m for s, m in b["printed"] if s <= seq]
            ahead = [m for s, m in b["printed"] if s > seq]

        if b["raw"].startswith("from ") and when not in behind:
            wrong.append(f"{b['route']} {b['end']} {b['raw']!r} at {b['label']!r}: "
                         f"nothing behind the rider is printed at that time "
                         f"(behind {behind}, ahead {ahead})")
        elif b["raw"].startswith("by ") and when not in ahead:
            wrong.append(f"{b['route']} {b['end']} {b['raw']!r} at {b['label']!r}: "
                         f"nothing ahead of the rider is printed at that time "
                         f"(behind {behind}, ahead {ahead})")
        elif b["raw"].startswith("about "):
            if behind and when < max(behind):
                wrong.append(f"{b['route']} {b['end']} {b['raw']!r}: earlier than "
                             f"{max(behind)}, which the bus has already passed")
            if ahead and when > min(ahead):
                wrong.append(f"{b['route']} {b['end']} {b['raw']!r}: later than "
                             f"{min(ahead)}, which the bus has not reached")
    return wrong


def test_the_rule_would_have_caught_it():
    """
    The screenshot, as data, put through the rule that now guards it.

    KRAAIFONTEIN - NORTHPINE - CAPE TOWN, trip 3: CAPE GATE prints 05:10, the terminus
    prints 06:30, and the rider's own point sits on the leg between N1 FREEWAY (stop 6)
    and CAPE TOWN (stop 7). Calling that "from 06:30" - a floor naming a time the bus has
    not reached - is what the app did, and reads on screen as "after 06:30" directly above
    "CAPE TOWN 06:30".

    Needs no database and no API. The point is that the rule rejects it, and goes on
    rejecting it whether or not anything is running.
    """
    woodstock = {
        "route": "KRAAIFONTEIN - NORTHPINE - CAPE TOWN",
        "label": "between N1 FREEWAY and CAPE TOWN",
        "end": "arrive", "seq": 6,
        "printed": [(1, 5 * 60 + 10), (7, 6 * 60 + 30)],
    }
    assert misdirected([{**woodstock, "raw": "by 06:30"}]) == [], (
        "the terminus is ahead of the rider, so a ceiling naming it is right")
    assert misdirected([{**woodstock, "raw": "from 06:30"}]), (
        "the bug itself: a floor naming a time the bus has not reached yet")
    assert misdirected([{**woodstock, "raw": "about 06:45"}]), (
        "an estimate later than a terminus it has not got to")
    # And the ordinary via-stop floor, which must keep passing.
    assert misdirected([{**woodstock, "raw": "from 05:10"}]) == []


def test_an_approximate_time_says_which_way_it_leans(kraaifontein_plan):
    """
    A bare clock cannot be read, because there are three ways to mean one.

    The API sends a floor at a via stop, a ceiling on the leg before a timed stop, and an
    interpolation between two - and it used to send all three as "05:10", leaving the
    screen to guess. The screen guessed "floor" every time and printed "after".
    """
    bare = [b for b in _bounds_in(kraaifontein_plan)
            if not b["raw"].startswith(BOUND_WORDS)]
    assert not bare, (
        "approximate times with no direction on them, which the breakdown can only "
        "guess at:\n  " + "\n  ".join(f"{b['route']} {b['end']} {b['raw']!r}" for b in bare))


def test_a_bound_names_a_time_on_the_side_it_claims(kraaifontein_plan):
    """
    The bug Mukhethwa saw: "Woodstock (your stop) after 06:30" above "CAPE TOWN 06:30".

    His words were "time to depart cannot be same time or before or after next stop", and
    he was right: 06:30 is the terminus the bus has not reached yet, so the rider passes
    Woodstock BEFORE it, and the screen said after. The clock was the right number with
    the wrong word in front of it, which is why nothing that checks times caught it.

    So this checks the word against the timetable. A "from" must name a printed time the
    bus has already left; a "by" must name one it has not reached. Anything else is the
    two swapped.
    """
    wrong = misdirected(_bounds_in(kraaifontein_plan))
    assert not wrong, ("approximate times pointing the wrong way:\n  "
                       + "\n  ".join(wrong))


def test_a_rider_is_never_offered_the_same_clock_twice(kraaifontein_plan):
    """
    Two chips reading 07:20, one crisp and one approximate, are one bus to a reader.

    They used to be told apart by their wording, so the moment a bound started saying
    "from 07:20" it stopped matching the stop that prints "07:20" and both appeared. The
    dedupe now keys on the clock, which is what a rider compares.
    """
    dupes = []
    for option in kraaifontein_plan["options"]:
        seen = set()
        for d in option["departures"]:
            pair = (d["board_raw"].split(" ")[-1], str(d["arrive_raw"]).split(" ")[-1])
            if pair in seen:
                dupes.append(f"{option['route_label']}: {pair[0]} to {pair[1]}")
            seen.add(pair)
    assert not dupes, "the same two clocks offered twice on one route:\n  " + \
                      "\n  ".join(dupes)


# ---------------------------------------------------------------------------
# Getting on and off where the rider asked.
# ---------------------------------------------------------------------------

# Two suburbs a kilometre apart, both with a station, and the pair that showed what
# happens when the walking radius reaches past the destination.
ROSEBANK = (-33.9520, 18.4720)
MOWBRAY = (-33.9470, 18.4740)
WOODSTOCK = (-33.9270, 18.4450)


def metres(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    inner = (math.sin(lat1) * math.sin(lat2)
             + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return 6371000 * math.acos(max(-1.0, min(1.0, inner)))


def ends_that_miss_a_nearer_stop(plan, origin, destination, trip_stops) -> list[str]:
    """
    Options that ride past a stop nearer to what the rider searched than the one used.

    A function so it can be shown an answer that IS wrong - see the pure test below.
    `trip_stops` is passed in rather than fetched, for the same reason.
    """
    apart = metres(origin, destination)
    wrong = []
    for o in plan["options"]:
        d = (o["departures"] or [None])[0]
        if d is None:
            continue
        stops = {s["stop_sequence"]: s for s in trip_stops(d["schedule_id"], d["trip_index"])
                 if s.get("lat") is not None}
        board_m = o["board_away_m"] or 0
        alight_m = o["alight_away_m"] or 0

        # Boarding earlier on the run than a stop nearer to where the rider is.
        for q, s in stops.items():
            if d["from_seq"] < q < d["to_seq"]:
                near = metres(origin, (s["lat"], s["lon"]))
                if near < board_m - 50:
                    wrong.append(f"{o['route_label']}: boards {o['board_label']} "
                                 f"{round(board_m)}m from the origin, then passes "
                                 f"{s['name']} at {round(near)}m")
        # Getting off before a stop nearer to where they are going.
        for q, s in stops.items():
            if q > d["to_seq"]:
                near = metres(destination, (s["lat"], s["lon"]))
                if near < alight_m - 50:
                    wrong.append(f"{o['route_label']}: alights {o['alight_label']} "
                                 f"{round(alight_m)}m from the destination, then goes on "
                                 f"to {s['name']} at {round(near)}m")
        # Walking further to reach it than the whole journey is long.
        if board_m >= apart:
            wrong.append(f"{o['route_label']}: {round(board_m)}m to reach "
                         f"{o['board_label']}, further than the {round(apart)}m journey")
        if alight_m >= apart:
            wrong.append(f"{o['route_label']}: set down {round(alight_m)}m away, "
                         f"further than the {round(apart)}m journey")
    return wrong


def test_the_rule_catches_an_answer_that_rides_past_the_stop_asked_for():
    """
    Kraaifontein to Woodstock, as it answered: off at SALT RIVER with WOODSTOCK next.

    Needs neither database nor API. The rule has to go on rejecting this, or the live
    check below is only asserting that the app still runs.
    """
    salt_river = (-33.9270, 18.4650)
    woodstock = (-33.9270, 18.4450)
    stops = [
        {"stop_sequence": 20, "name": "SALT RIVER", "lat": salt_river[0], "lon": salt_river[1]},
        {"stop_sequence": 21, "name": "WOODSTOCK", "lat": woodstock[0], "lon": woodstock[1]},
    ]
    plan = {"options": [{
        "route_label": "Northern Line INBOUND", "board_label": "KRAAIFONTEIN",
        "alight_label": "SALT River", "board_away_m": 1054,
        "alight_away_m": round(metres(WOODSTOCK, salt_river)),
        "departures": [{"schedule_id": 1, "trip_index": 0, "from_seq": 0, "to_seq": 20}],
    }]}
    assert ends_that_miss_a_nearer_stop(plan, KRAAIFONTEIN, WOODSTOCK,
                                        lambda s, t: stops), (
        "alighting at Salt River with Woodstock one stop further on must be rejected")

    # And the same answer, corrected, must pass.
    plan["options"][0]["alight_label"] = "WOODSTOCK"
    plan["options"][0]["alight_away_m"] = round(metres(WOODSTOCK, woodstock))
    plan["options"][0]["departures"][0]["to_seq"] = 21
    assert ends_that_miss_a_nearer_stop(plan, KRAAIFONTEIN, WOODSTOCK,
                                        lambda s, t: stops) == []


def test_the_rule_catches_walking_past_the_destination_to_board():
    """
    Rosebank to Mowbray, as it answered: 1.5km to OBSERVATORY for a journey of 1km.

    Whatever the timetable says, a rider told to walk further than the whole trip before
    boarding has been given an answer they cannot use.
    """
    plan = {"options": [{
        "route_label": "Southern Line OUTBOUND", "board_label": "OBSERVATORY",
        "alight_label": "MOWBRAY", "board_away_m": 1915, "alight_away_m": 174,
        "departures": [{"schedule_id": 1, "trip_index": 0, "from_seq": 3, "to_seq": 4}],
    }]}
    assert ends_that_miss_a_nearer_stop(plan, ROSEBANK, MOWBRAY, lambda s, t: []), (
        "boarding 1.9km away on a 1km journey must be rejected")


@pytest.mark.parametrize("name,origin,destination", [
    ("Kraaifontein to Woodstock", KRAAIFONTEIN, WOODSTOCK),
    ("Rosebank to Mowbray", ROSEBANK, MOWBRAY),
    ("Kraaifontein to the CBD", KRAAIFONTEIN, CBD),
])
def test_a_journey_gets_on_and_off_where_the_rider_asked(name, origin, destination):
    """
    The ends of a journey must match the ends of the search.

    Mukhethwa's words: "on and off should match what i searched". Both of the answers he
    found were built the same way - each end chosen by where it falls on the TRIP rather
    than by how near it is to the place he named - so both are checked here, along with a
    long journey where the walking radius cannot reach past either end.
    """
    plan = get("plan", from_lat=origin[0], from_lon=origin[1],
               to_lat=destination[0], to_lon=destination[1])
    if not plan["options"]:
        pytest.skip(f"no direct journey for {name}")

    seen: dict = {}

    def trip_stops(schedule_id, trip_index):
        key = (schedule_id, trip_index)
        if key not in seen:
            seen[key] = get("trip_stops", schedule_id=schedule_id, trip_index=trip_index,
                            from_seq=0, to_seq=9999)["stops"]
        return seen[key]

    wrong = ends_that_miss_a_nearer_stop(plan, origin, destination, trip_stops)
    assert not wrong, (f"{name} answers with ends the rider did not ask for:\n  "
                       + "\n  ".join(sorted(set(wrong))[:12]))


# ---------------------------------------------------------------------------
# Being able to ask, and being answered.
# ---------------------------------------------------------------------------

def test_every_name_an_operator_prints_can_be_typed_into_the_search():
    """
    Mukhethwa typed "buhrein" and got nothing.

    BUH REIN is a bus stop in Kraaifontein serving a development of that name, and no
    place node in OpenStreetMap carries it. When the search box stopped offering stops -
    rightly, to end the bus/train/place triplicates - 416 of the 584 names the operators
    print went with them, ADDERLEY STR and AKASIA PARK station among them. A rider cannot
    plan to somewhere they cannot name.

    The database question, not the API one, because it is about coverage rather than
    ranking: is every printed name reachable by typing it.
    """
    from gabs_scraper import db

    try:
        conn = db.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {e}")
    try:
        cur = conn.cursor()
        # Compared with the punctuation out, the way the search matches its aliases.
        squash = ("replace(replace(replace(replace(lower({0}),' ',''),chr(39),''),"
                  "'.',''),'-','')")
        cur.execute(f"""
            SELECT DISTINCT s.name FROM stop s
            WHERE s.lat IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM area a
                              WHERE {squash.format('a.name')} = {squash.format('s.name')})
            ORDER BY s.name
            """)
        missing = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    assert not missing, (f"{len(missing)} names an operator prints that nobody can search "
                         f"for: " + ", ".join(missing[:15]))


def test_a_name_typed_as_one_word_still_finds_it():
    """
    "buhrein" is one word to a rider and two to Golden Arrow.

    The search matches on a substring, so the space made the name unfindable rather than
    merely awkward. Every place carries its squashed spelling as an alias.
    """
    for typed, expected in (("buhrein", "BUH REIN"),
                            ("mitchellsplain", "Mitchells Plain"),
                            ("capegate", "CAPE GATE"),
                            ("saltriver", "Salt River")):
        names = [x["name"] for x in get("geocode", q=typed)["results"]]
        assert expected in names, f"{typed!r} does not find {expected}: {names[:5]}"


def test_a_journey_with_a_change_is_offered_even_when_something_runs_direct():
    """
    Kraaifontein to Rosebank: one direct bus, and sixteen ways to do it by train.

    The screen asked for journeys with a change only when the direct search came back
    empty, so the one bus was enough to stop it ever asking - and a rider looking for the
    train was told, in effect, that there isn't one. A direct journey existing does not
    make it the journey they want.
    """
    plan = get("plan", from_lat=KRAAIFONTEIN[0], from_lon=KRAAIFONTEIN[1],
               to_lat=ROSEBANK[0], to_lon=ROSEBANK[1])
    conns = get("connections", from_lat=KRAAIFONTEIN[0], from_lon=KRAAIFONTEIN[1],
                to_lat=ROSEBANK[0], to_lon=ROSEBANK[1])["connections"]
    assert plan["options"], "expected at least one direct journey on this pair"
    assert conns, ("Kraaifontein to Rosebank has journeys with a change and the API must "
                   "say so whether or not something runs straight through")
    # And the train is among them, which is what he could not find.
    kinds = {leg["route_label"] for c in conns for leg in c["legs"]}
    assert any("Line" in k for k in kinds), f"no train among the changes: {sorted(kinds)[:6]}"


def test_a_fare_stating_no_transfer_allowance_is_common_enough_to_matter():
    """
    The count behind TransferAllowanceTest, which is where the rule itself is checked.

    A null transfer column is not a miss: Map.of throws on a null key rather than
    returning the default, so a journey with a change whose two ends happened to have a
    through fare of that kind answered 500 and the screen showed nothing at all.

    The rule is tested in Java, instantly and without a database. What cannot be tested
    there is how much of this data walks into it, and the answer decides whether the rule
    is worth having: a handful would be an edge, and nine thousand is the common case. So
    the count lives here, and it fails if the shape of the data changes enough to make the
    Java test about nothing.

    Asserted rather than swept against the API on purpose. Every pair that reaches this
    path is a slow connections query - all three sampled took over four minutes - and a
    test that takes a quarter of an hour to skip guards nothing at all.
    """
    from gabs_scraper import db

    try:
        conn = db.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {e}")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT count(*) FILTER (WHERE transfers IS NULL), count(*)
            FROM journey_fare WHERE per_ride_cents IS NOT NULL
            """)
        unstated, total = cur.fetchone()
    finally:
        conn.close()

    if total == 0:
        pytest.skip("no priced journeys in this database")
    assert unstated > 0, (
        "every fare now states a transfer allowance, which would make the null-key crash "
        "unreachable - check whether TransferAllowanceTest still guards anything real")


def test_a_place_is_offered_once_however_it_is_spelt():
    """
    The whole point of dropping bus/train/place: one line per place.

    Spelling brought the duplication back by another door. OpenStreetMap maps Fir Grove
    and Firgrove as separate nodes, Golden Arrow prints FIRGROVE, and the list showed all
    three - a choice with nothing to choose between the lines, which is exactly what the
    three kinds used to be. Smartie Town and Sybrand Park were the same.

    A space is not a different place, so the search collapses on the name with the
    punctuation taken out, the same spelling it matches aliases against.
    """
    for typed in ("firgrove", "smartietown", "sybrandpark", "mitchellsplain", "capegate"):
        names = [x["name"] for x in get("geocode", q=typed)["results"]]
        squashed = ["".join(c for c in n.lower() if c.isalnum()) for n in names]
        assert len(squashed) == len(set(squashed)), (
            f"{typed!r} offers the same place more than once: {names}")


def test_a_place_with_no_station_is_told_where_the_nearest_one_is():
    """
    BUH REIN to CAPE TOWN under Metro Rail drew a blank screen.

    No station is within walking distance of BUH REIN, so the plan held only buses, the
    chip hid those, and every "nothing found" banner asks whether the PLAN is empty -
    which it was not. A blank screen is the worst answer the app has: it reads as broken
    rather than as "not from here".

    The reply is the one the destination list already gives for the other end of a
    journey - name the nearest place this does work from - and it has to be verified
    rather than guessed, because an offer the app withdraws when taken up is worse than
    no offer at all. So: the nearest station to the rider, which actually runs a direct
    train to the station nearest their destination.
    """
    origin = get("geocode", q="buh rein")["results"]
    dest = get("geocode", q="cape town")["results"]
    if not origin or not dest:
        pytest.skip("sample places not in this database")
    o, d = origin[0], dest[0]

    # There is indeed no station near BUH REIN, which is why the screen had nothing.
    plan = get("plan", from_lat=o["lat"], from_lon=o["lon"],
               to_lat=d["lat"], to_lon=d["lon"])
    assert not [x for x in plan["options"] if x["operator_kind"] == "train"], (
        "BUH REIN now has a train of its own; this test needs a place that does not")

    near = get("nearest_stops", lat=d["lat"], lon=d["lon"], kind="train",
               radius=20000, limit=1)["stops"]
    assert near, "no station within 20km of the destination"

    origins = get("nearby_origins", lat=o["lat"], lon=o["lon"],
                  to=near[0]["id"], radius=20000)["origins"]
    assert origins, (f"nothing to point a rider at: no station near {o['name']} runs a "
                     f"train to {near[0]['name']}")
    first = origins[0]
    assert first["trip_count"] > 0 and first["earliest"], (
        "a referral must name a station that actually runs the service, and say when")
    # Far enough to be worth saying, which is the whole reason the screen was empty.
    assert first["distance_m"] > 100, "this station is on top of the rider; nothing to refer"


def test_a_journey_with_a_change_never_mixes_the_two_networks():
    """
    The assumption the operator chip now filters journeys-with-a-change on.

    Choosing Golden Arrow said "No bus goes from KRAAIFONTEIN" and then listed twenty-six
    Metrorail journeys underneath it, described as "2 buses" - two answers to two
    different questions on one screen, contradicting each other. The screen now hides a
    journey whose network is not the one chosen, and names the network from the stop the
    API resolved the origin to.

    That is only sound while a journey with a change cannot mix the two, which is true for
    a reason rather than by luck: a connection changes at ONE stop row, and no stop row is
    served by both a bus route and a train route. If that ever stops being true - the
    obvious way being a bus/train interchange, which is worth having - this test fails and
    the chip will need the operator per leg instead of per journey.
    """
    from gabs_scraper import db

    try:
        conn = db.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {e}")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT count(*) FROM (
              SELECT ss.stop_id FROM schedule_stop ss
              JOIN schedule sc ON sc.id = ss.schedule_id
              JOIN timetable t ON t.id = sc.timetable_id
              JOIN route r     ON r.id = t.route_id
              JOIN operator o  ON o.id = r.operator_id
              GROUP BY ss.stop_id HAVING count(DISTINCT o.kind) > 1) x
            """)
        both = cur.fetchone()[0]
    finally:
        conn.close()

    assert both == 0, (
        f"{both} stops are served by both networks, so a journey with a change can now "
        f"mix them - the screen decides which chip a whole journey belongs to from one "
        f"stop, and would label such a journey wrongly")


def test_a_new_operator_does_not_crowd_out_an_old_one():
    """
    The CBD is where every operator is densest, so it is where one can hide another.

    The nearest-stop query keeps six nearest and four busiest, because taking all
    twenty-seven stops inside the walking radius turned a CBD search into eleven seconds.
    That cap was applied per KIND, and MyCiTi and Golden Arrow are both buses - so the day
    MyCiTi loaded, its dense city stations filled the bus allowance and six Golden Arrow
    journeys from the CBD to Woodstock stopped being found. The corpus caught it as a
    LOST line, which is exactly what the corpus is for.

    An allowance each now. Adding an operator must add journeys and never remove them, so
    this asserts that all three answer at once on the journey where they compete hardest.
    """
    plan = get("plan", from_lat=CBD[0], from_lon=CBD[1],
               to_lat=WOODSTOCK[0], to_lon=WOODSTOCK[1])
    codes = {o["operator_code"] for o in plan["options"]}
    loaded = {o["code"] for o in get("operators")["operators"] if o["departures"] > 0}
    missing = loaded - codes
    assert not missing, (
        f"{', '.join(sorted(missing))} has departures loaded but offers nothing from the "
        f"CBD to Woodstock, where every operator runs - the nearest-stop allowance is "
        f"being shared rather than given per operator")


def test_the_chip_filters_by_company_and_not_by_kind():
    """
    Two bus companies do not serve the same places.

    39 places are within walking distance of a MyCiTi stop and of no Golden Arrow stop.
    Asked as "is there a bus near here" - which is what served_bus answers - all 39 are
    offered under the Golden Arrow chip and then found to have no journey. It is the
    failure the kind columns were added to prevent, one operator later, so the question is
    asked per operator now.
    """
    from gabs_scraper import db

    try:
        conn = db.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {e}")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.name FROM area a
            WHERE EXISTS (SELECT 1 FROM area_service x JOIN operator o ON o.id = x.operator_id
                          WHERE x.area_id = a.id AND o.code = 'myciti')
              AND NOT EXISTS (SELECT 1 FROM area_service x JOIN operator o ON o.id = x.operator_id
                              WHERE x.area_id = a.id AND o.code = 'gabs')
            ORDER BY length(a.name), a.name LIMIT 5
            """
        )
        myciti_only = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    if not myciti_only:
        pytest.skip("every MyCiTi place is also reachable by Golden Arrow")

    for name in myciti_only:
        under_gabs = [r["name"] for r in
                      get("geocode", q=name, operator="gabs")["results"]]
        assert name not in under_gabs, (
            f"{name} is offered under the Golden Arrow chip and no Golden Arrow stop is "
            f"within walking distance of it")
        under_myciti = [r["name"] for r in
                        get("geocode", q=name, operator="myciti")["results"]]
        assert name in under_myciti, f"{name} is not offered under the MyCiTi chip"
