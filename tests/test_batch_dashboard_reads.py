"""Batch nudge and tracking reads.

Two dashboards fanned out one request per row. The driver page fetched
/{id}/nudge for every in-flight delivery on a five-second poll, so six live
deliveries meant seven requests every five seconds. The customer order history
fetched /tracking/{id} for every non-cancelled order on each render.

Both now have a batch endpoint that reads the orders, their deliveries and
their related rows in a fixed number of statements. The point of these tests is
that the statement count does not grow with the number of orders asked for,
and that the batch endpoint enforces exactly the same access rules as the
per-order endpoint it replaces.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from backend.db import SessionLocal
from backend.models import Delivery, Order, Restaurant, User
from backend.routers import orders as orders_router
from backend.routers import tracking as tracking_router
from backend.tracking_state import build_tracking_state


class CustomerUser:
    def __init__(self, id: int, restaurants=None):
        self.id = id
        self.role = "customer"
        self.restaurants = restaurants or []


class AdminUser:
    id = 1
    role = "admin"


class DriverUser:
    def __init__(self, id: int, restaurants=None):
        self.id = id
        self.role = "delivery"
        self.restaurants = restaurants or []


class RestaurantUser:
    def __init__(self, id: int, restaurants):
        self.id = id
        self.role = "restaurant"
        self.restaurants = restaurants


class _Request:
    """Stands in for OrderIdListRequest in a direct handler call."""

    def __init__(self, order_ids):
        self.order_ids = order_ids


def _count_queries(db, fn) -> int:
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
    emails = db.query(User.id).filter(User.email.like("nbatch%"))
    order_ids = db.query(Order.id).filter(Order.customer_id.in_(emails))
    db.query(Delivery).filter(Delivery.order_id.in_(order_ids)).delete(
        synchronize_session=False
    )
    db.query(Order).filter(Order.customer_id.in_(emails)).delete(
        synchronize_session=False
    )
    db.query(Restaurant).filter(Restaurant.user_id.in_(emails)).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.email.like("nbatch%")).delete(
        synchronize_session=False
    )
    db.commit()


@pytest.fixture
def fleet():
    """One driver with 12 in-flight deliveries and another driver with 12.

    Two drivers, so an authorization bug that ignored the assignment filter
    shows up as leaked nudges rather than passing by accident.

    Each order gets its own restaurant and its own customer. That is not
    realism, it is the only way to catch a missing eager load: with one shared
    restaurant, SQLAlchemy's identity map already holds the row, so a lazy load
    issues nothing and the query count looks fine. With 24 distinct rows, a lazy
    load cannot hide.
    """
    db = SessionLocal()
    _purge(db)
    mine = User(
        email="nbatch_driver@example.com", name="NBatchMine",
        password_hash="x", role="delivery",
    )
    theirs = User(
        email="nbatch_driver2@example.com", name="NBatchTheirs",
        password_hash="x", role="delivery",
    )
    owner = User(
        email="nbatch_owner@example.com", name="NBatchOwner",
        password_hash="x", role="restaurant",
    )
    db.add_all([mine, theirs, owner])
    db.flush()

    # 24 distinct customers and 24 distinct restaurants, one pair per order.
    customers, restaurants = [], []
    for i in range(24):
        customer = User(
            email=f"nbatch_customer{i}@example.com", name=f"NBatchCustomer {i}",
            password_hash="x", role="customer",
        )
        db.add(customer)
        db.flush()
        customers.append(customer)
        restaurant = Restaurant(
            user_id=owner.id, name=f"NBatch Diner {i}", address="a",
            cuisine="test", city="Chennai", rating=4.0,
            lat=12.97, lng=77.59,
        )
        db.add(restaurant)
        db.flush()
        restaurants.append(restaurant)

    mine_orders, theirs_orders = [], []
    for index, (driver, bucket) in enumerate(((mine, mine_orders), (theirs, theirs_orders))):
        for i in range(12):
            order = Order(
                customer_id=customers[index * 12 + i].id,
                restaurant_id=restaurants[index * 12 + i].id,
                status="OUT_FOR_DELIVERY",
                total=1.0,
            )
            db.add(order)
            db.flush()
            db.add(Delivery(order_id=order.id, driver_id=driver.id))
            bucket.append(order.id)
    db.commit()
    yield {
        "db": db,
        "mine_id": mine.id,
        "theirs_id": theirs.id,
        "owner_id": owner.id,
        "customers": customers,
        "restaurants": restaurants,
        "mine_orders": mine_orders,
        "theirs_orders": theirs_orders,
    }
    _purge(db)
    db.close()


# ---- /orders/nudges ----


def test_batch_nudges_do_not_scale_queries_with_order_count(fleet):
    """The point of the endpoint: cost is flat in the number of orders."""
    db = fleet["db"]
    ids = fleet["mine_orders"]
    driver = DriverUser(fleet["mine_id"])
    # Establish the floor on a couple of orders, then check a full page does not
    # cost more. If it did, this would have been N requests from the browser.
    small = _count_queries(
        db, lambda: orders_router.batch_order_nudges(_Request(ids[:2]), driver, db)
    )
    large = _count_queries(
        db, lambda: orders_router.batch_order_nudges(_Request(ids), driver, db)
    )
    assert small == large, (
        f"2 orders cost {small} statements but 12 cost {large}; the batch read "
        "must not fan out per order"
    )
    assert large <= 4, f"batch nudges issued {large} statements for 12 orders"


def test_batch_nudges_returns_one_nudge_per_requested_order(fleet):
    db, driver = fleet["db"], DriverUser(fleet["mine_id"])
    body = orders_router.batch_order_nudges(
        _Request(fleet["mine_orders"]), driver, db
    )
    returned = {n["order_id"] for n in body["nudges"]}
    assert returned == set(fleet["mine_orders"])
    for nudge in body["nudges"]:
        assert nudge["risk"] in {"LOW", "MEDIUM", "HIGH"}
        assert nudge["message"]


def test_batch_nudges_match_the_single_order_endpoint(fleet):
    """Same numbers per order, or the dashboard would disagree with the
    per-order page for the same order."""
    db, driver = fleet["db"], DriverUser(fleet["mine_id"])
    body = orders_router.batch_order_nudges(
        _Request(fleet["mine_orders"]), driver, db
    )
    by_id = {n["order_id"]: n for n in body["nudges"]}
    for order_id in fleet["mine_orders"][:3]:
        single = orders_router.order_nudge(order_id, driver, db)
        assert single == by_id[order_id]


def test_batch_nudges_exclude_another_drivers_deliveries(fleet):
    """A driver must not see orders they are not assigned."""
    db, driver = fleet["db"], DriverUser(fleet["mine_id"])
    body = orders_router.batch_order_nudges(
        _Request(fleet["mine_orders"] + fleet["theirs_orders"]), driver, db
    )
    returned = {n["order_id"] for n in body["nudges"]}
    assert returned == set(fleet["mine_orders"])
    assert not returned & set(fleet["theirs_orders"])


def test_batch_nudges_are_empty_for_a_driver_with_no_assignments(fleet):
    """No assignments must mean no access, not fall through to everything."""
    db, stranger = fleet["db"], DriverUser(999999)
    body = orders_router.batch_order_nudges(_Request(fleet["mine_orders"]), stranger, db)
    assert body["nudges"] == []


def test_batch_nudges_skip_unknown_order_ids(fleet):
    """An id that does not exist is simply absent, not a 404."""
    db, driver = fleet["db"], DriverUser(fleet["mine_id"])
    body = orders_router.batch_order_nudges(
        _Request(fleet["mine_orders"][:2] + [10**9]), driver, db
    )
    assert {n["order_id"] for n in body["nudges"]} == set(fleet["mine_orders"][:2])


def test_batch_nudges_give_the_owner_and_admin_everything_they_may_see(fleet):
    """Restaurant owners and admins keep the access the single endpoint gave."""
    db = fleet["db"]
    owner = RestaurantUser(fleet["owner_id"], fleet["restaurants"])
    body = orders_router.batch_order_nudges(
        _Request(fleet["mine_orders"] + fleet["theirs_orders"]), owner, db
    )
    assert {n["order_id"] for n in body["nudges"]} == set(
        fleet["mine_orders"] + fleet["theirs_orders"]
    )

    admin_body = orders_router.batch_order_nudges(
        _Request(fleet["mine_orders"] + fleet["theirs_orders"]), AdminUser(), db
    )
    assert len(admin_body["nudges"]) == 24


def test_batch_nudges_exclude_customers_even_for_their_own_orders(fleet):
    """A customer gets nothing from the nudge endpoint, batched or not.

    The single endpoint 403s a customer even on their own order -- nudges are
    an operations signal, not something the buyer sees. This test exists because
    the batch was written with a customer branch first, which quietly widened
    access the single endpoint denies.
    """
    db = fleet["db"]
    # This customer really does own one of the orders, so the assertion is that
    # even the owner is refused, not that the ids were simply unowned.
    customer_row = fleet["customers"][fleet["mine_orders"].index(fleet["mine_orders"][0])]
    customer = CustomerUser(customer_row.id)
    owned = db.query(Order.id).filter(Order.customer_id == customer.id).all()
    owned = [row[0] for row in owned]
    assert owned, "fixture bug: the first customer owns no order"

    body = orders_router.batch_order_nudges(_Request(owned), customer, db)
    assert body["nudges"] == []

    # Same order, same user: the single endpoint also refuses.
    with pytest.raises(HTTPException) as exc:
        orders_router.order_nudge(owned[0], customer, db)
    assert exc.value.status_code == 403


# ---- /tracking/batch ----
#
# These run as the admin, because the fixture gives every order its own customer
# and no single customer owns a full page. Admin sees every order, which is the
# case the eager joins exist for -- the alternative, 12 orders on one customer,
# is satisfied by the identity map and so proves nothing.


def test_batch_tracking_does_not_scale_queries_with_order_count(fleet):
    db, ids = fleet["db"], fleet["mine_orders"]
    admin = AdminUser()
    small = _count_queries(
        db, lambda: tracking_router.batch_tracking(_Request(ids[:2]), admin, db)
    )
    large = _count_queries(
        db, lambda: tracking_router.batch_tracking(_Request(ids), admin, db)
    )
    assert small == large, (
        f"2 orders cost {small} statements but 12 cost {large}; restaurant and "
        "customer must be joined, not read per order"
    )
    assert large <= 4, f"batch tracking issued {large} statements for 12 orders"


def test_batch_tracking_returns_a_state_per_order(fleet):
    """Every order gets its own restaurant and customer, so this only passes if
    the eager join is really there. A lazy load on a shared row is free."""
    db = fleet["db"]
    mine = set(fleet["mine_orders"])
    body = tracking_router.batch_tracking(_Request(fleet["mine_orders"]), AdminUser(), db)
    assert set(body["states"]) == mine
    for order_id, state in body["states"].items():
        assert state["order_id"] == order_id
        assert state["route"], f"order {order_id} came back with no route"
        assert state["restaurant_name"].startswith("NBatch Diner")
        # Distinct names per restaurant, so a mismatched join would show.
        assert state["restaurant_name"] == f"NBatch Diner {mine_order_index(fleet, order_id)}"
        assert state["customer_name"].startswith("NBatchCustomer")


def mine_order_index(fleet, order_id: int) -> int:
    """Which restaurant a driver's order belongs to, derived from the fixture."""
    return fleet["mine_orders"].index(order_id)


