"""Delivery simulation loop tests.

The simulator is a background task that runs for the life of the process, so
its failure modes are quiet: nothing surfaces an error to a user, it just
stops moving. These tests pin the properties that keep one bad delivery from
silently freezing every other rider.
"""

from __future__ import annotations

import asyncio
import pathlib
import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from backend import simulation, tracking_state
from backend.db import SessionLocal, engine
from backend.models import Delivery, Notification, Order, Restaurant, TripLog, User


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
        # Children first: notifications -> trip_points -> deliveries -> orders
        # -> restaurants -> users. A delivered tick writes a notification that
        # references the customer, so it has to go before the user row.
        user_ids = [i for (kind, i) in created if kind == "user"]
        order_ids = [i for (kind, i) in created if kind == "order"]
        if user_ids or order_ids:
            db.query(Notification).filter(
                (Notification.user_id.in_(user_ids))
                | (Notification.order_id.in_(order_ids))
            ).delete(synchronize_session=False)
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

    def flaky(db_, delivery, restaurant_point=None):
        if delivery.id == bad_id:
            # A realistic mid-tick failure: the DB rejects this statement and
            # Postgres marks the transaction aborted for the rest of the session.
            db_.execute(text("SELECT * FROM definitely_not_a_table"))
        return real_advance(db_, delivery, restaurant_point)

    monkeypatch.setattr(simulation, "_advance_delivery", flaky)

    _run_tick()

    for delivery_id in sorted(good_ids):
        assert _trip_point_count(db, delivery_id) >= 1, (
            f"delivery {delivery_id} was starved by an unrelated failure; "
            "every rider in the tick must still advance"
        )


def test_tick_survives_a_total_failure_and_keeps_running(client, monkeypatch):
    """Even when every delivery fails, the tick returns and the loop lives."""

    def always_boom(db, delivery, restaurant_point=None):
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


# ---------------------------------------------------------------------------
# Query shape
#
# The tick runs every 2 seconds for the life of the process, so its per-rider
# cost is the most repeated query load in the app. It used to pay a lazy
# restaurant load and a post-commit refresh for every rider; both are now gone.
# ---------------------------------------------------------------------------


def _count_on_connection(connection, fn) -> int:
    """Count statements issued through one Connection while fn runs.

    The app's own background simulator shares the engine, so counting at the
    engine would attribute its statements to the code under test. Binding the
    session to a dedicated connection and listening there keeps the count
    deterministic.
    """
    counter = {"n": 0}

    def _on_execute(*_args, **_kwargs):
        counter["n"] += 1

    event.listen(connection, "before_cursor_execute", _on_execute)
    try:
        fn()
    finally:
        event.remove(connection, "before_cursor_execute", _on_execute)
    return counter["n"]


def _session_on_dedicated_connection():
    """A session bound to its own connection, so commits keep the same one."""
    connection = engine.connect()
    return Session(bind=connection), connection


def test_advance_delivery_does_not_lazy_load_the_restaurant(sim_db):
    """One rider costs a fresh order read and a trip-log insert -- nothing else.

    The restaurant coordinates are passed in by the tick, so the lazy
    ``order.restaurant`` load must not happen. Reading the payload after commit
    must not re-select the order either.
    """
    db, created = sim_db
    delivery = _make_active_delivery(db, "q-point", created)
    delivery_id = delivery.id
    point = (18.5204, 73.8567)

    session, connection = _session_on_dedicated_connection()
    try:
        loaded = session.query(Delivery).filter(Delivery.id == delivery_id).one()
        queries = _count_on_connection(
            connection, lambda: simulation._advance_delivery(session, loaded, point)
        )
    finally:
        session.close()
        connection.close()

    assert queries == 2, (
        f"advancing one rider issued {queries} statements; expected 2 "
        "(one order read, one trip-log insert). A third means the restaurant "
        "was lazy-loaded or the order was re-read after commit."
    )


def test_advance_delivery_without_a_point_still_works(sim_db):
    """The lazy fallback stays available for any other caller."""
    db, created = sim_db
    delivery = _make_active_delivery(db, "q-nopoint", created)
    delivery_id = delivery.id

    session, connection = _session_on_dedicated_connection()
    try:
        loaded = session.query(Delivery).filter(Delivery.id == delivery_id).one()
        event_ = simulation._advance_delivery(session, loaded, None)
    finally:
        session.close()
        connection.close()

    assert event_ is not None
    assert event_["type"] == "position"


def test_restaurant_points_preloads_the_whole_fleet_in_one_query(sim_db):
    """The preload must be one query and must cover every active restaurant."""
    db, created = sim_db
    deliveries = [_make_active_delivery(db, f"q-pre-{i}", created) for i in range(5)]
    expected = {d.order_id: (18.5204, 73.8567) for d in deliveries}

    session, connection = _session_on_dedicated_connection()
    try:
        points = {}
        queries = _count_on_connection(
            connection, lambda: points.update(simulation._restaurant_points(session))
        )
    finally:
        session.close()
        connection.close()

    assert queries == 1, f"preloading {len(deliveries)} restaurants issued {queries} queries"
    for order_id, point in expected.items():
        assert points.get(order_id) == point


def test_preloaded_point_matches_the_lazy_route(sim_db):
    """Passing the point must not change the route or the rider's start."""
    db, created = sim_db
    delivery = _make_active_delivery(db, "q-equiv", created)
    order = db.query(Order).filter(Order.id == delivery.order_id).one()
    point = (18.5204, 73.8567)

    assert tracking_state.restaurant_start(order, point) == tracking_state.restaurant_start(order)
    assert tracking_state.order_route(order, point) == tracking_state.order_route(order)


