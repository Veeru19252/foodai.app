"""Single-order serialization query-shape tests.

The order detail and receipt serializers read four relationships that are all
declared lazy: order.restaurant, order.customer, order.items, and each line
item's menu_item. Serializing straight from a plain ``db.query(Order)`` was one
SELECT per line item on top of the order itself, on every endpoint that returns
an order.

``CreateOrderRequest.items`` has no ``max_length``, so the line-item count is
the client's choice, which makes this the one place where a single request can
ask for an unbounded number of round-trips.

The fixtures give each line item a distinct menu item on purpose. SQLAlchemy's
identity map absorbs a lazy load for a row it already holds, so sharing one
menu item across lines would make the count look flat and the test vacuous.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend.models import MenuItem, Order, OrderItem, Restaurant, User
from backend.routers import orders as orders_router


class CustomerUser:
    def __init__(self, id: int):
        self.id = id
        self.role = "customer"
        self.name = "NCustomer"
        self.email = "ncustomer@example.com"
        self.restaurants = []


def _count_queries(db: Session, fn) -> int:
    """Count the statements this session issues while fn runs.

    Listens on the session's own Connection rather than the engine: the
    background simulation task shares the engine and can fire a statement at
    any moment, which would otherwise be attributed to the code under test.
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


def _purge(db: Session) -> None:
    """Remove leftovers from a previous interrupted run."""
    owner_ids = db.query(User.id).filter(User.email.like("ndet_%"))
    restaurant_ids = db.query(Restaurant.id).filter(Restaurant.name.like("NDet%"))
    db.query(OrderItem).filter(
        OrderItem.order_id.in_(db.query(Order.id).filter(Order.restaurant_id.in_(restaurant_ids)))
    ).delete(synchronize_session=False)
    db.query(Order).filter(Order.restaurant_id.in_(restaurant_ids)).delete(
        synchronize_session=False
    )
    db.query(MenuItem).filter(MenuItem.restaurant_id.in_(restaurant_ids)).delete(
        synchronize_session=False
    )
    db.query(Restaurant).filter(Restaurant.id.in_(restaurant_ids)).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.email.like("ndet_%")).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def orders_with_lines():
    """A cart of orders whose line items are all distinct menu items."""
    db = SessionLocal()
    _purge(db)
    groups = 4
    lines = 8
    customer = User(
        email="ndet_cust@example.com", name="NDetCust", password_hash="x", role="customer"
    )
    db.add(customer)
    db.flush()
    restaurant = Restaurant(
        user_id=customer.id, name="NDetDiner", address="a", cuisine="test"
    )
    db.add(restaurant)
    db.flush()
    menu = []
    for i in range(lines):
        m = MenuItem(
            restaurant_id=restaurant.id, name=f"NDet Item {i}", price=10.0 + i, prep_time_min=10
        )
        db.add(m)
        menu.append(m)
    db.flush()
    order_ids = []
    for _g in range(groups):
        order = Order(
            customer_id=customer.id,
            restaurant_id=restaurant.id,
            status="PLACED",
            total=100.0,
        )
        db.add(order)
        db.flush()
        order_ids.append(order.id)
        for m in menu:
            db.add(
                OrderItem(
                    order_id=order.id, menu_item_id=m.id, quantity=2, price=m.price
                )
            )
    db.commit()
    yield db, order_ids, customer.id, lines
    _purge(db)
    db.close()


def test_order_detail_query_count_does_not_grow_with_line_items(orders_with_lines):
    db, order_ids, _cid, lines = orders_with_lines
    db.expunge_all()
    queries = _count_queries(
        db, lambda: orders_router._order_detail(
            orders_router._reload_for_detail(db, order_ids[0])
        )
    )
    # One for the order, then one each for restaurant, customer, items and
    # their menu items. Anything above that is a per-line-item query.
    assert queries <= 5, (
        f"serializing a {lines}-line order issued {queries} queries; "
        "expected at most 5 regardless of line count"
    )


def test_batch_detail_query_count_does_not_grow_with_group_count(orders_with_lines):
    db, order_ids, _cid, lines = orders_with_lines
    db.expunge_all()
    queries = _count_queries(
        db,
        lambda: [
            orders_router._order_detail(o)
            for o in orders_router._reload_all_for_detail(db, order_ids)
        ],
    )
    assert queries <= 5, (
        f"serializing {len(order_ids)} orders of {lines} lines each issued "
        f"{queries} queries; the relationships must load once for the cart"
    )


def test_order_detail_still_returns_every_line_item_name(orders_with_lines):
    """An eager-load bug must not pass by returning less data."""
    db, order_ids, _cid, lines = orders_with_lines
    db.expunge_all()
    payload = orders_router._order_detail(
        orders_router._reload_for_detail(db, order_ids[0])
    )
    assert [item["name"] for item in payload["items"]] == [
        f"NDet Item {i}" for i in range(lines)
    ]
    assert payload["restaurant_name"] == "NDetDiner"
    assert payload["customer_name"] == "NDetCust"


def test_reload_preserves_the_order_of_a_batch(orders_with_lines):
    """The cart response must line up with the request, so the reload keeps order."""
    db, order_ids, _cid, _lines = orders_with_lines
    reversed_ids = list(reversed(order_ids))
    reloaded = orders_router._reload_all_for_detail(db, reversed_ids)
    assert [o.id for o in reloaded] == reversed_ids


def test_reload_handles_an_empty_batch(orders_with_lines):
    db, _order_ids, _cid, _lines = orders_with_lines
    assert orders_router._reload_all_for_detail(db, []) == []


def test_reload_skips_ids_that_are_gone(orders_with_lines):
    """A concurrent delete must not turn the response into a 500."""
    db, order_ids, _cid, _lines = orders_with_lines
    assert orders_router._reload_all_for_detail(db, [*order_ids, 999999999]) == [
        o for o in orders_router._reload_all_for_detail(db, order_ids)
    ]


def test_receipt_query_count_does_not_grow_with_line_items(orders_with_lines):
    """The receipt reads the same four relationships as the detail view."""
    db, order_ids, cid, lines = orders_with_lines
    db.expunge_all()
    user = CustomerUser(cid)
    queries = _count_queries(
        db, lambda: orders_router.order_receipt(order_ids[0], user, db)
    )
    assert queries <= 5, (
        f"a receipt for a {lines}-line order issued {queries} queries; "
        "expected at most 5 regardless of line count"
    )


def test_receipt_still_returns_line_items_and_totals(orders_with_lines):
    db, order_ids, cid, lines = orders_with_lines
    db.expunge_all()
    body = orders_router.order_receipt(order_ids[0], CustomerUser(cid), db)
    assert [item["name"] for item in body["items"]] == [
        f"NDet Item {i}" for i in range(lines)
    ]
    assert body["restaurant_name"] == "NDetDiner"
    assert body["billed_to"] == "ndet_cust@example.com"
    assert body["food_total"] == sum((10.0 + i) * 2 for i in range(lines))
