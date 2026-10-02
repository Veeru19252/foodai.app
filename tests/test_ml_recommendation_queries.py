"""Recommendation query shape and scoring invariants.

``/ml/recommendations`` scores the whole catalogue on every request, so it is
the one endpoint whose cost scales with the platform rather than with the
customer. Two things have to hold: the statement count must not grow with the
customer's history or the catalogue size, and the scores must not change --
this is a load-shedding fix, not a re-ranking.

The scoring weights are asserted directly rather than through a golden
response, because a golden response would only prove the ranking still happens
to come out in the same order, which is a weaker guarantee than the arithmetic.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from backend.db import SessionLocal
from backend.models import Order, Restaurant, Review, User
from backend.routers import ml as ml_router


class CustomerUser:
    def __init__(self, id: int):
        self.id = id
        self.role = "customer"


def _count_queries(db, fn) -> int:
    """Count statements on this session's own connection.

    Listens on the Connection, not the engine: the background simulation task
    shares the engine and would otherwise be attributed to the endpoint.
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


def _purge(db) -> None:
    """Remove anything a previous interrupted run may have left behind."""
    emails = db.query(User.id).filter(User.email.like("nmlrec%"))
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
    db.query(User).filter(User.email.like("nmlrec%")).delete(
        synchronize_session=False
    )
    db.commit()


@pytest.fixture
def catalogue():
    """A customer with 40 orders over 20 distinct restaurants, plus 20 unvisited.

    Both halves matter. The visited ones must not inflate the statement count
    (that would reintroduce an N+1), and the unvisited ones must still be scored
    rather than silently dropped -- a restaurant nobody ordered from is exactly
    what a recommendation is for.
    """
    db = SessionLocal()
    _purge(db)
    customer = User(
        email="nmlrec_customer@example.com",
        name="NMLRecCustomer",
        password_hash="x",
        role="customer",
    )
    owner = User(
        email="nmlrec_owner@example.com",
        name="NMLRecOwner",
        password_hash="x",
        role="restaurant",
    )
    db.add_all([customer, owner])
    db.flush()

    visited, unvisited = [], []
    for i in range(40):
        # The first 20 are visited and share a cuisine, so affinity is exactly
        # 1.0 for them and exactly 0.0 for the unvisited half. That makes the
        # cuisine term a known constant instead of something to reverse-engineer
        # from the response.
        cuisine = "NMLRec North" if i < 20 else "NMLRec South"
        rating = 3.0 + (i % 20) / 10.0
        restaurant = Restaurant(
            user_id=owner.id,
            name=f"NMLRec Diner {i}",
            address="a",
            cuisine=cuisine,
            city="Chennai",
            rating=rating,
        )
        db.add(restaurant)
        db.flush()
        # The first 20 are ordered from twice each; the rest are never visited.
        (visited if i < 20 else unvisited).append(restaurant)

    for restaurant in visited:
        for _ in range(2):
            order = Order(
                customer_id=customer.id,
                restaurant_id=restaurant.id,
                status="DELIVERED",
                total=1.0,
            )
            db.add(order)
            db.flush()
            # A review so the popularity term is exercised too.
            db.add(
                Review(
                    order_id=order.id,
                    user_id=customer.id,
                    restaurant_id=restaurant.id,
                    rating=4,
                    comment="x",
                )
            )
    db.commit()
    yield {
        "db": db,
        "customer_id": customer.id,
        "visited": visited,
        "unvisited": unvisited,
    }
    _purge(db)
    db.close()


def test_recommendations_do_not_scale_queries_with_history_or_catalogue(catalogue):
    """Statement count must be constant, whatever the table sizes.

    This is the load-shedding guarantee: the catalogue is read once, not once
    per order, and the review aggregate is a single grouped query.
    """
    db = catalogue["db"]
    queries = _count_queries(
        db, lambda: ml_router.get_recommendations(CustomerUser(catalogue["customer_id"]), db)
    )
    assert queries == 3, (
        f"get_recommendations issued {queries} queries for "
        f"{len(catalogue['visited']) + len(catalogue['unvisited'])} restaurants and "
        f"{len(catalogue['visited']) * 2} orders; expected the order history, the "
        "catalogue, and one grouped review aggregate"
    )


def test_recommendations_read_only_the_columns_they_use(catalogue):
    """The order and catalogue reads must be column-only.

    A query-count assertion cannot catch this: loading full entities issues the
    same three statements, it just moves far more data and builds far more
    objects for the same answer. So assert the projection directly.
    """
    db = catalogue["db"]
    statements = []

    def _capture(conn, cursor, statement, *_args):
        statements.append(statement)

    event.listen(db.connection(), "before_cursor_execute", _capture)
    try:
        ml_router.get_recommendations(CustomerUser(catalogue["customer_id"]), db)
    finally:
        event.remove(db.connection(), "before_cursor_execute", _capture)

    order_select = next(s for s in statements if "FROM orders" in s)
    assert "orders.restaurant_id" in order_select
    # The scoring never reads created_at, total, status or any payment column,
    # so selecting them means fetching a row's worth of data per order for
    # nothing.
    for unused in ("orders.total", "orders.status", "orders.created_at"):
        assert unused not in order_select, f"{unused} is fetched but never scored"

    restaurant_select = next(s for s in statements if "FROM restaurants" in s)
    for column in ("restaurants.id", "restaurants.name", "restaurants.cuisine"):
        assert column in restaurant_select
    # lat/lng/address matter to display; user_id and rating must also be there.
    assert "restaurants.rating" in restaurant_select
    for unused in ("restaurants.user_id", "restaurants.city"):
        assert unused not in restaurant_select, f"{unused} is fetched but never scored"


