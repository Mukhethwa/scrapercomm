"""Reading MyCiTi's timetables, and the two ways that goes wrong quietly.

MyCiTi publishes a clean table per route, so most of this reads itself. What does not is
either end of the reading: a service that runs off the bottom of a page and continues on
the next, and a stop name that OpenStreetMap puts in the wrong town.

Both fail silently. A direction printed across three pages read page-by-page gives three
routes each with a third of the service, and every count still adds up. A stop matched to
the wrong Avondale gives a position, a plausible-looking map pin, and journeys that
cannot be made.
"""
from __future__ import annotations

import os

import pytest

from myciti_scraper.load import direction_label, route_name
from myciti_scraper.parse import Page, Run, day_type_of, runs
from myciti_scraper.positions import IMPOSSIBLE_KMH, implausible, metres, squash

DATA = os.path.join("data", "myciti")


def page(number, day_type, direction, stops, times, route="214A", title="PARKLANDS"):
    return Page(number=number, route=route, title=title, day_type=day_type,
                direction=direction, stops=list(stops),
                times=[list(r) for r in times])


def test_the_day_a_page_is_for():
    """
    Three headings, and the longest has to win.

    "SUNDAYS AND PUBLIC HOLIDAYS" contains "SUNDAYS", so a shorter match tested first
    would read the whole phrase as Sunday. It is Sunday here either way - MyCiTi runs one
    service for both - and the ordering is what keeps the public-holiday case from being
    silently lost if they ever split.
    """
    assert day_type_of("MONDAYS TO FRIDAYS Peak fare period") == "WEEKDAY"
    assert day_type_of("SATURDAYS Peak fare period") == "SATURDAY"
    assert day_type_of("SUNDAYS AND PUBLIC HOLIDAYS Peak fare") == "SUNDAY"
    assert day_type_of("101: VREDEHOEK - GARDENS") is None


def test_a_direction_printed_across_pages_is_one_service():
    """
    Route 214a spends three pages on one weekday direction, 37 departures at a time.

    Read page by page that is three services of a third the size each, and nothing about
    the totals looks wrong: 23 stops, times in every cell, three plausible timetables.
    The only way to notice is to know that the stops are identical and the headings match.
    """
    stops = ["Stables Turnaround", "Omuramba", "Marine Circle"]
    a = page(1, "WEEKDAY", "To 214a Marine Circle", stops,
             [["05:00", "06:00"], ["05:10", "06:10"], ["05:20", "06:20"]])
    b = page(2, "WEEKDAY", "To 214a Marine Circle", stops,
             [["07:00"], ["07:10"], ["07:20"]])
    joined, notes = runs([a, b])
    assert len(joined) == 1, f"expected one service, got {len(joined)}"
    assert joined[0].pages == [1, 2]
    assert joined[0].trips == 3
    assert joined[0].times[0] == ["05:00", "06:00", "07:00"]
    assert not notes


def test_pages_that_disagree_about_their_stops_are_not_joined():
    """
    The loop routes head both halves of the circuit for the same terminus.

    101 runs Civic Centre to Wexford and then Wexford back to Civic Centre, and the
    outward half is headed "To 101 Vredehoek" on a page whose stops are nothing like the
    return half's. Joined on the heading alone, one half's times would be hung on the
    other half's stops - every stop would have a time and every time would be wrong.
    """
    a = page(1, "WEEKDAY", "To 101 Vredehoek", ["Civic Centre", "Adderley"],
             [["05:50"], ["05:53"]], route="101")
    b = page(2, "WEEKDAY", "To 101 Vredehoek", ["Wexford", "St James"],
             [["06:12"], ["06:13"]], route="101")
    joined, notes = runs([a, b])
    assert len(joined) == 2, "pages listing different stops are different services"
    assert notes and "different stops" in notes[0]


def test_a_service_keeps_its_own_days_apart():
    """A Saturday page must never join a weekday one, however alike the stops."""
    stops = ["Kuyasa", "Civic Centre"]
    a = page(1, "WEEKDAY", "To D01 Civic Centre", stops, [["05:00"], ["06:00"]])
    b = page(2, "SATURDAY", "To D01 Civic Centre", stops, [["05:30"], ["06:30"]])
    joined, _ = runs([a, b])
    assert len(joined) == 2
    assert {r.day_type for r in joined} == {"WEEKDAY", "SATURDAY"}


def test_the_route_number_leads_the_name():
    """
    A rider looks for "D01" on the front of the bus.

    Golden Arrow has no equivalent - it names routes and numbers only timetables - so a
    MyCiTi label reads differently on purpose.
    """
    run = Run(route="D01", title="KHAYELITSHA EAST - CIVIC CENTRE", day_type="WEEKDAY",
              direction="To D01 Civic Centre", pages=[1], stops=["Kuyasa"], times=[["05:00"]])
    assert route_name(run).startswith("D01: ")
    assert direction_label(run) == "D01 to Civic Centre"


def test_a_direction_that_does_not_repeat_the_route_number():
    """"To Waterfront" has no number to strip; it must survive intact."""
    run = Run(route="T01", title="DUNOON - WATERFRONT", day_type="WEEKDAY",
              direction="To Waterfront", pages=[1], stops=["Dunoon"], times=[["05:00"]])
    assert direction_label(run) == "T01 to Waterfront"


