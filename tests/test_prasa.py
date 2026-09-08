"""Tests for reading PRASA timetables.

The OCR itself needs Tesseract and an image, so what is tested here is everything around
it: the patterns a cell is matched against, the checks a read grid has to survive, and the
facts pulled out of a page's own wording. Those are where the real mistakes have been.
"""
import numpy as np
import pytest

from prasa_scraper.load import day_type_of, effective_from, route_name
from prasa_scraper.ocr import (PADDED_TIME, TIME, Grid, _blocks, _check,
                               _column_edges, clean_station)


# ---------------------------------------------------------------- time shapes

def test_a_plain_time_is_a_time():
    assert TIME.match("05:25")
    assert TIME.match("18:43")


def test_seconds_are_part_of_the_time():
    # The weekend sheets are timed to the half minute and print it. Rejecting these
    # flagged 836 correctly-read cells across the four lines as OCR failures.
    assert TIME.match("05:25:00")
    assert TIME.match("04:48:30")


def test_nonsense_is_not_a_time():
    for bad in ("", "..", "5", "42:55", "90:18", "05:", "1234"):
        assert not TIME.match(bad), bad


def test_a_padded_hour_is_required_when_choosing_between_crops():
    # PRASA never prints "4:25", so a single-digit hour is a dropped digit rather than a
    # reading worth keeping - which is what tells the reader to try another crop.
    assert PADDED_TIME.match("04:25")
    assert not PADDED_TIME.match("4:25")
    assert not PADDED_TIME.match("1:11")


# ---------------------------------------------------------- checking a grid

def grid_with(times, stations=None):
    g = Grid(heading="")
    g.times = times
    g.stations = stations or [f"S{i}" for i in range(len(times))]
    return g


def test_a_column_that_runs_forwards_is_accepted():
    g = grid_with([["05:00"], ["05:10"], ["05:25"]])
    _check(g)
    assert g.problems == []


def test_a_column_that_runs_backwards_is_flagged():
    # A train cannot reach a later stop earlier. This is the check that caught the page
    # being read as one grid when it was three.
    g = grid_with([["11:10"], ["11:20"], ["01:12"]])
    _check(g)
    assert any(p.kind == "order" for p in g.problems)


def test_seconds_do_not_break_the_ordering_check():
    # Reading seconds made the running total a float, and the message that reports a
    # break formatted it as an integer. The whole run died on the page that first hit it.
    g = grid_with([["05:00:30"], ["04:00:00"]])
    _check(g)                       # must not raise
    assert any(p.kind == "order" for p in g.problems)
    assert all(isinstance(p.detail, str) for p in g.problems)


def test_a_cell_that_is_not_a_time_is_flagged():
    g = grid_with([["05:00"], ["oh dear"]])
    _check(g)
    assert any(p.kind == "shape" for p in g.problems)


# ------------------------------------------------------------- finding the grid

# The detection distances scale with page width, so a fixture has to be a realistic
# width or it is testing thresholds nothing ever uses.
PAGE_WIDTH = 3250


def test_stacked_tables_are_found_separately():
    # A page is not one table: a ruled line divides it, and the tables either side have
    # different column counts because they run different trains.
    ink = np.zeros((300, PAGE_WIDTH), dtype=bool)
    ink[120, :] = True                       # a full-width rule
    blocks = _blocks(ink)
    assert len(blocks) == 2
    assert blocks[0][1] <= 121 <= blocks[1][0] + 1


def test_a_short_band_joins_the_table_below_it():
    # The train numbers sit in a strip too short to be a table of their own.
    ink = np.zeros((300, PAGE_WIDTH), dtype=bool)
    ink[20, :] = True
    ink[45, :] = True
    blocks = _blocks(ink)
    assert len(blocks) == 1
    assert blocks[0][0] == 0                 # the strip was kept, not dropped


def test_column_edges_ignore_a_stripe_that_is_not_a_rule():
    # In a shallow block the digits stack: a column of noughts can be as dark as a rule.
    # Edges that do not sit on the table's own pitch are accidents.
    ink = np.zeros((40, PAGE_WIDTH), dtype=bool)
    for x in range(0, PAGE_WIDTH, 66):       # the real rules, every 66px
        ink[:, x] = True
    ink[:, 100] = True                       # an impostor between two of them
    edges = _column_edges(ink)
    assert 100 not in edges
    assert 66 in edges and 132 in edges


# -------------------------------------------------------- reading the wording

