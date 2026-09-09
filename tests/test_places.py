"""Which places the search box offers, and in what order.

Fixtures are real Nominatim responses, trimmed to the fields the code reads. The ordering
fault was invisible from the code - Nominatim answered, the app drew what it was given -
and the filtering question is not visible from the code either: nothing about a hit says
whether a rider could actually board a bus at it.
"""
from gabs_scraper.api import AREA_TYPES, _rank_places

# The four things Nominatim returns for "kraaifontein", in the order it returns them.
# Three are buildings standing in Kraaifontein; the fourth is Kraaifontein.
KRAAIFONTEIN = [
    {"name": "Durbanville Kraaifontein Sea Scout Group", "class": "club", "type": "scout",
     "osm_type": "way", "osm_id": 1446440267, "lat": "-33.86", "lon": "18.68",
     "importance": 0.0,
     "display_name": "Durbanville Kraaifontein Sea Scout Group, 6, King Street"},
    {"name": "Kraaifontein High School", "class": "amenity", "type": "school",
     "osm_type": "way", "osm_id": 1218784370, "lat": "-33.85", "lon": "18.71",
     "importance": 0.0,
     "display_name": "Kraaifontein High School, 3, Sydow Street"},
    {"name": "The Haven Night Shelter Kraaifontein", "class": "amenity",
     "type": "social_facility", "osm_type": "node", "osm_id": 11300086698,
     "lat": "-33.84", "lon": "18.72", "importance": 0.0,
     "display_name": "The Haven Night Shelter Kraaifontein, 20, Van der Ross Road"},
    {"name": "Kraaifontein", "class": "place", "type": "town", "osm_type": "node",
     "osm_id": 262720866, "lat": "-33.85", "lon": "18.72", "importance": 0.424,
     "display_name": "Kraaifontein, City of Cape Town, Western Cape, 7500"},
]


def areas_only(hits):
    """What _nominatim keeps, without going near the network."""
    return [h for h in hits if h.get("class") == "place" and h.get("type") in AREA_TYPES]


def test_only_the_area_survives():
    """
    The school, the shelter and the scout hall are dropped.

    Not because they are wrong places - they exist - but because the planner turns a pin
    into a journey by matching it against the road a bus drives, and a building is not
    somewhere a rider can be told to board.
    """
    out = _rank_places(areas_only(KRAAIFONTEIN), "kraaifontein")
    assert [p["name"] for p in out] == ["Kraaifontein"]


def test_the_area_comes_first_when_several_survive():
    """A name that IS what was typed beats one that merely begins with it."""
    hits = [
        {"name": "Kraaifontein East", "class": "place", "type": "suburb", "osm_type": "node",
         "osm_id": 2, "lat": "-33.84", "lon": "18.73", "importance": 0.1,
         "display_name": "Kraaifontein East"},
        {"name": "Kraaifontein", "class": "place", "type": "town", "osm_type": "node",
         "osm_id": 1, "lat": "-33.85", "lon": "18.72", "importance": 0.424,
         "display_name": "Kraaifontein"},
    ]
    assert [p["name"] for p in _rank_places(hits, "kraaifontein")][0] == "Kraaifontein"


def test_a_shop_is_not_a_place_to_start_a_journey():
    """
    "kraaifontein shoprite" finds a supermarket, and a supermarket is not a bus stop.

    Offering it would have the app answer "a bus passes here" for a point nothing
    published says a bus stops at - the exact claim Golden Arrow's timetables cannot
    support, because they list timing points rather than every kerb.
    """
    shoprite = [{"name": "Shoprite", "class": "shop", "type": "supermarket",
                 "osm_type": "way", "osm_id": 1, "lat": "-33.84", "lon": "18.71",
                 "importance": 0.0, "display_name": "Shoprite, 1st Avenue, Eikendal"}]
    assert _rank_places(areas_only(shoprite), "kraaifontein shoprite") == []


def test_a_province_is_not_an_area_either():
    """"place" also covers a province and an ocean. Western Cape is not a journey."""
    province = [{"name": "Western Cape", "class": "place", "type": "state",
                 "osm_type": "relation", "osm_id": 5, "lat": "-33.0", "lon": "20.0",
                 "importance": 0.8, "display_name": "Western Cape, South Africa"}]
    assert areas_only(province) == []


def test_an_area_mapped_twice_is_one_row():
    """
    Parow is a town and a suburb of the same name, two OSM features.

    Two identical rows is a choice with no difference behind it, so they collapse by name
    rather than by feature id.
    """
    parow = [
        {"name": "Parow", "class": "place", "type": "town", "osm_type": "node",
         "osm_id": 11, "lat": "-33.90", "lon": "18.60", "importance": 0.4,
         "display_name": "Parow, City of Cape Town"},
        {"name": "Parow", "class": "place", "type": "suburb", "osm_type": "relation",
         "osm_id": 22, "lat": "-33.91", "lon": "18.61", "importance": 0.3,
         "display_name": "Parow, Cape Town Ward 70"},
    ]
    assert len(_rank_places(areas_only(parow), "parow")) == 1


def test_a_street_number_is_not_the_name():
    """
    Where Nominatim gives no name, the leading component of display_name is used - and for
    an address that component is the number. The name field is preferred wherever it is
    there, which is why this only has to hold for the fallback.
    """
    numbered = [{"class": "place", "type": "suburb", "lat": "-33.9", "lon": "18.5",
                 "display_name": "6, King Street, Aurora, Cape Town"}]
    assert _rank_places(numbered, "king street")[0]["name"] == "6"


def test_an_empty_query_ranks_nothing():
    assert _rank_places([], "") == []


def test_a_failed_lookup_is_not_an_empty_one():
    """
    None and [] are different answers, and the cache treats them differently.

    They were the same answer once. An audit fired 122 lookups back to back, Nominatim
    rate-limited most of them exactly as its policy says it will, the failures became
    empty lists and the empty lists were cached - so WOODSTOCK reported "no such place"
    for the life of the process. A transient fault, made permanent by remembering it.
    """
    import requests

    from gabs_scraper.api import _nominatim

    saved = requests.get

    def rate_limited(*_a, **_k):
        raise RuntimeError("429 Too Many Requests")

    requests.get = rate_limited          # _nominatim imports requests inside the call
    try:
        assert _nominatim("woodstock") is None
    finally:
        requests.get = saved