def test_batch_tracking_matches_the_single_order_endpoint(fleet):
    """The preview on the order list must agree with the tracking page."""
    db = fleet["db"]
    body = tracking_router.batch_tracking(
        _Request(fleet["mine_orders"]), AdminUser(), db
    )
    single = tracking_router.get_tracking(fleet["mine_orders"][0], AdminUser(), db)
    assert single == body["states"][fleet["mine_orders"][0]]


def test_batch_tracking_excludes_orders_the_caller_cannot_see(fleet):
    """A customer who owns none of these orders gets nothing back.

    The single endpoint 403s the same request, so the batch is not opening a
    hole the per-order endpoint was closing.
    """
    db = fleet["db"]
    intruder = CustomerUser(999999)
    body = tracking_router.batch_tracking(_Request(fleet["mine_orders"]), intruder, db)
    assert body["states"] == {}

    with pytest.raises(HTTPException) as exc:
        tracking_router.get_tracking(fleet["mine_orders"][0], intruder, db)
    assert exc.value.status_code == 403


def test_batch_tracking_gives_the_driver_only_their_deliveries(fleet):
    db, driver = fleet["db"], DriverUser(fleet["mine_id"])
    body = tracking_router.batch_tracking(
        _Request(fleet["mine_orders"] + fleet["theirs_orders"]), driver, db
    )
    assert set(body["states"]) == set(fleet["mine_orders"])


def test_batch_tracking_gives_a_customer_their_own_orders(fleet):
    """The access rule that matters for the order-history page."""
    db = fleet["db"]
    customer = fleet["customers"][0]
    own = db.query(Order.id).filter(Order.customer_id == customer.id).all()
    own = [row[0] for row in own]
    body = tracking_router.batch_tracking(
        _Request(own), CustomerUser(customer.id), db
    )
    assert set(body["states"]) == set(own)


def test_batch_tracking_skips_unknown_ids(fleet):
    db = fleet["db"]
    body = tracking_router.batch_tracking(
        _Request([fleet["mine_orders"][0], 10**9]), AdminUser(), db
    )
    assert set(body["states"]) == {fleet["mine_orders"][0]}
