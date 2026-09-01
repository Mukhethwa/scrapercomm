from gabs_scraper.fares import RIDES, _squash, _tokens, _zone_labels, cents, parse


def test_cents_plain_price():
    assert cents("R87.00") == 8700


def test_cents_thousands_are_space_separated():
    # The page writes "R1 008.00", sometimes with a non-breaking space.
    assert cents("R1 008.00") == 100800
    assert cents("R1\xa0008.00") == 100800


def test_cents_of_nothing_is_none():
    assert cents("") is None
    assert cents("-") is None


def test_cents_never_goes_through_a_float():
    # 0.1 + 0.2 arithmetic has no place anywhere near a fare.
    assert cents("R114.50") == 11450
    assert isinstance(cents("R114.50"), int)


def test_products_carry_the_documented_ride_counts():
    # "Weekly" is 10 rides and "Monthly" is 48 - not 7 days and not a month. Every
    # per-ride price we show depends on these being right.
    assert RIDES == {"five_ride": 5, "weekly": 10, "monthly": 48}


def test_tokens_drop_the_route_qualifier():
    assert _tokens("Atlantis via Killarney") == ["ATLANTIS"]
    assert _tokens("Bloubergstrand (via Killarney)") == ["BLOUBERGSTRAND"]


def test_tokens_expand_our_abbreviations():
    assert _tokens("KOEBERG STN") == ["KOEBERG", "STATION"]
    assert _tokens("Koeberg Station") == ["KOEBERG", "STATION"]


def test_squash_ignores_how_a_name_is_spaced():
    assert _squash("Blue Downs") == _squash("BLUEDOWNS")
    assert _squash("Summer Greens") == _squash("Summergreens")


def test_zone_naming_two_places_yields_both():
    assert _zone_labels("Athlone / Athlone Industria") == ["Athlone", "Athlone Industria"]


SAMPLE = """
<div style = "padding-left:18px" >Airport Industria to</div>
<table><thead><tr><th>Destination</th><th>Code</th><th>5 Ride</th><th>Weekly</th>
<th>Monthly</th><th>Transfers</th></tr></thead><tbody>
<tr><td>Blue Downs</td><td>AIBD</td><td>R123.50</td><td>R229.00</td><td>R1 008.00</td><td>Zero</td></tr>
<tr><td>Nyanga</td><td>NYAI</td><td>R76.50</td><td>R142.00</td><td>R625.00</td><td>One</td></tr>
</tbody></table>
"""


def test_parse_reads_a_group_into_rows():
    rows = parse(SAMPLE)
    assert len(rows) == 2
    first = rows[0]
    assert first["origin_zone"] == "Airport Industria"
    assert first["destination_zone"] == "Blue Downs"
    assert first["code"] == "AIBD"
    assert first["five_ride_cents"] == 12350
    assert first["monthly_cents"] == 100800
    assert first["transfers"] == "Zero"


def test_parse_ignores_the_header_row():
    # The header is <th>, not <td>, so it must never arrive as a fare.
    assert all(r["code"] != "Code" for r in parse(SAMPLE))
