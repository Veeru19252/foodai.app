"""Delivery simulation loop tests.

The simulator is a background task that runs for the life of the process, so
its failure modes are quiet: nothing surfaces an error to a user, it just
stops moving. These tests pin the properties that keep one bad delivery from
silently freezing every other rider.
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime

import pytest
from sqlalchemy import text

from backend import simulation
from backend.db import SessionLocal
from backend.models import Delivery, Order, Restaurant, TripLog, User


@pytest.fixture
def sim_db():
    """A session for the simulation tests, cleaned up afterwards.

    The `client` fixture's database is session-scoped and shared by the whole
    suite, and several e2e tests assert against hardcoded ids (e.g. order 1).
    Rows created here would shift those ids and break unrelated tests, so
    everything these tests insert is removed on the way out.
    """
    created: list = []
    db = SessionLocal()
    try:
        yield db, created
    finally:
        # Children first: trip_points -> deliveries -> orders -> restaurants
        # -> users.
        for delivery_id in [i for (kind, i) in created if kind == "delivery"]:
            db.query(TripLog).filter(TripLog.delivery_id == delivery_id).delete()
            db.query(Delivery).filter(Delivery.id == delivery_id).delete()
        for order_id in [i for (kind, i) in created if kind == "order"]:
            db.query(Order).filter(Order.id == order_id).delete()
        for rest_id in [i for (kind, i) in created if kind == "restaurant"]:
            db.query(Restaurant).filter(Restaurant.id == rest_id).delete()
        for user_id in [i for (kind, i) in created if kind == "user"]:
            db.query(User).filter(User.id == user_id).delete()
        db.commit()
        db.close()


def _make_active_delivery(db, suffix: str, created: list | None = None) -> Delivery:
    """A user + restaurant + order that the tick will treat as in-transit.

    The two endpoints must be distinct real coordinates: with an identical
    start and end the trip estimate is zero, the tick computes progress >= 1.0,
    and the order is delivered instantly instead of being advanced.
    """
    user = User(
        email=f"sim-{suffix}@foodai.com",
        name=f"Sim {suffix}",
        password_hash="x",
        role="customer",
    )
    db.add(user)
    db.flush()
    restaurant = Restaurant(
        user_id=user.id,
        name=f"Sim Diner {suffix}",
        address="2 Test Road",
        cuisine="test",
        city="Pune",
        lat=18.5204,
        lng=73.8567,
    )
    db.add(restaurant)
    db.flush()

    order = Order(
        customer_id=user.id,
        restaurant_id=restaurant.id,
        status="OUT_FOR_DELIVERY",
        total=100.0,
        delivery_address="1 Test Lane",
        delivery_lat=18.4089,
        delivery_lng=73.8757,
    )
    db.add(order)
    db.flush()

    delivery = Delivery(order_id=order.id, driver_id=user.id, pickup_time=datetime.utcnow())
    db.add(delivery)
    db.commit()
    if created is not None:
        created.extend(
            [
                ("delivery", delivery.id),
                ("order", order.id),
                ("restaurant", restaurant.id),
                ("user", user.id),
            ]
        )
    return delivery


def _run_tick() -> None:
    """Run one simulation tick on a real loop and drain the publish tasks.

    advance_all_deliveries schedules manager.publish on the loop, so the loop
    must stay open long enough for those to run before it is closed.
    """
    loop = asyncio.new_event_loop()
    try:
        simulation.advance_all_deliveries(loop)
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    finally:
        loop.close()


def _trip_point_count(db, delivery_id: int) -> int:
    return db.query(TripLog).filter(TripLog.delivery_id == delivery_id).count()


def _deactivate(db, delivery_id: int) -> None:
    """Take a delivery out of the tick's active set.

    The test database is session-scoped and shared with every other test, so a
    delivery left picked-up-and-undelivered here would be advanced by later
    ticks and keep appending trip points.
    """
    db.query(Delivery).filter(Delivery.id == delivery_id).update(
        {Delivery.delivered_time: datetime.utcnow()}
    )
    db.commit()


def test_tick_logs_a_trip_point_for_every_active_delivery(sim_db):
    db, created = sim_db
    delivery_id = _make_active_delivery(db, "tick-basic", created).id

    _run_tick()

    # Scope to the delivery this test created: the shared database may hold
    # active deliveries belonging to other tests. The count is "at least one"
    # because the app's own background simulator also ticks while the suite is
    # running, so the exact number is not deterministic. What matters is that
    # the tick advanced this delivery at all.
    assert _trip_point_count(db, delivery_id) >= 1


def test_one_failing_delivery_does_not_starve_the_others(sim_db, monkeypatch):
    """A single bad delivery must not freeze every other rider in the tick.

    Postgres aborts the whole transaction when a statement fails, so once one
    delivery raises, every later query on that session fails too. Without
    per-delivery isolation, one poisoned row silently stops the simulation for
    *all* riders -- and because the loop is a background task, nothing reports
    it. The rider just never arrives.
    """
    db, created = sim_db
    # The bad one is created first so it is advanced first, which is the
    # ordering that starves the rest on a shared session.
    bad_id = _make_active_delivery(db, "iso-bad", created).id
    good_ids = {
        _make_active_delivery(db, "iso-a", created).id,
        _make_active_delivery(db, "iso-b", created).id,
    }

    real_advance = simulation._advance_delivery

    def flaky(db_, delivery):
        if delivery.id == bad_id:
            # A realistic mid-tick failure: the DB rejects this statement and
            # Postgres marks the transaction aborted for the rest of the session.
            db_.execute(text("SELECT * FROM definitely_not_a_table"))
        return real_advance(db_, delivery)

    monkeypatch.setattr(simulation, "_advance_delivery", flaky)

    _run_tick()

    for delivery_id in sorted(good_ids):
        assert _trip_point_count(db, delivery_id) >= 1, (
            f"delivery {delivery_id} was starved by an unrelated failure; "
            "every rider in the tick must still advance"
        )


def test_tick_survives_a_total_failure_and_keeps_running(client, monkeypatch):
    """Even when every delivery fails, the tick returns and the loop lives."""

    def always_boom(db, delivery):
        raise RuntimeError("simulated total failure")

    monkeypatch.setattr(simulation, "_advance_delivery", always_boom)

    # Must not raise: the tick is called from a background task.
    _run_tick()


def test_simulation_loop_uses_the_logger_not_print_exc():
    """traceback.print_exc bypasses logging config and disappears in production."""
    source = pathlib.Path(simulation.__file__).read_text()
    assert "traceback.print_exc" not in source, (
        "simulation_loop should use logger.exception so failures reach the "
        "configured handlers instead of raw stderr"
    )
