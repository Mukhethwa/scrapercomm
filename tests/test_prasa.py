"""Tests for reading PRASA timetables.

The OCR itself needs Tesseract and an image, so what is tested here is everything around
it: the patterns a cell is matched against, the checks a read grid has to survive, and the
facts pulled out of a page's own wording. Those are where the real mistakes have been.
"""
import numpy as np
import pytest

from prasa_scraper.load import day_type_of, effective_from, route_name
from prasa_scraper.ocr import (PADDED_TIME, TIME, Grid, _blocks, _check,
                               _column_edges, _restore_dropped_hour,
                               clean_station)


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


def test_the_afrikaans_name_is_the_same_station():
    from prasa_scraper.stations import canonical, key
    # One line, two sheets, two languages: the weekend outbound timetable lists VISHOEK
    # where the inbound one lists FISH HOEK, in the same position between KALKBAAI and
    # SUNNY COVE. Loading both spellings puts half the Southern Line out of reach of the
    # other half. No rule derives one from the other, so it is stated.
    assert canonical("VISHOEK") == "FISH HOEK"
    assert key(canonical("VISHOEK")) == key(canonical("FISH HOEK"))


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


# ------------------------------------------------------- finding the OCR engine

def test_a_missing_engine_is_an_error_and_not_an_empty_page():
    # Every cell read is wrapped in a broad except so one failed call costs that cell
    # rather than a three-hour run. That means a missing binary returned "" forty thousand
    # times and the pipeline reported "nothing timetable-shaped here" on page after page
    # of legible timetables - a missing install and a blank page looked identical.
    import prasa_scraper.ocr as ocr

    saved_checked, saved_paths = ocr._checked, ocr._TESSERACT_PATHS
    saved_cmd = ocr.pytesseract.pytesseract.tesseract_cmd
    try:
        ocr._checked = False
        ocr._TESSERACT_PATHS = ("/nowhere/tesseract",)
        ocr.pytesseract.pytesseract.tesseract_cmd = "definitely-not-a-real-binary"
        with pytest.raises(RuntimeError, match="cannot be found"):
            ocr._tesseract()
    finally:
        ocr._checked, ocr._TESSERACT_PATHS = saved_checked, saved_paths
        ocr.pytesseract.pytesseract.tesseract_cmd = saved_cmd


def test_the_engine_is_found_where_the_installer_puts_it():
    import prasa_scraper.ocr as ocr
    # Nothing to assert about the machine running the tests beyond this: whatever the
    # lookup settles on, it must be something that actually runs.
    assert ocr._tesseract().get_tesseract_version()


# ------------------------------------------------- putting back a dropped hour digit

def flagged(times):
    g = grid_with(times)
    _check(g)
    _restore_dropped_hour(g)
    return g


def test_a_dropped_leading_digit_is_restored_when_the_column_proves_it():
    # PRASA prints 17:11, never 7:11, so the cell lost its tens digit rather than saying
    # something unusual. Between 17:09 and 17:20 only one of 07:11 and 17:11 can be true.
    # One cell like this held 304 verified times off the site.
    g = flagged([["17:09"], ["7:11"], ["17:20"]])
    assert g.times[1][0] == "17:11"
    assert g.problems == []


def test_seconds_do_not_stop_the_repair():
    g = flagged([["15:18"], ["5:27:00"], ["15:40"]])
    assert g.times[1][0] == "15:27:00"
    assert g.problems == []


def test_an_ambiguous_cell_is_left_flagged():
    # Nothing published below it, and 07:11 sits after nothing - so both readings are
    # consistent with the column and neither is proven. An unverified time is worse than
    # no time, so the cell stays flagged and the loader will not write it.
    g = Grid(heading="")
    g.times = [["7:11"]]
    g.stations = ["S0"]
    _check(g)
    _restore_dropped_hour(g)
    assert g.times[0][0] == "7:11"


def test_a_padded_hour_is_never_rewritten():
    # 05:00 after 17:00 is a real problem - a whole column read in the wrong order, or a
    # block boundary missed. Quietly turning it into 15:00 would paper over that.
    g = flagged([["17:00"], ["05:00"], ["17:30"]])
    assert g.times[1][0] == "05:00"
    assert any(p.kind == "order" for p in g.problems)


def test_the_repair_does_not_disturb_a_sound_column():
    g = flagged([["05:00"], ["05:10"], ["05:25"]])
    assert [r[0] for r in g.times] == ["05:00", "05:10", "05:25"]
    assert g.problems == []


# -------------------------------------------- what a forced load is allowed to write

def test_a_flagged_cell_is_named_so_a_forced_load_can_drop_it():
    g = grid_with([["17:09"], ["7:11"], ["17:20"], ["oh dear"]])
    _check(g)
    # Both the well-formed-but-unproven cell and the unreadable one are named. The first
    # is the dangerous one: it would insert as 07:11, a train a rider misses by ten hours.
    assert (1, 0) in g.unverified()
    assert (3, 0) in g.unverified()


def test_a_sound_grid_names_no_cells():
    g = grid_with([["05:00"], ["05:10"]])
    _check(g)
    assert g.unverified() == set()


def test_an_unpadded_hour_is_flagged_even_when_the_column_is_happy():
    # 07:11 for 17:11 in a sparse column offends no ordering, so nothing caught it and it
    # loaded as a train ten hours early. PRASA pads, so the cell is wrong on its face.
    g = grid_with([["7:11"], ["", ]])
    _check(g)
    assert any(p.kind == "shape" and "unpadded" in p.detail for p in g.problems)


