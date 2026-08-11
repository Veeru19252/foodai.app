"""
Unit tests for the pure geometry/ETA helpers shared by the tracking engine.
No network, no database: these only exercise tracking.py math.
"""

import pytest

import tracking


def test_haversine_known_distance():
    # Roughly the real distance between Spice Garden (MG Road) and the demo
    # home (near Indiranagar) — a few km, definitely not 0.
    a = (12.9755, 77.6039)  # MG Road
    b = (12.9719, 77.6412)  # default customer home
    d = tracking.haversine_km(a, b)
    assert 3.0 < d < 8.0


def test_route_length_matches_haversine():
    a = (12.9755, 77.6039)
    b = (12.9719, 77.6412)
    route = tracking.build_route(a, b)
    straight = tracking.haversine_km(a, b)
    road = tracking.route_length_km(route)
    assert road >= straight * 0.9
    assert road < straight * 3.0


def test_interpolate_position_bounds():
    route = tracking.build_route((12.9755, 77.6039), (12.9719, 77.6412))
    assert tracking.interpolate_position(route, 0.0) == pytest.approx(route[0])
    assert tracking.interpolate_position(route, 1.0) == pytest.approx(route[-1])


def test_estimate_trip_seconds_positive():
    route = tracking.build_route((12.9755, 77.6039), (12.9719, 77.6412))
    seconds = tracking.estimate_trip_seconds(route, avg_speed_kmh=25.0)
    assert seconds > 0


def test_compute_eta_monotonic():
    route = tracking.build_route((12.9755, 77.6039), (12.9719, 77.6412))
    eta0 = tracking.compute_eta(route, 0.0)
    eta_half = tracking.compute_eta(route, 0.5)
    eta1 = tracking.compute_eta(route, 1.0)
    assert eta0 >= eta_half >= eta1 == 0


def test_preset_coordinates_known():
    coords = tracking.preset_coordinates("Koramangala")
    assert len(coords) == 2
    assert all(isinstance(v, float) for v in coords)


def test_preset_coordinates_unknown_raises():
    with pytest.raises(ValueError):
        tracking.preset_coordinates("not-a-place")


def test_compute_distance_eta_known():
    # Spice Garden (MG Road) -> demo home (near Indiranagar): a few km.
    distance_km, eta_min = tracking.compute_distance_eta(
        12.975, 77.606, 12.9719, 77.6412
    )
    assert 3.0 < distance_km < 8.0
    # ETA = road distance / speed + prep buffer, strictly above the buffer.
    assert eta_min > tracking.PREP_BUFFER_MIN
    assert eta_min == pytest.approx(
        distance_km * tracking.ROAD_FACTOR / tracking.AVG_SPEED_KMH * 60
        + tracking.PREP_BUFFER_MIN
    )


def test_compute_distance_eta_zero():
    distance_km, eta_min = tracking.compute_distance_eta(12.97, 77.59, 12.97, 77.59)
    assert distance_km == pytest.approx(0.0)
    assert eta_min == pytest.approx(tracking.PREP_BUFFER_MIN)


def test_compute_distance_eta_is_symmetric():
    a = (12.975, 77.606)
    b = (12.9719, 77.6412)
    d1, _ = tracking.compute_distance_eta(*a, *b)
    d2, _ = tracking.compute_distance_eta(*b, *a)
    assert d1 == pytest.approx(d2)
