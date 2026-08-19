from gabs_scraper.geo import haversine_m, point_to_segment_m, locate_on_path


def test_haversine_one_degree_lat():
    d = haversine_m(0, 0, 1, 0)
    assert 110_000 < d < 112_000  # ~111 km


def test_point_to_segment_perpendicular():
    # segment along longitude 0..0.01 at the equator; point offset ~0.001deg lat, mid-way
    d, t = point_to_segment_m(0.001, 0.005, 0, 0, 0, 0.01)
    assert 0.4 < t < 0.6
    assert 100 < d < 125  # ~111 m


def test_point_beyond_segment_clamps_to_end():
    _, t = point_to_segment_m(0, 0.02, 0, 0, 0, 0.01)
    assert t == 1.0


def test_locate_on_path_midpoint():
    path = [[0, 0], [0, 0.01], [0, 0.02]]
    total = haversine_m(0, 0, 0, 0.02)
    d, f = locate_on_path(path, total, 0.0005, 0.01)
    assert 0.45 < f < 0.55
    assert d < 80


def test_locate_far_point_is_far():
    path = [[0, 0], [0, 0.01]]
    d, _ = locate_on_path(path, None, 0.05, 0.005)  # ~5.5 km off
    assert d > 5_000
