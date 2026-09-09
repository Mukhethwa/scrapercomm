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


def test_the_search_box_offers_areas_and_not_buildings():
    """
    A pin becomes a journey by matching the road a bus drives, so naming a school claims
    a bus passes a spot nothing published says a bus stops at.
    """
    results = get("geocode", q="kraaifontein")["results"]
    names = [r["name"] for r in results]
    assert "Kraaifontein" in names, f"the suburb itself is missing from {names}"
    assert not any("School" in n or "Shelter" in n for n in names), names


def test_an_area_is_only_offered_where_the_network_goes():
    """Ceres is a real town and no service in this database reaches it."""
    assert get("geocode", q="Ceres")["results"] == []