def test_recommendations_still_return_a_fixed_number_of_rows(catalogue):
    """The response is capped at 4, whatever the catalogue holds.

    The cap is what makes the single catalogue read affordable; a regression that
    returned the whole scored list would quietly reintroduce the payload blowup
    this endpoint had.
    """
    db = catalogue["db"]
    body = ml_router.get_recommendations(CustomerUser(catalogue["customer_id"]), db)
    assert len(body["recommendations"]) == 4
    assert body["fallback"] is False


def test_recommendations_score_matches_the_documented_weights(catalogue):
    """The score is a fixed weighted sum; assert it rather than golden-match.

    Guards the column-only rewrite: it reads the same five columns as before,
    and a mis-wired tuple unpack would show up as a wrong score rather than only
    as a missing field.

    Only the returned page is checked, since the seeded demo restaurants share
    the catalogue and the response is capped at 4. Every visited restaurant
    should beat every unvisited one though, so at least some of them are here.
    """
    db = catalogue["db"]
    body = ml_router.get_recommendations(CustomerUser(catalogue["customer_id"]), db)
    recommended = {r["restaurant_id"] for r in body["recommendations"]}
    visited_ids = {r.id for r in catalogue["visited"]}
    unvisited_ids = {r.id for r in catalogue["unvisited"]}
    assert recommended & visited_ids, "no restaurant the customer ordered from ranked"

    for rec in body["recommendations"]:
        if rec["restaurant_id"] not in visited_ids:
            continue
        # Ordered from twice: familiarity saturates at 1.0 after two orders, and
        # both orders were at this cuisine so the affinity term is 1.0 too.
        assert rec["review_count"] == 2
        assert rec["reviews_rating"] == 4.0
        assert rec["reason"].startswith("You've ordered here 2")
        rating = next(
            r.rating for r in catalogue["visited"] if r.id == rec["restaurant_id"]
        )
        expected = (
            0.45 * ((rating or 0.0) / 5.0) + 0.30 * 1.0 + 0.15 * 1.0 + 0.10 * 0.4
        )
        assert rec["score"] == pytest.approx(round(expected, 3))

    # A restaurant nobody ordered from and nobody reviewed has no familiarity
    # and no popularity term at all, so it must score below any visited one.
    for rec in body["recommendations"]:
        if rec["restaurant_id"] in unvisited_ids:
            assert rec["review_count"] == 0
            assert rec["score"] < 0.45 + 0.30 + 0.15 + 0.10


def test_recommendations_are_ranked_by_score(catalogue):
    """The response is sorted, so a caller can render it as-is."""
    db = catalogue["db"]
    body = ml_router.get_recommendations(CustomerUser(catalogue["customer_id"]), db)
    scores = [r["score"] for r in body["recommendations"]]
    assert scores == sorted(scores, reverse=True)


def test_customer_without_orders_gets_the_fallback(catalogue):
    """No history means nothing can be attributed to familiarity or affinity."""
    db = catalogue["db"]
    fresh = User(
        email="nmlrec_fresh@example.com",
        name="NMLRecFresh",
        password_hash="x",
        role="customer",
    )
    db.add(fresh)
    db.commit()
    body = ml_router.get_recommendations(CustomerUser(fresh.id), db)
    assert body["fallback"] is True
    assert len(body["recommendations"]) == 4
    for rec in body["recommendations"]:
        # The seeded demo restaurants have reviews, so the reason can be either
        # of the two rating-based ones -- what it must not be is an order-based
        # claim, which would mean the empty history leaked into the scoring.
        assert not rec["reason"].startswith("You've ordered here")
        assert not rec["reason"].startswith("You like")


class _EmptyRows:
    """A query that filters down to nothing, chainable like the real one."""

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return []


class _EmptySession:
    """A session that reads nothing, standing in for a platform with no data.

    Avoids deleting the seeded demo catalogue, which other suites in this
    session-scoped database rely on.
    """

    def query(self, *_args, **_kwargs):
        return _EmptyRows()


def test_empty_catalogue_returns_an_empty_fallback():
    """A platform with no restaurants must return the empty shape, not raise."""
    body = ml_router.get_recommendations(CustomerUser(1), _EmptySession())
    assert body == {"recommendations": [], "fallback": True}