def test_a_damaged_neighbour_cannot_prove_anything():
    # Two dropped digits in a row would otherwise agree with each other into a confident
    # wrong answer, so only padded neighbours are used as bounds. Neither cell here has a
    # trustworthy neighbour, so neither is repaired.
    g = grid_with([["7:10"], ["7:20"]])
    _check(g)
    _restore_dropped_hour(g)
    assert [r[0] for r in g.times] == ["7:10", "7:20"]
    assert len(g.unverified()) == 2


# ---------------------------------------- telling a table from the page's furniture

def test_a_title_bar_is_not_a_failed_table():
    # The red banner and the footer logos are split off as blocks like anything else.
    # Reporting them as tables that failed made a fully-read page look half lost, and I
    # went looking for missing services that were never missing.
    from prasa_scraper.ocr import _read_block
    import numpy as np
    from PIL import Image

    page = np.zeros((200, PAGE_WIDTH), dtype=bool)
    gray = Image.fromarray(np.full((200, PAGE_WIDTH), 255, dtype=np.uint8))
    grid = _read_block(gray, page, 0, 0, 0, 100, "")     # short, no column rules
    assert grid.problems == []


def test_a_tall_band_with_no_grid_is_still_reported():
    # The Central Line's weekend sheets are printed on a ground that defeats detection
    # outright. Those are full-page tables and a real failure - saying nothing about them
    # is how a missing line goes unnoticed.
    from prasa_scraper.ocr import _read_block
    import numpy as np
    from PIL import Image

    page = np.zeros((900, PAGE_WIDTH), dtype=bool)
    gray = Image.fromarray(np.full((900, PAGE_WIDTH), 255, dtype=np.uint8))
    grid = _read_block(gray, page, 0, 0, 0, 800, "")
    assert any(p.kind == "grid" for p in grid.problems)


# ------------------------------------------- catching the next VISHOEK automatically

def test_the_similarity_threshold_separates_variants_from_neighbours():
    from prasa_scraper.duplicates import SIMILAR, _similar
    from prasa_scraper.stations import key

    # VISHOEK shipped undetected until somebody looked at a page image, which is not a
    # process. These are the two clusters the threshold has to sit between.
    variants = [("VISHOEK", "FISH HOEK"), ("KALKBAAI", "KALK BAY"),
                ("DIEPRIVER", "DIEPRIVIER")]
    different = [("STEENBERG", "MUIZENBERG"), ("WYNBERG", "STEENBERG"),
                 ("RETREAT", "ROSEBANK"), ("NEWLANDS", "LANSDOWNE")]

    for a, b in variants:
        assert _similar(key(a), key(b)) >= SIMILAR, (a, b)
    for a, b in different:
        assert _similar(key(a), key(b)) < SIMILAR, (a, b)


# ------------------------------------- one table, however many rules are drawn in it

def bands_with(column_pitches, height=200):
    """A page of stacked bands, each ruled at its own column pitch."""
    import numpy as np
    ink = np.zeros((height * len(column_pitches), PAGE_WIDTH), dtype=bool)
    for i, pitch in enumerate(column_pitches):
        top = i * height
        for x in range(0, PAGE_WIDTH, pitch):
            ink[top:top + height, x] = True
        if i:
            ink[top, :] = True          # the rule between this band and the one above
    return ink


def test_bands_on_the_same_columns_are_one_table():
    # The Northern Line page is divided into five groups of stations by ruled lines, and
    # all five carry the same 41 columns because they are the same 41 trains. Train 2500
    # runs KRAAIFONTEIN to CAPE TOWN across four of those rules; split there it became a
    # stub to Stikland and an unrelated route out of Bellville, and a rider asking to go
    # from Kraaifontein into town was told no train does it.
    blocks = _blocks(bands_with([66, 66, 66]))
    assert len(blocks) == 1
    assert blocks[0] == (0, 600)


def test_bands_on_different_columns_stay_apart():
    # Where the column layout really does change, the tables really are different, and
    # joining them would read one table's cells at another's column positions - times
    # silently swapped between neighbouring trains, every one of them plausible.
    blocks = _blocks(bands_with([66, 90, 66]))
    assert len(blocks) == 3


def test_a_rule_alone_does_not_divide_a_table():
    # The ink between two rows was never what made them separate tables.
    assert len(_blocks(bands_with([66, 66]))) == 1


# ------------------------------------------------ rows that are not stations

def test_the_platform_row_is_not_a_station():
    from prasa_scraper.ocr import _is_platform_row
    # Bellville's arrivals become its departures, and PRASA prints the platform between
    # them. Once the bands either side are joined, that row lands in the body of the
    # table and every cell in it was reported as a time that was not a time.
    assert _is_platform_row("PLATFORM NO", ["5", "10", "3", "8"])
    assert _is_platform_row("", ["5", "10", "3", "8"])


def test_a_station_is_not_mistaken_for_a_platform_row():
    from prasa_scraper.ocr import _is_platform_row
    # A row of real times, and a row whose times were read badly, are both stations. Only
    # a row that is entirely small integers - or says so - is the platform strip.
    assert not _is_platform_row("RETREAT", ["05:03", "05:18", "05:30"])
    assert not _is_platform_row("RETREAT", ["5", "05:18"])
    assert not _is_platform_row("WYNBERG", [])
