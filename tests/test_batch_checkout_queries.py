"""Batch checkout notification query-shape tests.

POST /orders/batch creates one order per restaurant group in the cart. After
committing, the endpoint notified each restaurant owner by reading
``order.restaurant`` on the just-inserted instances, then re-read the ids to
serialize the response. Both of those happen after commits, which expire the
instances, so each group cost a row refresh plus a lazy restaurant SELECT -- and
the cart size is entirely client-controlled, since neither ``BatchOrderRequest``
nor ``CreateOrderRequest.items`` has a ``max_length``.

Some restaurant reads are legitimate and do scale with the cart: one inside
_create_single_order per group, plus a single batched selectinload when the
response is serialized. What must not exist is a *second* per-group read from
the notification loop, so these tests assert the slope across two cart sizes
rather than an absolute count, which would just bake in today's internals.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend import security
from backend.db import SessionLocal, engine
from backend.models import MenuItem, Notification, Order, OrderItem, Restaurant, User
from backend.routers import orders as orders_router
from backend.schemas import BatchOrderRequest, CreateOrderRequest

PHONE = "9876543210"


def _build(db: Session, tag: str, groups: int):
    """A customer plus `groups` restaurants, each owned by a distinct user."""
    customer = User(
        email=f"nbatch_{tag}_cust@example.com",
        name=f"NBatchCust {tag}",
        password_hash="x",
        role="customer",
    )
    db.add(customer)
    db.flush()
    spec = []
    for g in range(groups):
        owner = User(
            email=f"nbatch_{tag}_owner{g}@example.com",
            name=f"NBatchOwner {tag}{g}",
            password_hash="x",
            role="restaurant",
        )
        db.add(owner)
        db.flush()
        restaurant = Restaurant(
            user_id=owner.id,
            name=f"NBatch {tag} Diner {g}",
            address="a",
            cuisine="test",
        )
        db.add(restaurant)
        db.flush()
        item = MenuItem(
            restaurant_id=restaurant.id,
            name=f"NBatch {tag} Item {g}",
            price=50.0 + g,
            prep_time_min=10,
        )
        db.add(item)
        db.flush()
        spec.append((restaurant.id, owner.id, item.id))
    db.commit()
    return customer.id, spec


def _purge(db: Session) -> None:
    """Remove everything the tests in this file insert."""
    owner_ids = db.query(User.id).filter(User.email.like("nbatch_%"))
    restaurant_ids = db.query(Restaurant.id).filter(Restaurant.name.like("NBatch%"))
    order_ids = db.query(Order.id).filter(Order.restaurant_id.in_(restaurant_ids))
    db.query(Notification).filter(Notification.order_id.in_(order_ids)).delete(
        synchronize_session=False
    )
    db.query(Notification).filter(Notification.user_id.in_(owner_ids)).delete(
        synchronize_session=False
    )
    db.query(OrderItem).filter(OrderItem.order_id.in_(order_ids)).delete(
        synchronize_session=False
    )
    db.query(Order).filter(Order.id.in_(order_ids)).delete(synchronize_session=False)
    db.query(MenuItem).filter(MenuItem.restaurant_id.in_(restaurant_ids)).delete(
        synchronize_session=False
    )
    db.query(Restaurant).filter(Restaurant.id.in_(restaurant_ids)).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.email.like("nbatch_%")).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def cart_db():
    db = SessionLocal()
    _purge(db)
    yield db
    # Not wrapped in a bare except on purpose: these rows carry a non-Argon2id
    # password_hash, and a silently failed cleanup leaves them behind for
    # test_seeded_passwords_are_argon2id to trip over later in the run.
    _purge(db)
    db.close()


def _payload(spec):
    """A batch body that passes the pre-order gate for every group."""
    otp = security.create_otp_token(PHONE)
    return BatchOrderRequest(
        orders=[
            CreateOrderRequest(
                restaurant_id=rid,
                items=[{"menu_item_id": item_id, "quantity": 1}],
                delivery_phone=PHONE,
                otp_token=otp,
                location_confirmed=True,
                delivery_address="1 Test Lane",
                delivery_lat=18.4089,
                delivery_lng=73.8757,
            )
            for rid, _owner_id, item_id in spec
        ]
    )


def _run_batch(customer_id: int, spec):
    """Run one batch checkout on a dedicated connection; return (sql, response).

    The dedicated connection is what makes the statement list attributable:
    the app's background simulator shares the engine and would otherwise fire
    statements into the middle of the count.
    """
    connection = engine.connect()
    session = Session(bind=connection)
    statements: list = []

    def _on_execute(_conn, _cursor, statement, *_args, **_kwargs):
        statements.append(" ".join(statement.split()))

    try:
        customer = session.query(User).filter(User.id == customer_id).one()
        payload = _payload(spec)
        event.listen(connection, "before_cursor_execute", _on_execute)
        try:
            response = orders_router.create_orders_batch(payload, customer, session, None)
        finally:
            event.remove(connection, "before_cursor_execute", _on_execute)
    finally:
        session.close()
        connection.close()
    return statements, response


def test_notification_loop_adds_no_per_group_restaurant_read(cart_db):
    """Doubling the cart must not double the restaurant reads.

    Two carts, twice the size. The only per-group restaurant read left is the
    one inside _create_single_order, so the difference must equal the number of
    extra groups. Reading order.restaurant in the notify loop would make it
    twice that.
    """
    small_id, small = _build(cart_db, "s", 4)
    large_id, large = _build(cart_db, "l", 8)

    small_sql, small_response = _run_batch(small_id, small)
    large_sql, large_response = _run_batch(large_id, large)

    assert len(small_response.orders) == 4
    assert len(large_response.orders) == 8

    reads = lambda sql: [s for s in sql if "FROM restaurants" in s]
    extra_groups = len(large) - len(small)
    assert len(reads(large_sql)) - len(reads(small_sql)) == extra_groups, (
        f"going from {len(small)} to {len(large)} groups added "
        f"{len(reads(large_sql)) - len(reads(small_sql))} restaurant reads; "
        f"expected {extra_groups} (one per group inside _create_single_order). "
        "A second per-group read means the notify loop is lazy-loading "
        "order.restaurant again."
    )


def test_batch_checkout_notifies_every_restaurant_owner(cart_db):
    """Batching the owner lookup must still notify the right owner per group."""
    customer_id, spec = _build(cart_db, "n", 4)
    _sql, response = _run_batch(customer_id, spec)
    created = {o.id for o in response.orders}
    assert len(created) == 4
    for _rid, owner_id, _item_id in spec:
        rows = (
            cart_db.query(Notification)
            .filter(Notification.user_id == owner_id, Notification.type == "new_order")
            .all()
        )
        matching = [n for n in rows if n.order_id in created]
        assert len(matching) == 1, (
            f"restaurant owner {owner_id} got {len(matching)} new_order "
            "notifications for this cart; expected exactly 1"
        )


def test_batch_checkout_does_not_reread_orders_after_notifying(cart_db):
    """Serializing the response must not re-select each order row.

    notify() commits once per group, so by the time the endpoint reads order.id
    for the response the instances are expired and every read refreshes its row.
    """
    customer_id, spec = _build(cart_db, "r", 4)
    sql, _response = _run_batch(customer_id, spec)

    per_row_refreshes = [s for s in sql if "FROM orders" in s and "orders.id =" in s]
    assert not per_row_refreshes, (
        f"batch checkout issued {len(per_row_refreshes)} single-order refreshes: "
        + " | ".join(s[:140] for s in per_row_refreshes[:3])
    )
