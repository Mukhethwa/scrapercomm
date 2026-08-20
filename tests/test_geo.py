import pytest

from gabs_scraper.geo import (
    haversine_m,
    locate_on_path,
    point_to_segment_m,
    slice_path,
)


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


# ---- slice_path: trimming a leg to the part a passenger actually rides ----

def test_slice_path_full_range_is_unchanged():
    path = [[0, 0], [0, 0.01], [0, 0.02]]
    assert slice_path(path, 0.0, 1.0) == [[0, 0], [0, 0.01], [0, 0.02]]


def test_slice_path_trims_head_to_the_exact_midpoint():
    path = [[0, 0], [0, 0.01], [0, 0.02]]
    out = slice_path(path, 0.5, 1.0)
    assert out[0][1] == pytest.approx(0.01, abs=1e-6)   # starts halfway, not at a vertex
    assert out[-1] == [0, 0.02]


def test_slice_path_trims_tail():
    path = [[0, 0], [0, 0.01], [0, 0.02]]
    out = slice_path(path, 0.0, 0.5)
    assert out[0] == [0, 0]
    assert out[-1][1] == pytest.approx(0.01, abs=1e-6)


def test_slice_path_trims_both_ends_within_one_segment():
    # Board and alight both between the same pair of timing points.
    path = [[0, 0], [0, 0.02]]
    out = slice_path(path, 0.25, 0.75)
    assert out[0][1] == pytest.approx(0.005, abs=1e-6)
    assert out[-1][1] == pytest.approx(0.015, abs=1e-6)


def test_slice_path_cut_points_lie_on_the_line():
    path = [[0, 0], [0, 0.01], [0, 0.02]]
    for lat, _ in slice_path(path, 0.3, 0.8):
        assert lat == pytest.approx(0, abs=1e-9)  # never wanders off the road


def test_slice_path_handles_degenerate_input():
    assert slice_path([], 0.2, 0.8) == []
    assert slice_path([[1, 2]], 0.2, 0.8) == [[1, 2]]
    assert slice_path([[0, 0], [0, 0.01]], 0.8, 0.2) == []  # inverted window
