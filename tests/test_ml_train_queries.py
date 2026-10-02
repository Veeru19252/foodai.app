"""Demand-forecast retrain query-shape tests.

``retrain_forecast`` rebuilds the model from the whole order table, so
``live_orders_frame`` is a full scan that runs on every admin retrain. Any
order without a delivery point falls back to its restaurant's coordinates for
the zone, and reading that through the lazy ``order.restaurant`` relationship
made the query count grow with the table.

``ml_train`` opens its own session, so the tests bind one to a dedicated
connection. Nothing else uses that session -- the background simulator uses its
own -- so the statement count is attributable without touching the engine.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

import eta_service
import tracking

from backend import ml_train
from backend.db import SessionLocal, engine
from backend.models import Order, Restaurant, User


def _purge(db) -> None:
    """Remove leftovers from a previous interrupted run."""
    restaurant_ids = db.query(Restaurant.id).filter(Restaurant.name.like("NZone%"))
    db.query(Order).filter(Order.restaurant_id.in_(restaurant_ids)).delete(
        synchronize_session=False
    )
    db.query(Restaurant).filter(Restaurant.id.in_(restaurant_ids)).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.email.like("nzone_%")).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def orders_needing_the_restaurant_fallback():
    """Orders split between those with and without a delivery point.

    The ones without are the interesting case: each used to cost a restaurant
    SELECT. The restaurants are distinct so the identity map cannot absorb the
    loads and make the count look flat.
    """
    db = SessionLocal()
    _purge(db)
    customer = User(
        email="nzone_cust@example.com", name="NZoneCust", password_hash="x", role="customer"
    )
    db.add(customer)
    db.flush()
    customer_id = customer.id
    # Restaurant coordinates in the demand-forecast zones (A-E) so
    # nearest_zone resolves them instead of rejecting them.
    restaurant_points = [
        (18.5204, 73.8567),  # Pune -> B
        (19.0760, 72.8777),  # Mumbai -> B
        (12.9716, 77.5946),  # Bengaluru -> C
    ]
    # Delivery points deliberately in *different* zones from the restaurants
    # above, so a swap of which point wins is visible in the frame rather than
    # both answers happening to be the same letter.
    delivery_points = [
        (28.6139, 77.2090),  # Delhi -> A
        (22.5726, 88.3639),  # Kolkata -> D
        (13.0827, 80.2707),  # Chennai -> E
    ]
    restaurant_zones = {"B", "C"}
    delivery_zones = {"A", "D", "E"}
    with_point = 0
    without_point = 0
    my_orders: list = []
    restaurant_coord_per_order: list = []
    for i in range(6):
        owner = User(
            email=f"nzone_owner{i}@example.com",
            name=f"NZoneOwner{i}",
            password_hash="x",
            role="restaurant",
        )
        db.add(owner)
        db.flush()
        rlat, rlng = restaurant_points[i % len(restaurant_points)]
        restaurant = Restaurant(
            user_id=owner.id,
            name=f"NZone Diner {i}",
            address="a",
            cuisine="test",
            lat=rlat,
            lng=rlng,
        )
        db.add(restaurant)
        db.flush()
        # Half the orders carry no delivery point, forcing the fallback.
        order = Order(
            customer_id=customer_id,
            restaurant_id=restaurant.id,
            status="PLACED",
            total=10.0,
            created_at=datetime(2026, 10, 1, 9 + i, 0, 0),
        )
        if i % 2 == 0:
            without_point += 1
        else:
            order.delivery_lat, order.delivery_lng = delivery_points[(i - 1) // 2]
            with_point += 1
        db.add(order)
        my_orders.append(order)
        restaurant_coord_per_order.append((rlat, rlng))

    # One restaurant with no coordinates at all, to cover the third fallback:
    # restaurant_start gets no preloaded point, misses the legacy COORDINATES
    # dict, and lands on the demo home. Its order must still be zoned rather
    # than quietly dropped from the training set.
    lonelier = User(
        email="nzone_owner_nocoords@example.com",
        name="NZoneOwnerNoCoords",
        password_hash="x",
        role="restaurant",
    )
    db.add(lonelier)
    db.flush()
    blank = Restaurant(
        user_id=lonelier.id,
        name="NZone Diner No Coords",
        address="a",
        cuisine="test",
        lat=None,
        lng=None,
    )
    db.add(blank)
    db.flush()
    no_coords_order = Order(
        customer_id=customer_id,
        restaurant_id=blank.id,
        status="PLACED",
        total=10.0,
        created_at=datetime(2026, 10, 1, 20, 0, 0),
    )
    db.add(no_coords_order)
    my_orders.append(no_coords_order)
    restaurant_coord_per_order.append(None)
    without_point += 1

    db.flush()
    total = with_point + without_point
    # live_orders_frame scans the whole table, which also holds the seeded demo
    # data, so assertions are scoped to the orders this fixture created.
    mine = {o.id for o in my_orders}
    fallback_ids = {o.id for o in my_orders if o.delivery_lat is None}
    # Zone each order must land in. Orders with a delivery point use it, the
    # rest use their restaurant's coordinates, and the restaurant with none
    # lands on the demo home.
    expected = {}
    for order, rc in zip(my_orders, restaurant_coord_per_order):
        if order.delivery_lat is not None:
            point = (order.delivery_lat, order.delivery_lng)
        elif rc is not None:
            point = rc
        else:
            point = tracking.DEFAULT_CUSTOMER_HOME
        expected[order.id] = eta_service.nearest_zone(*point)
    assert {expected[i] for i in fallback_ids} & restaurant_zones, (
        "fixture must exercise at least one restaurant-coordinate fallback zone"
    )
    assert {expected[i] for i in mine - fallback_ids} <= delivery_zones, (
        "delivery-point orders must resolve to their own zones"
    )
    db.commit()
    # Not wrapped in a bare except on purpose: these rows carry a non-Argon2id
    # password_hash, and a silently failed cleanup leaves them behind for
    # test_seeded_passwords_are_argon2id to trip over later in the run.
    yield db, total, without_point, mine, fallback_ids, expected
    _purge(db)
    db.close()


def _frame_with_statement_count(monkeypatch):
    """Run live_orders_frame on a dedicated connection; return (sql, frame)."""
    connection = engine.connect()
    session = sessionmaker(bind=connection, autocommit=False, autoflush=False)
    monkeypatch.setattr(ml_train, "SessionLocal", session)
    statements: list = []

    def _on_execute(_conn, _cursor, statement, *_args, **_kwargs):
        statements.append(" ".join(statement.split()))

    event.listen(connection, "before_cursor_execute", _on_execute)
    try:
        frame = ml_train.live_orders_frame()
    finally:
        event.remove(connection, "before_cursor_execute", _on_execute)
        connection.close()
    return statements, frame


def test_retrain_scan_does_not_query_the_restaurant_per_order(
    orders_needing_the_restaurant_fallback, monkeypatch
):
    """One restaurants query plus one orders query, whatever the table size.

    Each order without a delivery point used to lazy-load order.restaurant, so
    a scan grew with the number of such orders.
    """
    _db, _total, _without, _mine, _fallback, _expected = (
        orders_needing_the_restaurant_fallback
    )
    statements, _frame = _frame_with_statement_count(monkeypatch)

    assert len(statements) == 2, (
        f"live_orders_frame issued {len(statements)} queries; expected 2 "
        "(one for restaurant coordinates, one for the order columns): "
        + " | ".join(s[:100] for s in statements[:4])
    )
    assert any("FROM restaurants" in s for s in statements)
    assert any("FROM orders" in s for s in statements)


def test_retrain_scan_still_zones_every_order(
    orders_needing_the_restaurant_fallback, monkeypatch
):
    """The batched lookup must not drop rows or change which zone is assigned.

    Orders with a delivery point use it; the rest fall back to the restaurant's
    coordinates. Both must survive, because a dropped row is a silently smaller
    training set.
    """
    _db, _total, _without, mine, fallback_ids, expected = (
        orders_needing_the_restaurant_fallback
    )
    _statements, frame = _frame_with_statement_count(monkeypatch)

    assert fallback_ids, "fixture must include orders needing the fallback"
    frame_ids = set(frame["order_id"])
    missing = mine - frame_ids
    assert not missing, (
        f"frame dropped orders {sorted(missing)}; a missing row is a silently "
        "smaller training set"
    )
    assert not (fallback_ids - frame_ids), (
        "orders without a delivery point lost their restaurant-zone fallback"
    )
    actual = dict(zip(frame["order_id"], frame["customer_zone"]))
    wrong = {oid: (expected[oid], actual[oid]) for oid in mine if actual.get(oid) != expected[oid]}
    assert not wrong, (
        f"wrong zone as (expected, actual) for orders {wrong}; the delivery "
        "point must win over the restaurant's coordinates"
    )