def test_restaurant_without_coordinates_is_omitted_and_falls_back(sim_db):
    """A restaurant with no lat/lng must be left out of the preload.

    ``restaurant_start`` then falls back to the legacy coordinate table exactly
    as it did before the preload existed.
    """
    db, created = sim_db
    delivery = _make_active_delivery(db, "q-nocoords", created)
    restaurant_id = db.query(Order.restaurant_id).filter(Order.id == delivery.order_id).scalar()
    db.query(Restaurant).filter(Restaurant.id == restaurant_id).update(
        {Restaurant.lat: None, Restaurant.lng: None}
    )
    db.commit()

    points = simulation._restaurant_points(db)
    assert delivery.order_id not in points

    order = db.query(Order).filter(Order.id == delivery.order_id).one()
    # Must not raise, and must return a concrete point.
    start = tracking_state.restaurant_start(order, points.get(delivery.order_id))
    assert isinstance(start, tuple) and len(start) == 2


def test_tick_reads_the_fleet_once(sim_db, monkeypatch):
    """Committing per rider must not expire the fleet list and re-read it.

    The tick loads every active delivery once, then commits once per rider. With
    the default expire-on-commit, that first commit invalidates the whole list,
    so the next iteration's ``delivery.id`` re-selects the row -- one wasted
    SELECT per rider per tick. The fleet table must be read exactly once.
    """
    db, created = sim_db
    for i in range(4):
        _make_active_delivery(db, f"q-fleet-{i}", created)
    db.expunge_all()

    connection = engine.connect()
    real_sessionmaker = simulation.SessionLocal
    main_thread = threading.get_ident()

    def scoped_sessionmaker(*args, **kwargs):
        # Only the tick this test drives (main thread) is bound to the counted
        # connection. The app's background simulator runs in an executor thread
        # and keeps using the engine, so its statements are not counted.
        if threading.get_ident() == main_thread:
            return real_sessionmaker(bind=connection)
        return real_sessionmaker(*args, **kwargs)

    monkeypatch.setattr(simulation, "SessionLocal", scoped_sessionmaker)

    statements: list = []

    def _on_execute(_conn, _cursor, statement, *_args, **_kwargs):
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", _on_execute)
    loop = asyncio.new_event_loop()
    try:
        simulation.advance_all_deliveries(loop)
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    finally:
        event.remove(connection, "before_cursor_execute", _on_execute)
        loop.close()
        connection.close()

    # "FROM deliveries" matches the fleet list query only; the restaurant
    # preload joins deliveries, so it reads "JOIN deliveries".
    fleet_reads = [s for s in statements if "FROM deliveries" in s]
    assert len(fleet_reads) == 1, (
        f"the tick read the deliveries table {len(fleet_reads)} times; the fleet "
        "list must be loaded once and not re-selected after each commit"
    )


def test_tick_passes_the_preloaded_point_to_every_rider(sim_db, monkeypatch):
    """The call site must actually forward the preloaded coordinates.

    Without this, the unit-level query test would still pass while the tick
    silently went back to a lazy load per rider.
    """
    db, created = sim_db
    deliveries = [_make_active_delivery(db, f"q-fwd-{i}", created) for i in range(4)]
    expected = {d.order_id: (18.5204, 73.8567) for d in deliveries}

    seen = {}
    real_advance = simulation._advance_delivery

    def recording(db_, delivery, restaurant_point=None):
        seen[delivery.order_id] = restaurant_point
        return real_advance(db_, delivery, restaurant_point)

    monkeypatch.setattr(simulation, "_advance_delivery", recording)
    _run_tick()

    for order_id, point in expected.items():
        assert seen.get(order_id) == point, (
            f"order {order_id} was advanced with {seen.get(order_id)!r}; the tick "
            "must pass the preloaded restaurant point"
        )


def test_delivered_delivery_still_notifies_the_customer(sim_db, monkeypatch):
    """The delivered branch must survive the payload-before-commit refactor."""
    db, created = sim_db
    # Silence the app's own simulator before the delivery exists: it would
    # otherwise be free to deliver this order first and leave the direct call
    # below with nothing to do.
    monkeypatch.setattr(simulation, "advance_all_deliveries", lambda loop: None)
    delivery = _make_active_delivery(db, "q-delivered", created)
    delivery_id = delivery.id
    order_id = delivery.order_id
    customer_id = db.query(Order.customer_id).filter(Order.id == order_id).scalar()
    # Far enough in the past that progress clamps to 1.0 on the next tick.
    db.query(Delivery).filter(Delivery.id == delivery_id).update(
        {Delivery.pickup_time: datetime.utcnow() - timedelta(days=1)}
    )
    db.commit()

    session, connection = _session_on_dedicated_connection()
    try:
        loaded = session.query(Delivery).filter(Delivery.id == delivery_id).one()
        event_ = simulation._advance_delivery(session, loaded, (18.5204, 73.8567))
    finally:
        session.close()
        connection.close()

    assert event_ is not None
    assert event_["type"] == "delivered"
    assert event_["status"] == "DELIVERED"

    db.expire_all()
    order = db.query(Order).filter(Order.id == order_id).one()
    assert order.status == "DELIVERED"
    assert db.query(Delivery).filter(Delivery.id == delivery_id).one().delivered_time is not None
    assert (
        db.query(Notification)
        .filter(Notification.order_id == order_id, Notification.user_id == customer_id)
        .count()
        == 1
    )
