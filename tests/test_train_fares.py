"""What a Metrorail journey costs, and how far the app thinks it is.

Two different things can go wrong here and only one of them is arithmetic.

The bands are transcribed by hand from a scanned announcement whose OCR is unusable for
money - it read "R9,50" as "R950" - so the numbers below are a second copy of what was read
off the page. If someone edits ZONES, these fail, and that is the point: a fare should not
be able to change quietly.

The distance is the subtler one. Summing along the line looked obviously right and made
Cape Town to Kraaifontein 202km against a real 30km, because a loaded schedule crosses
between branches and is not a physical path. It would have sold a Zone 2 trip at Zone 4.
The eleven-distance check below is the one that caught it, kept so it cannot come back.
"""
from __future__ import annotations

import pytest

from prasa_scraper.fares import ZONES, km, zone_for

# Published Metrorail distances from Cape Town, in kilometres, and the band each belongs
# in. Real journeys, used because a fare rule is only as good as the distances it sorts.
FROM_CAPE_TOWN = {
    "WOODSTOCK": 2, "SALT RIVER": 3, "WYNBERG": 14, "MUIZENBERG": 25,
    "BELLVILLE": 26, "KRAAIFONTEIN": 30, "KHAYELITSHA": 35, "STRAND": 50,
    "PAARL": 60, "WELLINGTON": 72,
}


def test_the_four_bands_are_what_the_announcement_prints():
    """
    Zone 1 R10, Zone 2 R12, Zone 3 R14, Zone 4 R15 for a single.

    A second copy of the numbers read off PRASA's page, so an edit to ZONES has to be
    deliberate rather than a slip.
    """
    printed = {
        #        upper km, single, return, weekly M-F, weekly M-S, monthly
        "Z1": (        15,   1000,   2000,       6000,       7500,   18000),
        "Z2": (        40,   1200,   2400,       7000,       8000,   22000),
        "Z3": (        60,   1400,   2800,       8000,      10000,   25000),
        "Z4": (      None,   1500,   3000,       9000,      12000,   28000),
    }
    loaded = {label: (upper, single, ret, wk_mf, wk_ms, monthly)
              for upper, label, single, ret, wk_mf, wk_ms, monthly in ZONES}
    assert loaded == printed


def test_a_return_is_twice_a_single():
    """True in every band, which is worth pinning because it is not true of the weeklies."""
    for _, label, single, ret, *_ in ZONES:
        assert ret == single * 2, f"{label}: return {ret} is not twice single {single}"


def test_the_boundaries_fall_where_the_announcement_says():
    """
    1-15km, 16-40km, 41-60km, over 60km.

    Boundaries are where a band rule is wrong if it is wrong at all, and a kilometre
    either way is two rand to somebody.
    """
    assert zone_for(1)[0] == "Z1"
    assert zone_for(15)[0] == "Z1"
    assert zone_for(15.5)[0] == "Z2"
    assert zone_for(16)[0] == "Z2"
    assert zone_for(40)[0] == "Z2"
    assert zone_for(41)[0] == "Z3"
    assert zone_for(60)[0] == "Z3"
    assert zone_for(60.1)[0] == "Z4"
    assert zone_for(500)[0] == "Z4"


def test_a_longer_journey_never_costs_less():
    """The fare rises with distance, at every band edge and in between."""
    last = 0
    for distance in range(1, 120):
        single = zone_for(distance)[1]
        assert single >= last, f"{distance}km costs less than {distance - 1}km"
        last = single


def test_straight_line_puts_every_known_journey_in_the_right_band():
    """
    The check that caught the 202km bug.

    A train follows the line and PRASA charges for travel distance, so measuring across
    country is the wrong measure - it is used anyway because the alternative was worse,
    and it is only defensible while it keeps landing in the same band as the real
    distance. This asserts that it does, for every journey whose length is published.
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
            SELECT s.name, s.lat, s.lon
            FROM stop s JOIN operator o ON o.id = s.operator_id AND o.kind = 'train'
            WHERE s.lat IS NOT NULL
            """
        )
        where = {n: (float(a), float(b)) for n, a, b in cur.fetchall()}
    finally:
        conn.close()

    if "CAPE TOWN" not in where:
        pytest.skip("no stations loaded")

    wrong = []
    for station, real_km in FROM_CAPE_TOWN.items():
        if station not in where:
            continue
        straight = km(where["CAPE TOWN"], where[station])
        by_straight, by_real = zone_for(straight)[0], zone_for(real_km)[0]
        if by_straight != by_real:
            wrong.append(f"{station}: {straight:.1f}km straight is {by_straight}, "
                         f"{real_km}km by rail is {by_real}")
    assert not wrong, ("the straight line no longer agrees with the railway on which band "
                       "a journey is in:\n  " + "\n  ".join(wrong))


def test_the_straight_line_never_exceeds_the_railway():
    """
    A train cannot take a shorter path than the crow.

    Which is why using it is safe: where it is wrong it puts a journey in a cheaper band,
    and undercharging on a screen is a smaller wrong than overcharging.
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
            SELECT s.name, s.lat, s.lon
            FROM stop s JOIN operator o ON o.id = s.operator_id AND o.kind = 'train'
            WHERE s.lat IS NOT NULL
            """
        )
        where = {n: (float(a), float(b)) for n, a, b in cur.fetchall()}
    finally:
        conn.close()

    if "CAPE TOWN" not in where:
        pytest.skip("no stations loaded")

    for station, real_km in FROM_CAPE_TOWN.items():
        if station not in where:
            continue
        straight = km(where["CAPE TOWN"], where[station])
        assert straight <= real_km + 1, (
            f"{station}: {straight:.1f}km straight exceeds {real_km}km of railway, "
            f"which means one of the two is wrong")
