"""Unit tests for the shared tracking state.

`backend/tracking_state.py` is the single source of truth for the customer's
map: the REST endpoint and the WebSocket simulator both call it, so anything
wrong here is wrong in both views at once. These were the only untested
functions in the backend, and they carry the ETA and marker position, so the
arithmetic and the staleness rules are pinned here directly.

`order_route` is stubbed to a fixed synthetic route: the real one calls the
OSRM API, which would make these tests slow, flaky, and network-dependent.
The projection math under test never looks anything up.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

import tracking

from backend import tracking_state as ts

# A straight west-to-east route at constant latitude, so longitude maps
# linearly onto distance and the expected progress at each point is obvious.
#
#   (73.000) -- 25% -- (73.025) -- 50% -- (73.050) -- 75% -- (73.075) -- 100% -- (73.100)
ROUTE = (
    (18.5, 73.000),
    (18.5, 73.025),
    (18.5, 73.050),
    (18.5, 73.075),
    (18.5, 73.100),
)
ROUTE_KM = 10.6


class FakeOrder:
    """Minimal stand-in: every function here reads plain attributes."""

    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.status = kw.get("status", "OUT_FOR_DELIVERY")
        self.restaurant_id = kw.get("restaurant_id", 1)
        self.restaurant = kw.get("restaurant")
        self.customer = kw.get("customer")
        self.delivery_lat = kw.get("delivery_lat", 18.4089)
        self.delivery_lng = kw.get("delivery_lng", 73.8757)
        self.delivery_address = kw.get("delivery_address", "1 Test Lane")
        self.delivery_city = kw.get("delivery_city", "Pune")
        self.created_at = kw.get("created_at", datetime(2026, 10, 1, 11, 0, 0))
        self.driver_lat = kw.get("driver_lat")
        self.driver_lng = kw.get("driver_lng")
        self.driver_updated_at = kw.get("driver_updated_at")


@pytest.fixture(autouse=True)
def fixed_route(monkeypatch):
    """Pin the route so the projection math is deterministic and offline."""
    monkeypatch.setattr(
        ts, "order_route", lambda order, restaurant_point=None: (ROUTE, ROUTE_KM)
    )


@pytest.fixture(autouse=True)
def fixed_eta(monkeypatch):
    """Keep the ML model out of these tests; ETA is covered in test_ml_eta_honesty."""
    monkeypatch.setattr(
        ts, "eta_for_order", lambda order, progress: (12.5, "formula")
    )


# ---- _to_epoch_utc ----------------------------------------------------


def test_naive_datetime_is_read_as_utc():
    """The app writes datetime.utcnow() into a timezone-less column."""
    naive = datetime(2026, 10, 1, 12, 0, 0)
    aware = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert ts._to_epoch_utc(naive) == ts._to_epoch_utc(aware)


def test_aware_datetime_offset_is_respected():
    """A non-UTC aware value must convert by instant, not by wall clock."""
    ist_noon = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    same_instant_utc = datetime(2026, 10, 1, 6, 30, 0, tzinfo=timezone.utc)
    assert ts._to_epoch_utc(ist_noon) == ts._to_epoch_utc(same_instant_utc)
    # and it is genuinely five and a half hours behind naive-UTC noon
    assert ts._to_epoch_utc(ist_noon) < ts._to_epoch_utc(
        datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    )


# ---- live_driver_position --------------------------------------------


def _order_with_fix(**kw) -> FakeOrder:
    kw.setdefault("driver_lat", 18.51)
    kw.setdefault("driver_lng", 73.06)
    return FakeOrder(**kw)


def test_no_fix_returns_none():
    assert ts.live_driver_position(FakeOrder()) is None


def test_fresh_fix_is_trusted():
    order = _order_with_fix(driver_updated_at=datetime.utcnow())
    assert ts.live_driver_position(order) == (18.51, 73.06)


def test_fix_inside_the_ttl_is_trusted():
    order = _order_with_fix(
        driver_updated_at=datetime.utcnow()
        - timedelta(seconds=ts.LIVE_POSITION_TTL_SECONDS - 5)
    )
    assert ts.live_driver_position(order) is not None


def test_fix_past_the_ttl_is_rejected():
    """A driver who loses signal degrades to the simulator, not a frozen marker."""
    order = _order_with_fix(
        driver_updated_at=datetime.utcnow()
        - timedelta(seconds=ts.LIVE_POSITION_TTL_SECONDS + 5)
    )
    assert ts.live_driver_position(order) is None


def test_a_fix_from_the_future_is_rejected():
    """A wrong phone clock must not pin the marker forever.

    The staleness rule is `age > TTL`, and a future timestamp makes `age`
    negative, so without a lower bound such a fix is trusted *forever*: the
    customer watches a marker parked at one spot while the real rider moves on
    and the order never appears to progress. Small skew is tolerated; a
    timestamp hours ahead is not.
    """
    order = _order_with_fix(
        driver_updated_at=datetime.utcnow() + timedelta(hours=1)
    )
    assert ts.live_driver_position(order) is None


def test_tiny_clock_skew_is_tolerated():
    """A fix a few seconds ahead is normal NTP drift, not a broken clock."""
    order = _order_with_fix(
        driver_updated_at=datetime.utcnow() + timedelta(seconds=ts.MAX_FUTURE_SKEW_SECONDS / 2)
    )
    assert ts.live_driver_position(order) is not None


def test_missing_timestamp_is_not_treated_as_fresh():
    """Coordinates without a timestamp cannot be aged, so they are unusable."""
    order = _order_with_fix(driver_updated_at=None)
    assert ts.live_driver_position(order) is None


# ---- progress_at_position --------------------------------------------


def test_progress_is_zero_at_the_route_start():
    assert ts.progress_at_position(FakeOrder(), 18.5, 73.000) == pytest.approx(0.0, abs=1e-6)


def test_progress_is_one_at_the_route_end():
    assert ts.progress_at_position(FakeOrder(), 18.5, 73.100) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize(
    "lng,expected",
    [
        (73.000, 0.00),
        (73.025, 0.25),
        (73.050, 0.50),
        (73.075, 0.75),
        (73.100, 1.00),
    ],
)
def test_progress_matches_position_along_a_uniform_route(lng, expected):
    assert ts.progress_at_position(FakeOrder(), 18.5, lng) == pytest.approx(
        expected, abs=1e-6
    )


def test_progress_interpolates_between_route_vertices():
    """The point of segment projection: the ETA must not jump vertex to vertex.

    Snapping to the nearest vertex would make progress move in 25% steps here.
    Interpolating keeps it continuous, so successive GPS fixes produce a
    smoothly advancing marker.
    """
    assert ts.progress_at_position(FakeOrder(), 18.5, 73.0125) == pytest.approx(
        0.125, abs=1e-6
    )
    assert ts.progress_at_position(FakeOrder(), 18.5, 73.0375) == pytest.approx(
        0.375, abs=1e-6
    )
    assert ts.progress_at_position(FakeOrder(), 18.5, 73.0875) == pytest.approx(
        0.875, abs=1e-6
    )


def test_progress_is_monotonic_along_the_route():
    """GPS noise must never make the marker move backwards."""
    values = [
        ts.progress_at_position(FakeOrder(), 18.5, 73.0 + 0.005 * i) for i in range(21)
    ]
    assert all(b >= a - 1e-9 for a, b in zip(values, values[1:])), values
    assert values[0] == pytest.approx(0.0, abs=1e-6)
    assert values[-1] == pytest.approx(1.0, abs=1e-6)


def test_progress_ignores_distance_off_the_route():
    """A rider on the far side of the road is still on the same segment.

    Only the along-route component should matter, otherwise ordinary GPS drift
    perpendicular to the road would distort the ETA. The tolerance covers
    haversine curvature between the route vertex and the off-route probe: the
    projection is onto a straight segment between two great-circle points, so
    a perpendicular offset is not exactly orthogonal to it.
    """
    on_route = ts.progress_at_position(FakeOrder(), 18.5, 73.050)
    ahead = ts.progress_at_position(FakeOrder(), 18.51, 73.050)
    behind = ts.progress_at_position(FakeOrder(), 18.49, 73.050)
    assert ahead == pytest.approx(on_route, abs=1e-4)
    assert behind == pytest.approx(on_route, abs=1e-4)


def test_progress_is_clamped_to_the_unit_interval():
    for lat, lng in [(18.5, 72.0), (18.5, 74.0), (10.0, 73.05), (25.0, 73.05)]:
        value = ts.progress_at_position(FakeOrder(), lat, lng)
        assert 0.0 <= value <= 1.0, (lat, lng, value)


def test_progress_is_zero_when_the_route_has_no_length(monkeypatch):
    """A degenerate route (rider still at pickup) yields 0, not a division error."""
    monkeypatch.setattr(
        ts, "order_route", lambda order, restaurant_point=None: (((18.5, 73.0),), 0.0)
    )
    assert ts.progress_at_position(FakeOrder(), 18.5, 73.0) == 0.0


def test_progress_is_zero_for_an_empty_route(monkeypatch):
    monkeypatch.setattr(ts, "order_route", lambda order, restaurant_point=None: ((), 0.0))
    assert ts.progress_at_position(FakeOrder(), 18.5, 73.0) == 0.0


def test_route_with_a_duplicate_point_does_not_divide_by_zero(monkeypatch):
    """Two identical vertices have zero length; that segment must be skipped."""
    dup = ((18.5, 73.0), (18.5, 73.0), (18.5, 73.1))
    monkeypatch.setattr(ts, "order_route", lambda order, restaurant_point=None: (dup, 11.1))
    value = ts.progress_at_position(FakeOrder(), 18.5, 73.05)
    assert not math.isnan(value)
    assert 0.0 <= value <= 1.0


# ---- rider_progress ---------------------------------------------------


def test_rider_waits_at_the_restaurant_before_pickup():
    order = FakeOrder()
    progress, pos = ts.rider_progress(order, None)
    assert progress == 0.0
    assert pos == ts.restaurant_start(order)


def test_rider_progress_is_near_zero_just_after_pickup():
    class Delivery_:
        pickup_time = datetime.utcnow()

    progress, pos = ts.rider_progress(FakeOrder(), Delivery_())
    assert 0.0 <= progress < 0.1
    assert len(pos) == 2


def test_rider_progress_reaches_one_after_the_trip_time(monkeypatch):
    monkeypatch.setattr(
        ts.tracking, "estimate_trip_seconds", lambda route, speed: 1.0
    )

    class Delivery_:
        pickup_time = datetime.utcnow() - timedelta(seconds=5)

    progress, _pos = ts.rider_progress(FakeOrder(), Delivery_())
    assert progress == 1.0


def test_rider_progress_never_goes_negative():
    class Delivery_:
        pickup_time = datetime.utcnow() + timedelta(seconds=30)

    progress, _pos = ts.rider_progress(FakeOrder(), Delivery_())
    assert progress == 0.0


# ---- build_tracking_state --------------------------------------------


def test_state_reports_a_simulated_rider_without_a_fix():
    state = ts.build_tracking_state(FakeOrder(), None)
    assert state["position_source"] == "simulated"
    assert state["progress"] == 0.0
    assert len(state["route"]) == len(ROUTE)
    assert state["route_distance_km"] == pytest.approx(ROUTE_KM, abs=0.01)


def test_state_prefers_a_fresh_live_fix():
    order = _order_with_fix(driver_updated_at=datetime.utcnow())
    state = ts.build_tracking_state(order, None)
    assert state["position_source"] == "live"
    assert state["rider_lat"] == pytest.approx(18.51)
    assert state["rider_lng"] == pytest.approx(73.06)
    # progress comes from the GPS fix, not the simulated clock
    assert state["progress"] == pytest.approx(
        ts.progress_at_position(order, 18.51, 73.06), abs=1e-4
    )


def test_state_falls_back_to_the_simulator_when_the_fix_goes_stale():
    order = _order_with_fix(
        driver_updated_at=datetime.utcnow() - timedelta(hours=1)
    )
    state = ts.build_tracking_state(order, None)
    assert state["position_source"] == "simulated"


def test_state_route_is_json_safe_pairs():
    """The payload is serialised straight onto a WebSocket."""
    state = ts.build_tracking_state(FakeOrder(), None)
    for point in state["route"]:
        assert isinstance(point, list) and len(point) == 2
        assert all(isinstance(v, float) for v in point)
    assert isinstance(state["rider_lat"], float)
    assert isinstance(state["progress"], float)
    assert isinstance(state["eta_min"], (int, float, type(None)))


# ---- coordinate helpers ----------------------------------------------


def test_delivery_end_uses_the_stored_point():
    order = FakeOrder(delivery_lat=19.0, delivery_lng=74.0)
    assert ts.delivery_end(order) == (19.0, 74.0)


def test_delivery_end_falls_back_to_the_demo_home():
    order = FakeOrder(delivery_lat=None, delivery_lng=None)
    assert ts.delivery_end(order) == tracking.DEFAULT_CUSTOMER_HOME


def test_restaurant_start_prefers_the_restaurant_row():
    class Rest:
        lat = 18.33
        lng = 73.9

    order = FakeOrder(restaurant=Rest())
    assert ts.restaurant_start(order) == (18.33, 73.9)


def test_restaurant_start_falls_back_when_the_row_has_no_coordinates():
    class Rest:
        lat = None
        lng = None

    order = FakeOrder(restaurant=Rest(), restaurant_id=1)
    expected = tracking.restaurant_coordinates(1)
    assert ts.restaurant_start(order) == expected


def test_resolve_restaurant_point_uses_the_selected_pair():
    """A pair the caller already selected is used as-is."""
    assert ts.resolve_restaurant_point(999, (18.33, 73.9)) == (18.33, 73.9)


def test_resolve_restaurant_point_falls_back_to_the_legacy_dict():
    """With no pair, the pure COORDINATES dict is next."""
    assert ts.resolve_restaurant_point(1) == tracking.restaurant_coordinates(1)


def test_resolve_restaurant_point_ends_at_the_demo_home():
    """An id nothing knows must land on the demo home, not raise.

    Raising here is not harmless: callers that catch ValueError substitute a
    flat 1 km, so the demo home is what keeps a coordinate-less restaurant's
    distance coming from a real position.
    """
    assert ts.resolve_restaurant_point(999999) == tracking.DEFAULT_CUSTOMER_HOME


def test_restaurant_start_ends_at_the_demo_home_when_nothing_knows_the_id():
    """The full descent: a NULL row, then a dict miss, then the demo home."""

    class Rest:
        lat = None
        lng = None

    order = FakeOrder(restaurant=Rest(), restaurant_id=999999)
    assert ts.restaurant_start(order) == tracking.DEFAULT_CUSTOMER_HOME
