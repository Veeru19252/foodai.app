"""Auto-dispatch fleet lookup tests.

auto_assign_delivery scores every rider on current load and distance to the
restaurant. It used to ask for each rider's load and last position inside the
scoring loop, so one dispatch cost two queries per rider and loaded every
delivery row for each of them. Both lookups are now batched.

The batched versions have to agree with the per-rider queries they replaced, so
these tests compute the expectation both ways and compare.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from backend.db import SessionLocal
from backend.models import Delivery, Order, Restaurant, TripLog, User
from backend.routers import orders as orders_router

START = datetime(2026, 10, 1, 8, 0, 0)


def _count(db, fn) -> int:
    counter = {"n": 0}

    def _on_execute(*_args, **_kwargs):
        counter["n"] += 1

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", _on_execute)
    try:
        fn()
    finally:
        event.remove(connection, "before_cursor_execute", _on_execute)
    return counter["n"]


def _purge(db) -> None:
    """Remove leftovers from a previous interrupted run."""
    rider_ids = db.query(User.id).filter(User.email.like("nfleet_%"))
    db.query(TripLog).filter(
        TripLog.delivery_id.in_(
            db.query(Delivery.id).filter(Delivery.driver_id.in_(rider_ids))
        )
    ).delete(synchronize_session=False)
    db.query(Delivery).filter(Delivery.driver_id.in_(rider_ids)).delete(
        synchronize_session=False
    )
    order_ids = db.query(Order.id).filter(Order.restaurant_id.in_(
        db.query(Restaurant.id).filter(Restaurant.name == "NFleetDiner")
    ))
    db.query(Order).filter(Order.id.in_(order_ids)).delete(synchronize_session=False)
    db.query(Restaurant).filter(Restaurant.name == "NFleetDiner").delete(
        synchronize_session=False
    )
    db.query(User).filter(User.email.like("nfleet_%")).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def fleet():
    """Riders with a mix of active, queued and delivered deliveries."""
    db = SessionLocal()
    _purge(db)
    n = 12
    customer = User(
        email="nfleet_c@example.com", name="NFleetC", password_hash="x", role="customer"
    )
    db.add(customer)
    db.flush()
    restaurant = Restaurant(
        user_id=customer.id, name="NFleetDiner", address="a", cuisine="test", lat=13.0, lng=80.0
    )
    db.add(restaurant)
    db.flush()
    driver_ids = []
    for i in range(n):
        d = User(
            email=f"nfleet_d{i}@example.com", name=f"NFD{i}", password_hash="x", role="delivery"
        )
        db.add(d)
        db.flush()
        driver_ids.append(d.id)
        for j in range(6):
            order = Order(
                customer_id=customer.id,
                restaurant_id=restaurant.id,
                status="PLACED",
                total=1.0,
            )
            db.add(order)
            db.flush()
            delivery = Delivery(order_id=order.id, driver_id=d.id)
            if j % 3 == 0:
                delivery.pickup_time = START + timedelta(minutes=j)
            if j % 4 == 0:
                delivery.delivered_time = START + timedelta(minutes=j + 1)
            db.add(delivery)
            db.flush()
            db.add(
                TripLog(
                    delivery_id=delivery.id,
                    lat=13.0 + j * 0.001,
                    lng=80.0 + j * 0.001,
                    # Deliberately out of insertion order, so "latest" cannot
                    # be mistaken for "last inserted".
                    timestamp=START + timedelta(minutes=10 - j),
                )
            )
    db.commit()
    # Captured while attached: tests call db.expunge_all() before measuring,
    # which detaches these objects.
    driver_ids = list(driver_ids)
    restaurant_id = restaurant.id
    yield db, n, driver_ids
    # Same order as _purge, and deliberately not wrapped in a bare except:
    # these rows hold a non-Argon2id password_hash, and a silently failed
    # cleanup leaves them behind for test_seeded_passwords_are_argon2id to
    # trip over much later in the run.
    _purge(db)
    db.close()


def test_batched_loads_match_the_per_rider_computation(fleet):
    db, n, driver_ids = fleet
    batched = orders_router._rider_loads(db, driver_ids)
    assert len(batched) == n
    for driver_id in driver_ids:
        rows = db.query(Delivery).filter(Delivery.driver_id == driver_id).all()
        active = sum(
            1
            for d in rows
            if d.pickup_time is not None and d.delivered_time is None
        )
        queued = sum(1 for d in rows if d.pickup_time is None)
        assert batched[driver_id] == {
            "active": active,
            "queued": queued,
            "load": active * 2 + queued,
        }


def test_batched_positions_match_the_per_rider_query(fleet):
    """DISTINCT ON must pick the same latest fix the single-rider query did."""
    db, n, driver_ids = fleet
    fallback = (0.0, 0.0)
    batched = orders_router._rider_last_positions(db, driver_ids, fallback)
    for driver_id in driver_ids:
        assert batched.get(driver_id) == orders_router._rider_last_position(
            db, driver_id, fallback
        )


def test_fleet_lookups_do_not_query_per_rider(fleet):
    """The dispatch score must not scale its queries with the fleet size."""
    db, n, driver_ids = fleet
    db.expunge_all()
    queries = _count(
        db,
        lambda: (
            orders_router._rider_loads(db, driver_ids),
            orders_router._rider_last_positions(db, driver_ids, (13.0, 80.0)),
        ),
    )
    assert queries == 2, (
        f"scoring {n} riders issued {queries} queries; expected 2 "
        "(one grouped count, one DISTINCT ON)"
    )


def test_single_rider_helper_still_works(fleet):
    """_rider_load stays available for any other caller."""
    db, _n, driver_ids = fleet
    batched = orders_router._rider_loads(db, driver_ids)
    for driver_id in driver_ids:
        assert orders_router._rider_load(db, driver_id) == batched[driver_id]


def test_rider_with_no_deliveries_reports_zero_load(fleet):
    """A brand-new rider is absent from the grouped result, so must fall back."""
    db, _n, _driver_ids = fleet
    fresh = User(
        email="nfleet_new@example.com", name="NFNew", password_hash="x", role="delivery"
    )
    db.add(fresh)
    db.commit()
    assert fresh.id not in orders_router._rider_loads(db, [fresh.id])
    assert orders_router._rider_load(db, fresh.id) == {
        "active": 0,
        "queued": 0,
        "load": 0,
    }
    # And a position fallback for a rider who has never logged a trip.
    assert fresh.id not in orders_router._rider_last_positions(db, [fresh.id], (1.0, 2.0))


def test_empty_fleet_ids_are_handled(fleet):
    db, _n, _driver_ids = fleet
    assert orders_router._rider_loads(db, []) == {}
    assert orders_router._rider_last_positions(db, [], (0.0, 0.0)) == {}
