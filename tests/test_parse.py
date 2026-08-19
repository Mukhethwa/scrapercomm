from pathlib import Path

import pytest

from gabs_scraper.parse import parse_pdf

SAMPLES = Path(__file__).parent / "samples"


@pytest.fixture(scope="module")
def nyanga():
    return parse_pdf(str(SAMPLES / "NYANGA_AIRPORT_BELLVILLE_004401.pdf"))


@pytest.fixture(scope="module")
def ph():
    return parse_pdf(str(SAMPLES / "AIRPORT_BELLVILLE_PH_004401.pdf"))


@pytest.fixture(scope="module")
def single():
    return parse_pdf(str(SAMPLES / "AIRPORT_CAPE_TOWN_012002.pdf"))


def _weekday_p1(pt):
    return [s for s in pt.schedules if s.page_number == 1 and s.day_type == "WEEKDAY"][0]


def _val(trip, stop):
    for st in trip.times:
        if st.stop_name == stop:
            return st.departure_time
    return None


def test_two_pages(nyanga):
    assert nyanga.page_count == 2
    assert {s.page_number for s in nyanga.schedules} == {1, 2}


def test_direction_labels(nyanga):
    labels = {s.direction_label for s in nyanga.schedules}
    assert "NYANGA - AIRPORT IND - BELLVILLE" in labels
    assert "BELLVILLE - AIRPORT IND - NYANGA" in labels


def test_weekday_has_key_stops(nyanga):
    wd = _weekday_p1(nyanga)
    assert "NYANGA TERM" in wd.stops
    assert "BELLVILLE" in wd.stops


def test_first_trip_times(nyanga):
    wd = _weekday_p1(nyanga)
    matches = [
        t for t in wd.trips
        if _val(t, "NYANGA TERM") == "05:40" and _val(t, "BELLVILLE") == "06:05"
    ]
    assert matches, "expected a trip NYANGA TERM 05:40 -> BELLVILLE 06:05"


def test_via_cell(nyanga):
    wd = _weekday_p1(nyanga)
    via = [
        st for t in wd.trips for st in t.times
        if st.stop_name == "GUGULETU" and st.cell_type == "VIA"
    ]
    assert via


def test_note_suffix_split(nyanga):
    wd = _weekday_p1(nyanga)
    cells = [
        st for t in wd.trips for st in t.times
        if st.stop_name == "NYANGA TERM" and st.note_code == "a"
    ]
    assert any(c.departure_time == "05:30" for c in cells)


def test_sunday_no_service(nyanga):
    suns = [s for s in nyanga.schedules if s.day_type == "SUNDAY"]
    assert suns and all(s.no_service for s in suns)


def test_notes_parsed(nyanga):
    codes = {n.code: n.description for n in nyanga.notes}
    assert codes.get("a") == "Mondays,Tuesdays,Wednesdays,Thursdays"
    assert codes.get("b") == "Fridays"


def test_section_metadata(nyanga):
    wd = _weekday_p1(nyanga)
    assert wd.section_timetable_number == "004401"
    assert wd.section_effective_date == "2026-06-22"
    assert wd.day_label == "MONDAYS TO FRIDAYS"


def test_ph_daytype_and_bundling(ph):
    assert ph.schedules and all(s.day_type == "PUBLIC_HOLIDAY" for s in ph.schedules)
    p2 = [s for s in ph.schedules if s.page_number == 2]
    assert p2 and p2[0].direction_label == "KHAYELITSHA - PANORAMA"
    assert p2[0].section_timetable_number == "004501"


def test_single_page(single):
    assert single.page_count == 1
    dts = {s.day_type for s in single.schedules}
    assert {"WEEKDAY", "SATURDAY", "SUNDAY"} <= dts


def test_raw_text_retained(nyanga):
    assert "NYANGA TERM" in nyanga.raw_text
    assert len(nyanga.raw_text) > 100


def test_wrapped_blocks_concatenate_not_duplicate():
    # This PDF wraps to stacked grid blocks (>22 trips). Blocks must concatenate
    # as more trips for the same stops, not repeat the stops.
    pt = parse_pdf(str(SAMPLES / "CAPE_TOWN_MAKHAZA_014301.pdf"))
    sch = [s for s in pt.schedules
           if s.direction_label.startswith("CAPE TOWN") and s.day_type == "WEEKDAY"][0]
    assert len(sch.stops) == len(set(sch.stops)), "stacked blocks duplicated the stops"
    assert len(sch.trips) > 22, "wrapped trips were not concatenated"

    def tv(trip, stop):
        for st in trip.times:
            if st.stop_name == stop and st.cell_type == "TIME":
                return st.departure_time
        return None

    seen_first = False
    for t in sch.trips:
        if tv(t, "CAPE TOWN") == "06:00":
            assert tv(t, "MAKHAZA") == "07:15"  # sane ~75-min direct trip
            seen_first = True
    assert seen_first


def test_no_separator_row_captured_as_stop():
    import re

    # This PDF uses pipe-bordered separator rows that must NOT become stops.
    pt = parse_pdf(str(SAMPLES / "BELHAR_CAPE_TOWN_003001.pdf"))
    names = [st for sch in pt.schedules for st in sch.stops]
    assert names
    assert all(re.search(r"[A-Za-z0-9]", n) for n in names), "a separator row leaked in as a stop"
