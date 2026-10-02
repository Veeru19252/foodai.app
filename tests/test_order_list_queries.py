"""Order-list query-shape tests for the customer and restaurant dashboards.

Both list endpoints read a related row for every order they return:

* my_orders reads order.restaurant.name via _order_brief;
* restaurant_orders reads customer name and assigned driver.

With those relationships left lazy, each endpoint issues one extra SELECT per
order. These assert query counts so a re-introduced N+1 fails in CI, and assert
the response values so an eager-load bug cannot pass by returning less data.

The fixtures deliberately vary the relationship each endpoint reads through:
my_orders is only an N+1 when the history spans many *restaurants*, and
restaurant_orders only when it spans many *customers and drivers*. SQLAlchemy's
identity map absorbs lazy loads for already-seen rows, so sharing a restaurant
or customer would hide the bug and make the query-count test vacuous.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend.models import Delivery, Order, Restaurant, User
from backend.routers import orders as orders_router
from backend.routers.orders import MAX_EARNINGS_DISTANCE_KM


class CustomerUser:
    def __init__(self, id: int):
        self.id = id
        self.role = "customer"


class AdminUser:
    id = 1
    role = "admin"


def _count_queries(db: Session, fn) -> int:
    """Count the statements this session issues while fn runs.

    Listens on the session's own Connection rather than the engine: the
    background simulation task shares the engine and can fire a statement at
    any moment, which would otherwise be attributed to the endpoint under test
    and make the count flaky.
    """
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


@pytest.fixture
def history_orders():
    """One customer with N orders spread across N distinct restaurants.

    This is what makes my_orders an N+1: _order_brief reads restaurant.name for
    every order, and no two orders share a restaurant.
    """
    db = SessionLocal()
    n = 30
    customer = User(
        email="nplus_hist@example.com", name="NPlusHist", password_hash="x", role="customer"
    )
    db.add(customer)
    db.flush()
    restaurants = []
    for i in range(n):
        r = Restaurant(
            user_id=customer.id, name=f"NHist {i}", address="a", cuisine="test"
        )
        db.add(r)
        restaurants.append(r)
    db.flush()
    for i in range(n):
        db.add(
            Order(
                customer_id=customer.id,
                restaurant_id=restaurants[i].id,
                status="PLACED",
                total=10.0 + i,
            )
        )
    db.commit()
    yield db, n, customer.id
    try:
        db.query(Order).filter(Order.customer_id == customer.id).delete(
            synchronize_session=False
        )
        db.query(Restaurant).filter(Restaurant.name.like("NHist %")).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.email.like("nplus_%")).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


class RestaurantUser:
    def __init__(self, id: int):
        self.id = id
        self.role = "restaurant"


class DriverUser:
    def __init__(self, id: int):
        self.id = id
        self.role = "delivery"


@pytest.fixture
def driver_history():
    """One driver with N delivered orders, each from a distinct restaurant.

    Every order carries real coordinates so the earnings computation takes the
    database path through restaurant lat/lng. Distinct restaurants matter: a
    shared restaurant would let the identity map absorb the lazy load and hide
    the N+1 this test exists to catch.
    """
    db = SessionLocal()
    n = 30
    driver = User(
        email="nplus_drv@example.com", name="NPlusDrv", password_hash="x", role="delivery"
    )
    db.add(driver)
    db.flush()
    customers, restaurants = [], []
    for i in range(n):
        c = User(
            email=f"nplus_dc{i}@example.com", name=f"NDC{i}", password_hash="x", role="customer"
        )
        db.add(c)
        customers.append(c)
    db.flush()
    for i in range(n):
        r = Restaurant(
            user_id=driver.id,
            name=f"NEDiner {i}",
            address="a",
            cuisine="test",
            lat=13.0 + i * 0.001,
            lng=80.0,
        )
        db.add(r)
        restaurants.append(r)
    db.flush()
    orders = []
    for i in range(n):
        o = Order(
            customer_id=customers[i].id,
            restaurant_id=restaurants[i].id,
            status="DELIVERED",
            total=10.0 + i,
            delivery_address="somewhere",
            delivery_city="Chennai",
            delivery_lat=13.05,
            delivery_lng=80.02,
        )
        db.add(o)
        orders.append(o)
    db.flush()
    now = datetime(2026, 10, 1, 12, 0, 0)
    for o in orders:
        db.add(Delivery(order_id=o.id, driver_id=driver.id, delivered_time=now))
    db.commit()
    yield db, n, driver.id
    try:
        order_ids = [o.id for o in orders]
        db.query(Delivery).filter(Delivery.order_id.in_(order_ids)).delete(
            synchronize_session=False
        )
        db.query(Order).filter(Order.id.in_(order_ids)).delete(synchronize_session=False)
        db.query(Restaurant).filter(Restaurant.name.like("NEDiner %")).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.email.like("nplus_%")).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def test_driver_orders_does_not_issue_a_query_per_delivery(driver_history):
    """The active list the driver app polls.

    Same shape as the earnings loop: its own Order query per delivery, with
    the restaurant and customer read lazily on top.
    """
    db, n, driver_id = driver_history
    rows = orders_router.driver_orders(DriverUser(driver_id), db)
    assert len(rows) == n
    queries = _count_queries(
        db, lambda: orders_router.driver_orders(DriverUser(driver_id), db)
    )
    assert queries <= 2, (
        f"driver_orders issued {queries} queries for {n} deliveries; "
        "the order, restaurant and customer must be selected in one query"
    )


def test_driver_orders_still_reports_both_names(driver_history):
    db, n, driver_id = driver_history
    rows = orders_router.driver_orders(DriverUser(driver_id), db)
    assert {r["restaurant_name"] for r in rows} == {f"NEDiner {i}" for i in range(n)}
    assert {r["customer_name"] for r in rows} == {f"NDC{i}" for i in range(n)}


def test_driver_earnings_does_not_issue_a_query_per_delivery(driver_history):
    """A driver's history is the longest-lived list in the app.

    This loop used to run its own Order query per delivery, and read the
    restaurant through a lazy relationship for the distance calculation, so it
    cost several queries per row. Only the ten most recent rows are rendered.
    """
    db, n, driver_id = driver_history
    queries = _count_queries(
        db, lambda: orders_router.driver_earnings(DriverUser(driver_id), db)
    )
    assert queries <= 2, (
        f"driver_earnings issued {queries} queries for {n} deliveries; "
        "the order, restaurant and customer must be selected in one query"
    )


def test_driver_earnings_still_totals_and_names_every_delivery(driver_history):
    """Totals cover the whole history; only the recent list is truncated."""
    db, n, driver_id = driver_history
    body = orders_router.driver_earnings(DriverUser(driver_id), db)
    assert body["total_deliveries"] == n
    assert body["completed_deliveries"] == n
    assert len(body["recent"]) == 10
    assert body["total_earnings"] > 0
    row = body["recent"][0]
    assert row["restaurant_name"].startswith("NEDiner"), row
    assert row["customer_name"].startswith("NDC"), row
    # A real distance, not the 1 km fallback for an unroutable pair.
    assert row["distance_km"] > 1.0, row


@pytest.fixture
def distinct_customers():
    """N orders with N distinct customers, restaurants and drivers.

    This is what makes restaurant_orders an N+1: it reads customer.name and
    assigned_driver per row, and no two orders share either.
    """
    db = SessionLocal()
    n = 30
    owner = User(
        email="nplus_owner@example.com", name="NPlusOwner", password_hash="x", role="restaurant"
    )
    db.add(owner)
    customers, drivers, restaurants = [], [], []
    for i in range(n):
        c = User(
            email=f"nplus_c{i}@example.com", name=f"NC{i}", password_hash="x", role="customer"
        )
        d = User(
            email=f"nplus_d{i}@example.com", name=f"ND{i}", password_hash="x", role="delivery"
        )
        db.add_all([c, d])
        customers.append(c)
        drivers.append(d)
    db.flush()
    for i in range(n):
        r = Restaurant(user_id=owner.id, name=f"NDiner {i}", address="a", cuisine="test")
        db.add(r)
        restaurants.append(r)
    db.flush()
    for i in range(n):
        o = Order(
            customer_id=customers[i].id,
            restaurant_id=restaurants[i].id,
            status="PLACED",
            total=10.0 + i,
        )
        db.add(o)
        db.flush()
        db.add(Delivery(order_id=o.id, driver_id=drivers[i].id))
        # Order.assigned_driver joins on orders.delivery_id, not via Delivery.
        o.delivery_id = drivers[i].id
    db.commit()
    yield db, n
    try:
        customer_ids = [c.id for c in customers]
        db.query(Delivery).filter(
            Delivery.order_id.in_(
                db.query(Order.id).filter(Order.customer_id.in_(customer_ids))
            )
        ).delete(synchronize_session=False)
        db.query(Order).filter(Order.customer_id.in_(customer_ids)).delete(
            synchronize_session=False
        )
        db.query(Restaurant).filter(Restaurant.name.like("NDiner %")).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.email.like("nplus_%")).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def test_my_orders_does_not_issue_a_query_per_order(history_orders):
    db, n, customer_id = history_orders
    queries = _count_queries(
        db, lambda: orders_router.my_orders(CustomerUser(customer_id), db)
    )
    assert queries <= 2, (
        f"my_orders issued {queries} queries for {n} orders; "
        "order.restaurant must be eager-loaded"
    )


def test_my_orders_returns_every_order_with_its_restaurant_name(history_orders):
    """Eager loading must not drop rows or their restaurant names."""
    db, n, customer_id = history_orders
    rows = orders_router.my_orders(CustomerUser(customer_id), db)
    assert len(rows) == n
    assert {r["restaurant_name"] for r in rows} == {f"NHist {i}" for i in range(n)}


def test_restaurant_orders_does_not_issue_a_query_per_order(distinct_customers):
    db, n = distinct_customers
    queries = _count_queries(
        db, lambda: orders_router.restaurant_orders(AdminUser(), db)
    )
    assert queries <= 2, (
        f"restaurant_orders issued {queries} queries for {n} orders; "
        "customer and assigned_driver must be eager-loaded"
    )


def test_restaurant_orders_still_reports_customer_and_driver(distinct_customers):
    """The N+1 fix must not drop the fields the dashboard renders."""
    db, n = distinct_customers
    rows = orders_router.restaurant_orders(AdminUser(), db)
    mine = {r["id"]: r for r in rows if str(r["customer_name"]).startswith("NC")}
    assert len(mine) == n
    for row in mine.values():
        assert row["customer_name"].startswith("NC"), row
        assert str(row["assigned_driver_name"]).startswith("ND"), row
        assert row["assigned_driver_id"] is not None, row


@pytest.fixture
def driver_history_without_coords():
    """Same shape as ``driver_history``, but no restaurant has coordinates.

    ``RestaurantCreate`` and POST /admin/restaurants never set lat/lng, so every
    restaurant created at runtime looks like this. The earnings query joins the
    restaurant row and selects its coordinates, so a NULL here is authoritative --
    and the lazy ``order.restaurant`` load it used to fall back on could only
    ever read those same NULLs, at one query per delivery.
    """
    db = SessionLocal()
    driver = User(
        email="nocoord_drv@example.com", name="NOCoordDrv", password_hash="x", role="delivery"
    )
    db.add(driver)
    db.flush()
    n = 20
    customers, restaurants = [], []
    for i in range(n):
        c = User(
            email=f"nocoord_dc{i}@example.com",
            name=f"NOCO{i}",
            password_hash="x",
            role="customer",
        )
        db.add(c)
        customers.append(c)
    db.flush()
    for i in range(n):
        r = Restaurant(
            user_id=driver.id,
            name=f"NOCoord Diner {i}",
            address="a",
            cuisine="test",
            lat=None,
            lng=None,
        )
        db.add(r)
        restaurants.append(r)
    db.flush()
    orders = []
    for i in range(n):
        o = Order(
            customer_id=customers[i].id,
            restaurant_id=restaurants[i].id,
            status="DELIVERED",
            total=10.0 + i,
            delivery_address="somewhere",
            delivery_city="Chennai",
            delivery_lat=13.05,
            delivery_lng=80.02,
        )
        db.add(o)
        orders.append(o)
    db.flush()
    now = datetime(2026, 10, 1, 12, 0, 0)
    for o in orders:
        db.add(Delivery(order_id=o.id, driver_id=driver.id, delivered_time=now))
    db.commit()
    yield db, n, driver.id
    # Not wrapped in a bare except on purpose: these rows carry a non-Argon2id
    # password_hash, and a silently failed cleanup leaves them behind for
    # test_seeded_passwords_are_argon2id to trip over later in the run.
    try:
        order_ids = [o.id for o in orders]
        db.query(Delivery).filter(Delivery.order_id.in_(order_ids)).delete(
            synchronize_session=False
        )
        db.query(Order).filter(Order.id.in_(order_ids)).delete(synchronize_session=False)
        db.query(Restaurant).filter(Restaurant.name.like("NOCoord %")).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.email.like("nocoord_%")).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def test_driver_earnings_does_not_query_restaurants_per_coordinate_less_delivery(
    driver_history_without_coords,
):
    """A restaurant with no coordinates must not cost a query per delivery.

    The earnings query already selects Restaurant.lat/lng, so the only missing
    piece was resolving the legacy tracking fallback from the id instead of
    re-reading the row the join had just read.
    """
    db, n, driver_id = driver_history_without_coords
    queries = _count_queries(
        db, lambda: orders_router.driver_earnings(DriverUser(driver_id), db)
    )
    assert queries <= 2, (
        f"driver_earnings issued {queries} queries for {n} deliveries at "
        "coordinate-less restaurants; the restaurant row is already joined, so "
        "the fallback must be resolved from the id"
    )


def test_driver_earnings_still_pays_out_for_coordinate_less_deliveries(
    driver_history_without_coords,
):
    """The fallback is what decides the distance, so it must still resolve.

    With no coordinates anywhere, tracking's legacy COORDINATES dict misses these
    restaurant ids and restaurant_start lands on the demo home. That is a real
    position, so the route distance resolves and gets clamped -- it is not the
    hardcoded 1.0 km the handler substitutes when the resolver raises. Every
    delivery resolves to the same demo home, so they must all agree.
    """
    db, n, driver_id = driver_history_without_coords
    result = orders_router.driver_earnings(DriverUser(driver_id), db)

    assert result["total_deliveries"] == n
    assert result["completed_deliveries"] == n
    assert result["total_earnings"] > 0
    assert result["per_delivery_rate"] > 0
    recent = result["recent"]
    assert len(recent) == 10
    distances = {row["distance_km"] for row in recent}
    assert len(distances) == 1, f"deliveries disagree on distance: {distances}"
    distance = distances.pop()
    assert distance > 1.0, (
        f"distance {distance} is the 1.0 km stand-in for a resolver that raised; "
        "a coordinate-less restaurant must still resolve via the demo home"
    )
    assert distance <= MAX_EARNINGS_DISTANCE_KM
    for row in recent:
        assert row["distance_km"] >= 1.0, (
            f"delivery {row['delivery_id']} got distance {row['distance_km']}, "
            "below the floor"
        )
        assert row["earned"] > 0, f"delivery {row['delivery_id']} earned nothing"
        assert row["restaurant_name"].startswith("NOCoord Diner ")
        assert row["customer_name"].startswith("NOCO")
