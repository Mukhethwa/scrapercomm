"""How the place suggestions are ordered and merged.

Fixtures are real Nominatim responses, trimmed to the fields the ranking reads. They are
here because the ordering fault was invisible from the code: Nominatim answered, the app
showed what it was given, and the answer a rider wanted was simply further down the list
than the browser was prepared to draw.
"""
from gabs_scraper.api import _rank_places

# The four things Nominatim returns for "kraaifontein, Cape Town, South Africa", in the
# order it returns them. The town is last, and every place-of-interest scores zero
# importance, so nothing about this list says the suburb is the likely answer.
KRAAIFONTEIN = [
    {"name": "Durbanville Kraaifontein Sea Scout Group", "osm_type": "way",
     "osm_id": 1446440267, "lat": "-33.86", "lon": "18.68", "importance": 0.0,
     "display_name": "Durbanville Kraaifontein Sea Scout Group, 6, King Street"},
    {"name": "Kraaifontein High School", "osm_type": "way", "osm_id": 1218784370,
     "lat": "-33.85", "lon": "18.71", "importance": 0.0,
     "display_name": "Kraaifontein High School, 3, Sydow Street"},
    {"name": "The Haven Night Shelter Kraaifontein", "osm_type": "node",
     "osm_id": 11300086698, "lat": "-33.84", "lon": "18.72", "importance": 0.0,
     "display_name": "The Haven Night Shelter Kraaifontein, 20, Van der Ross Road"},
    {"name": "Kraaifontein", "osm_type": "node", "osm_id": 262720866,
     "lat": "-33.85", "lon": "18.72", "importance": 0.424,
     "display_name": "Kraaifontein, City of Cape Town, Western Cape, 7500"},
]


def test_the_suburb_comes_first():
    """A name that IS what was typed beats one that merely contains it."""
    out = _rank_places(KRAAIFONTEIN, "kraaifontein")
    assert [p["name"] for p in out][:2] == ["Kraaifontein", "Kraaifontein High School"]


def test_nothing_is_dropped():
    """Four in, four out. Three was the old limit, and the suburb was the fourth."""
    assert len(_rank_places(KRAAIFONTEIN, "kraaifontein")) == 4


def test_a_named_place_survives_a_partial_match():
    """
    "kraaifontein shoprite" finds a feature called simply "Shoprite".

    Half the words typed are the suburb, which is nowhere in the name, so a rule that
    wanted every word would have thrown away the one result the search had.
    """
    shoprite = [{"name": "Shoprite", "osm_type": "way", "osm_id": 1, "lat": "-33.84",
                 "lon": "18.71", "importance": 0.0,
                 "display_name": "Shoprite, 1st Avenue, Eikendal"}]
    out = _rank_places(shoprite, "kraaifontein shoprite")
    assert [p["name"] for p in out] == ["Shoprite"]


def test_one_place_found_by_both_lookups_is_listed_once():
    """
    The bare and suffixed queries overlap, and they disagree about the street.

    Canal Walk comes back on Century Boulevard from one and Century City Drive from the
    other. Same OSM feature, so it is one suggestion, not two that look like a mistake.
    """
    both = [
        {"name": "Canal Walk", "osm_type": "way", "osm_id": 99, "lat": "-33.89",
         "lon": "18.51", "importance": 0.3,
         "display_name": "Canal Walk, Century Boulevard, Milnerton"},
        {"name": "Canal Walk", "osm_type": "way", "osm_id": 99, "lat": "-33.89",
         "lon": "18.51", "importance": 0.3,
         "display_name": "Canal Walk, Century City Drive, Milnerton"},
    ]
    assert len(_rank_places(both, "canal walk")) == 1


def test_a_place_with_no_osm_id_is_deduplicated_by_position():
    """Without a feature id, two readings of one point are still one place."""
    twice = [
        {"lat": "-33.900000", "lon": "18.500000", "display_name": "Somewhere, Cape Town"},
        {"lat": "-33.900001", "lon": "18.500002", "display_name": "Somewhere, Cape Town"},
    ]
    assert len(_rank_places(twice, "somewhere")) == 1


def test_a_street_number_is_not_the_name():
    """
    Where Nominatim gives no name, the leading component of display_name is used - and for
    an address that component is the number. The name field is preferred wherever it is
    there, which is why this only has to hold for the fallback.
    """
    numbered = [{"lat": "-33.9", "lon": "18.5",
                 "display_name": "6, King Street, Aurora, Cape Town"}]
    assert _rank_places(numbered, "king street")[0]["name"] == "6"


def test_an_empty_query_ranks_nothing():
    assert _rank_places([], "") == []