def test_a_name_in_the_wrong_town_is_caught_by_the_timetable():
    """
    Every object OpenStreetMap calls "Avondale" is in Parow, 38km from the Atlantis
    suburb of that name where route 241 actually calls.

    Nothing about the candidates looks wrong: there are six of them and they agree with
    each other to within a few hundred metres, so every check that asks "do these cluster"
    says yes. The timetable is what knows better - 241 reaches Avondale three minutes
    after leaving Atlantis Station, and no bus covers 38km in three minutes.

    This is the check that was missing when nineteen Golden Arrow stops were re-geocoded
    onto their town centroids and scored a perfect detour of zero.
    """
    atlantis = (-33.5632, 18.4914)
    parow = (-33.8978, 18.5931)
    placed = {1: atlantis, 2: parow, 3: (-33.5640, 18.4930)}
    # Atlantis Station 22:00, "Avondale" 22:03, a real Atlantis stop 22:05.
    sequences = [[(1, "22:00"), (2, "22:03"), (3, "22:05")]]
    caught = implausible(placed, sequences)
    assert 2 in caught, "a stop 38km away three minutes later must be rejected"
    assert caught[2] > IMPOSSIBLE_KMH

    # And the same shape, correctly placed, must pass.
    placed[2] = (-33.5650, 18.4920)
    assert implausible(placed, sequences) == {}


def test_the_check_leaves_a_long_trunk_route_alone():
    """
    Atlantis to the Civic Centre is 40km of real service and must not be rejected.

    A rule that only looked at distance would throw the T02 away with the bad matches,
    which is why the test is a speed: forty kilometres in fifty minutes is a bus, and
    forty kilometres in three minutes is a mistake.
    """
    placed = {1: (-33.5632, 18.4914), 2: (-33.9206, 18.4296)}
    sequences = [[(1, "05:00"), (2, "05:50")]]
    assert implausible(placed, sequences) == {}


def test_a_name_is_matched_with_the_punctuation_out():
    assert squash("Stables Turnaround") == "stablesturnaround"
    assert squash("Salt River Rail") == squash("SALT RIVER RAIL")
    assert squash("Simon's Town") == squash("Simons Town")


@pytest.mark.skipif(not os.environ.get("COMMUTTR_READ_PDFS"),
                    reason="set COMMUTTR_READ_PDFS=1 to read the real timetables")
@pytest.mark.skipif(not os.path.isdir(DATA) or not os.listdir(DATA),
                    reason="the MyCiTi timetables are not in data/")
def test_the_published_timetables_still_read():
    """
    Real files, if they are here and if asked for. Four of them, chosen for their shapes.

    OFF BY DEFAULT, and not because it is merely slow. On its own it reads four PDFs in
    about a minute. Run at the end of the whole suite it took two hours and fifty-five
    minutes for the same four files - a hundred and fifty times slower - while every other
    test in the run finished inside thirty seconds.

    That interaction is not understood. It is not the logging that pdfminer does about
    fonts, which is disabled here and in the pipeline; the likeliest explanation left is
    heap pressure from the megabytes of plan JSON the invariants pull down just before,
    against a parser that allocates heavily per page. Guessing at it is not worth an
    unpredictable suite, so the reading is opt-in:

        COMMUTTR_READ_PDFS=1 python -m pytest tests/test_myciti.py

    and the whole set is swept by `python -m myciti_scraper.pipeline --dry-run`, which is
    the command to run when the parser changes. The rules the parser turns on are tested
    above without reading anything.

    Skipped rather than mocked. The parser's whole job is to read somebody else's PDF, so
    a test that reads a PDF this repository wrote would be testing nothing.

    Each one is here for a reason the others do not cover:

        101   a loop, whose two halves are headed for the same terminus
        214a  a direction printed across three pages
        D01   the plainest possible case, one page per direction per day
        T01   a trunk route whose pages carry a second table beside the timetable

    """
    import logging

    logging.disable(logging.ERROR)
    from myciti_scraper.pipeline import read_all

    paths = [os.path.join(DATA, f"{r}-timetable.pdf")
             for r in ("101", "214a", "D01", "T01")]
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        pytest.skip("none of the sampled timetables are in data/")

    services, notes = read_all(paths)
    assert services, "no service came out of any file"
    assert {r.day_type for _, r in services} == {"WEEKDAY", "SATURDAY", "SUNDAY"}
    # Six services each: two directions on each of three kinds of day.
    by_route = {}
    for _, run in services:
        by_route.setdefault(run.route, []).append(run)
    for route, found in by_route.items():
        assert len(found) == 6, f"{route}: {len(found)} services, expected 6"
    # Every service has stops and at least one departure, or it is not a service.
    for _path, run in services:
        assert run.stops, f"{run.route} {run.direction}: no stops"
        assert run.trips >= 1, f"{run.route} {run.direction}: no departures"
        assert len(run.times) == len(run.stops)
    # 214a is the one that has to be joined across pages to come out whole.
    joined = [r for r in by_route.get("214A", []) if r.day_type == "WEEKDAY"]
    assert joined and max(r.trips for r in joined) > 90, (
        "214a's weekday service spans three pages and should exceed ninety departures")
