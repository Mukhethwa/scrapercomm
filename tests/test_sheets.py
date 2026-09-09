"""Reading Metrorail's published spreadsheets.

There is nothing to check the reader against here - a time in a spreadsheet is a time, not
a guess about some pixels - so what these cover is the shape of the sheets, which varies
more than the data in them does.
"""
import datetime

from prasa_scraper.sheets import _same_station, _time, direction_of, line_of


# ------------------------------------------------------------------ cell values

def test_a_time_keeps_the_seconds_prasa_prints():
    # The weekend trains are timed to the half minute and the sheet holds a real time
    # value, so the seconds arrive exactly rather than being read off an image.
    assert _time(datetime.time(5, 32, 30)) == "05:32:30"
    assert _time(datetime.time(5, 32)) == "05:32:00"


def test_the_no_service_marker_is_nothing():
    # ".." is the sheet saying this train does not stop here.
    assert _time("..") == ""
    assert _time(None) == ""
    assert _time("") == ""


# ------------------------------------------------------------------ which line

def test_a_line_is_named_however_the_sheet_says_it():
    # Five sheets, five ways of naming the same handful of lines - and one whose only text
    # above the header is "PLATFORM NO.", leaving the filename to say.
    assert line_of("Central Line Inbound", "Central-Line-Inbound-Weekday-1.xlsx") == "Central Line"
    assert line_of("Monte Vista Inbound", "x.xlsx") == "Monte Vista Line"
    assert line_of("Monte Vista (Bellville to cape Town Inbound)", "y.xlsx") == "Monte Vista Line"
    assert line_of("", "Monte-Vista-Line-Outbound-Weekday-1.xlsx") == "Monte Vista Line"
    assert line_of("Cape Flats Line Outbound", "z.xlsx") == "Cape Flats Line"


def test_a_descriptive_title_does_not_become_a_line():
    # Parsing "<words> Line" out of the wording produced "Monte Vista Saturday Bellville to
    # Cape Town Line", which is not a line and would have been a route in the catalogue.
    assert line_of("Monte Vista (Bellville to cape Town Inbound) SATURDAY",
                   "Monte-Vista-Saturday-Bellville-to-Cape-Town-Inbound.xlsx") == "Monte Vista Line"


def test_the_direction_is_read_from_either():
    assert direction_of("Southern Line Outbound", "a.xlsx") == "OUTBOUND"
    assert direction_of("", "Central-Line-Outbound-Saturday.xlsx") == "OUTBOUND"
    assert direction_of("Southern Line Inbound", "a.xlsx") == "INBOUND"


# --------------------------------------------------- arrival and departure are one call

def test_a_repeated_station_is_one_call():
    # The Saturday sheets list each station twice, arrival then departure, one minute
    # apart. Two rows would tell a rider a 27-station line has 54 stops.
    assert _same_station("WOODSTOCK", "WOODSTOCK")
    assert _same_station("RETREAT (A)", "RETREAT (D)")
    assert _same_station("FISH HOEK (A)", "FISH HOEK (D)")


def test_two_spellings_of_one_station_are_one_call():
    # Southern Saturday prints KALKBAAI and KALK BAY as consecutive rows - the arrival and
    # the departure of the same call, spelled two ways in one file.
    assert _same_station("KALKBAAI", "KALK BAY")
    assert _same_station("ST.JAMES", "ST JAMES")


def test_different_stations_are_not_merged():
    assert not _same_station("WOODSTOCK", "SALT RIVER")
    assert not _same_station("RETREAT", "STEENBERG")
    assert not _same_station("", "WOODSTOCK")