@pytest.mark.parametrize("text, expected", [
    ("SOUTHERN LINE WEEKDAY INBOUND TIMETABLE", "WEEKDAY"),
    ("SOUTHERN LINE WEEKEND INBOUND TIMETABLE : OCTOBER 2025", "WEEKEND"),
    ("CAPE FLATS SATURDAY TIMETABLE", "SATURDAY"),
    ("NORTHERN LINE SUNDAY", "SUNDAY"),
    ("#SouthernLineCT : INBOUND Simons Town", None),
])
def test_the_day_type_comes_from_what_the_page_says(text, expected):
    # Every one of these files is named "weekday" and not all of them are.
    assert day_type_of(text) == expected


def test_weekend_is_not_resolved_to_a_particular_day():
    # The sheet says weekend and does not say whether Sunday differs. Calling it Saturday
    # would be inventing a fact about Sunday.
    assert day_type_of("SOUTHERN LINE WEEKEND TIMETABLE") == "WEEKEND"


def test_effective_date_is_read_from_the_page():
    assert effective_from("Effective from 02 February 2026").isoformat() == "2026-02-02"
    assert effective_from("no date here") is None


def test_a_route_is_named_by_where_its_trains_actually_run():
    # Not by the line's endpoints: the Southern Line runs separate Simon's Town and Fish
    # Hoek workings, and a page holds one of them.
    g = Grid(heading="#SouthernLineCT : INBOUND")
    g.stations = ["Fish Hoek", "Kalk Bay", "Cape Town"]
    assert route_name(g) == "FISH HOEK - CAPE TOWN"


def test_a_route_is_named_the_way_its_stations_are_stored():
    # The weekend sheet ends at KALKBAAI and the weekday one at KALK BAY. Naming the route
    # from the raw reading put one line in the catalogue twice, and the second copy named
    # a station that exists nowhere in the stop table.
    g = Grid(heading="#SouthernLineCT : OUTBOUND")
    g.stations = ["Woodstock", "Diepriver", "Kalkbaai"]
    assert route_name(g) == "WOODSTOCK - KALK BAY"


# ---------------------------------------------------------- station names

def test_the_marker_column_is_stripped_from_a_station_name():
    # The A/D column sits beside the name and the rule between them reads as a letter, so
    # "FISH HOEK" came back as "FISH HOEK LA" and became part of the route name.
    assert clean_station("FISH HOEK LA") == "FISH HOEK"
    assert clean_station("SIMON'S TOWN | D") == "SIMON'S TOWN"
    assert clean_station("RETREAT D") == "RETREAT"
    assert clean_station("CAPE TOWN  A") == "CAPE TOWN"


def test_a_station_whose_name_ends_in_a_word_is_left_alone():
    # Only a lone trailing A or D is a marker. A real name is not touched.
    assert clean_station("SALT RIVER") == "SALT RIVER"
    assert clean_station("HARFIELD ROAD") == "HARFIELD ROAD"
    assert clean_station("NONKQUBELA") == "NONKQUBELA"


# --------------------------------------------------------- one name per station

def test_spelling_noise_collapses_to_one_station():
    from prasa_scraper.stations import key
    # Punctuation and stray spaces are reading noise, not different places. Two rows for
    # one station is two halves of a line that never meet.
    assert key("ST JAMES") == key("ST.JAMES")
    assert key("WYNBERG") == key("WY NBERG")
    assert key("HARFIELD ROAD") == key("HARFIELDROAD")


def test_prasas_own_variants_are_stated_not_derived():
    from prasa_scraper.stations import canonical, key
    # The weekday sheet says KALK BAY and the weekend one says KALKBAAI. No rule turns
    # one into the other, so the equivalence has to be written down.
    assert canonical("KALKBAAI") == "KALK BAY"
    assert key(canonical("KALKBAAI")) == key(canonical("KALK BAY"))
    assert canonical("DIEPRIVER") == "DIEPRIVIER"


def test_a_station_is_stored_under_the_spelling_a_rider_reads():
    from prasa_scraper.stations import canonical, key
    # Collapsing variants to one row is only half the job: the row keeps whichever
    # spelling was read first, and "ST.JAMES" in a list of destinations is a reading
    # artefact showing through to a rider. Same station, so the key must not move.
    assert canonical("ST.JAMES") == "ST JAMES"
    assert canonical("MELTONROSE") == "MELTON ROSE"
    assert key("ST.JAMES") == key("ST JAMES")
    assert key("MELTONROSE") == key("MELTON ROSE")


def test_different_stations_stay_different():
    from prasa_scraper.stations import key
    assert key("RETREAT") != key("ROSEBANK")
    assert key("SALT RIVER") != key("SALT ROCK")


def test_the_marker_column_leaves_more_than_a_bare_letter():
    from prasa_scraper.ocr import clean_station
    # "RETREAT I)" turned up where the rule and the A/D marker were read together.
    assert clean_station("RETREAT I)") == "RETREAT"
    assert clean_station("RETREAT (D)") == "RETREAT"
