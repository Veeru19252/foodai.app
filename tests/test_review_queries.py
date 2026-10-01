"""Review-list query-shape tests.

The public review list and the owner dashboard both serialize review.user.name,
which is a lazy relationship. Reviews are unbounded and public, so a busy
restaurant is the worst case for a per-row query.

The tests deliberately expunge the session before measuring, so that a lazy
relationship really issues its query. That detaches any ORM object handed out
by the fixture, so the fixture yields plain ids and the ids it needs for
cleanup are captured while the objects are still attached.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from backend.db import SessionLocal
from backend.models import Order, Restaurant, Review, User
from backend.routers import reviews as reviews_router


class OwnerUser:
    def __init__(self, id: int, restaurants):
        self.id = id
        self.role = "restaurant"
        self.restaurants = restaurants


def _purge(db) -> None:
    """Remove anything a previous interrupted run may have left behind."""
    emails = db.query(User.id).filter(User.email.like("nreview%"))
    order_ids = db.query(Order.id).filter(Order.customer_id.in_(emails))
    db.query(Review).filter(Review.order_id.in_(order_ids)).delete(
        synchronize_session=False
    )
    db.query(Order).filter(Order.customer_id.in_(emails)).delete(
        synchronize_session=False
    )
    db.query(Restaurant).filter(Restaurant.user_id.in_(emails)).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.email.like("nreview%")).delete(
        synchronize_session=False
    )
    db.commit()


@pytest.fixture
def many_reviews():
    """N reviews from N distinct customers on one restaurant.

    Distinct customers matter: with a shared reviewer SQLAlchemy's identity
    map would absorb the lazy loads and the query-count assertions would pass
    against the unfixed code.
    """
    db = SessionLocal()
    _purge(db)
    n = 40
    owner = User(
        email="nreview_owner@example.com",
        name="NRevOwner",
        password_hash="x",
        role="restaurant",
    )
    db.add(owner)
    db.flush()
    customers = []
    for i in range(n):
        c = User(
            email=f"nreview_c{i}@example.com",
            name=f"NRC{i}",
            password_hash="x",
            role="customer",
        )
        db.add(c)
        customers.append(c)
    db.flush()
    restaurant = Restaurant(user_id=owner.id, name="NRevDiner", address="a", cuisine="test")
    db.add(restaurant)
    db.flush()
    orders = []
    for i in range(n):
        o = Order(
            customer_id=customers[i].id,
            restaurant_id=restaurant.id,
            status="DELIVERED",
            total=10.0 + i,
        )
        db.add(o)
        orders.append(o)
    db.flush()
    for i, o in enumerate(orders):
        db.add(
            Review(
                restaurant_id=restaurant.id,
                user_id=customers[i].id,
                order_id=o.id,
                rating=4,
                comment=f"n{i}",
            )
        )
    db.commit()
    # Capture everything the teardown needs now, while it is still attached.
    order_ids = [o.id for o in orders]
    owner_id, restaurant_id = owner.id, restaurant.id
    yield db, n, restaurant_id, owner_id
    try:
        db.rollback()
        _purge(db)
    finally:
        db.close()


def test_list_reviews_does_not_issue_a_query_per_review(many_reviews):
    db, n, restaurant_id, _owner_id = many_reviews
    counter = {"n": 0}

    def _on_execute(*_args, **_kwargs):
        counter["n"] += 1

    db.expunge_all()
    connection = db.connection()
    event.listen(connection, "before_cursor_execute", _on_execute)
    try:
        rows = reviews_router.list_reviews(restaurant_id, db)
    finally:
        event.remove(connection, "before_cursor_execute", _on_execute)
    assert len(rows) == n
    assert counter["n"] <= 2, (
        f"list_reviews issued {counter['n']} queries for {n} reviews; "
        "review.user must be eager-loaded"
    )


def test_list_reviews_still_reports_the_reviewer_name(many_reviews):
    """Eager loading must not drop the name it was meant to prefetch."""
    db, n, restaurant_id, _owner_id = many_reviews
    rows = reviews_router.list_reviews(restaurant_id, db)
    mine = {r["id"]: r for r in rows if str(r["user_name"]).startswith("NRC")}
    assert len(mine) == n
    for row in mine.values():
        assert str(row["user_name"]).startswith("NRC"), row
        assert str(row["comment"]).startswith("n"), row


def test_owner_review_dashboard_does_not_issue_a_query_per_review(many_reviews):
    db, n, restaurant_id, owner_id = many_reviews
    counter = {"n": 0}

    def _on_execute(*_args, **_kwargs):
        counter["n"] += 1

    db.expunge_all()
    # Re-read the owner so its restaurants relationship is populated lazily,
    # the way the dependency-injected user would be.
    fresh_owner = db.query(User).filter(User.id == owner_id).first()
    connection = db.connection()
    event.listen(connection, "before_cursor_execute", _on_execute)
    try:
        rows = reviews_router.my_restaurant_reviews(
            OwnerUser(fresh_owner.id, list(fresh_owner.restaurants)), db
        )
    finally:
        event.remove(connection, "before_cursor_execute", _on_execute)
    assert len(rows) == n
    assert counter["n"] <= 4, (
        f"my_restaurant_reviews issued {counter['n']} queries for {n} reviews; "
        "review.user must be eager-loaded"
    )
    assert all(str(r["user_name"]).startswith("NRC") for r in rows)
