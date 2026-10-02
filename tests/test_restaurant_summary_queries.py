"""Restaurant-list review-summary query-shape tests.

``_review_summary`` feeds the review aggregates shown on every restaurant
payload. It grouped the whole review table unconditionally, so the owner's own
dashboard aggregated every review on the platform to produce one row, and a
filtered listing aggregated restaurants it was not returning.

These tests pin that the aggregate is scoped to the restaurants actually being
rendered, and that the numbers it produces are unchanged by that scoping.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from backend.db import SessionLocal
from backend.models import Order, Restaurant, Review, User
from backend.routers import restaurants as restaurants_router


def _review_statements(db, fn) -> list:
    """Collect the SQL of every statement touching the reviews table."""
    seen: list = []

    def _on_execute(_conn, _cursor, statement, *_args):
        if "review" in statement.lower():
            seen.append(" ".join(statement.split()))

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", _on_execute)
    try:
        fn()
    finally:
        event.remove(connection, "before_cursor_execute", _on_execute)
    return seen


def _purge(db) -> None:
    """Remove leftovers from a previous interrupted run."""
    owner_ids = db.query(User.id).filter(User.email.like("nsum_%"))
    restaurant_ids = db.query(Restaurant.id).filter(
        Restaurant.name.like("NSum%")
    )
    db.query(Review).filter(
        Review.restaurant_id.in_(restaurant_ids)
    ).delete(synchronize_session=False)
    db.query(Order).filter(Order.restaurant_id.in_(restaurant_ids)).delete(
        synchronize_session=False
    )
    db.query(Restaurant).filter(Restaurant.id.in_(restaurant_ids)).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.email.like("nsum_%")).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def platform():
    """One owner with two restaurants, plus noise on restaurants nobody asked for.

    The noise is what the unscoped aggregate used to read: it exists so a test
    can prove the summary is narrowed rather than merely correct.
    """
    db = SessionLocal()
    _purge(db)
    owner = User(
        email="nsum_owner@example.com",
        name="NSumOwner",
        password_hash="x",
        role="restaurant",
    )
    customer = User(
        email="nsum_cust@example.com",
        name="NSumCust",
        password_hash="x",
        role="customer",
    )
    other_owner = User(
        email="nsum_other@example.com",
        name="NSumOther",
        password_hash="x",
        role="restaurant",
    )
    db.add_all([owner, customer, other_owner])
    db.flush()

    ratings = {
        "NSumMine": [5, 4, 3],
        "NSumSecond": [2, 2],
        "NSumNoise": [1] * 25,
    }
    mine = []
    for name, values in ratings.items():
        own = owner if name in ("NSumMine", "NSumSecond") else other_owner
        restaurant = Restaurant(
            user_id=own.id, name=name, address="a", cuisine="test", city="Chennai"
        )
        db.add(restaurant)
        db.flush()
        if name in ("NSumMine", "NSumSecond"):
            mine.append(restaurant.id)
        for rating in values:
            order = Order(
                customer_id=customer.id,
                restaurant_id=restaurant.id,
                status="DELIVERED",
                total=1.0,
            )
            db.add(order)
            db.flush()
            db.add(
                Review(
                    order_id=order.id,
                    user_id=customer.id,
                    restaurant_id=restaurant.id,
                    rating=rating,
                    comment="x",
                )
            )
    db.commit()
    yield db, mine
    _purge(db)
    db.close()


def test_scoped_summary_matches_the_unscoped_numbers(platform):
    db, mine = platform
    everything = restaurants_router._review_summary(db)
    scoped = restaurants_router._review_summary(db, mine)
    for restaurant_id in mine:
        assert scoped[restaurant_id] == everything[restaurant_id]
    assert scoped[mine[0]] == {"reviews_rating": 4.0, "review_count": 3}
    assert scoped[mine[1]] == {"reviews_rating": 2.0, "review_count": 2}


def test_scoped_summary_returns_only_the_restaurants_asked_for(platform):
    db, mine = platform
    scoped = restaurants_router._review_summary(db, mine)
    assert set(scoped) == set(mine)
    assert "NSumNoise" not in {
        r.name for r in db.query(Restaurant).filter(Restaurant.id.in_(scoped))
    }


def test_scoped_summary_does_not_group_the_whole_review_table(platform):
    """The narrow query must carry a restaurant filter, not just return fewer rows."""
    db, mine = platform
    statements = _review_statements(
        db, lambda: restaurants_router._review_summary(db, mine)
    )
    assert len(statements) == 1
    assert "WHERE" in statements[0] and "restaurant_id IN" in statements[0]


def test_scoped_summary_with_no_ids_skips_the_query(platform):
    """An empty restaurant list has nothing to summarise; do not scan to find that out."""
    db, _mine = platform
    assert restaurants_router._review_summary(db, []) == {}
    assert _review_statements(
        db, lambda: restaurants_router._review_summary(db, [])
    ) == []


class OwnerUser:
    """Minimal stand-in for the auth dependency's User."""

    def __init__(self, id: int):
        self.id = id
        self.role = "restaurant"


def test_owner_dashboard_scopes_the_summary_to_its_own_restaurant(platform):
    """Call the real route, so the scoping at the call site is covered too."""
    db, mine = platform
    owner_id = db.query(User.id).filter(User.email == "nsum_owner@example.com").scalar()
    statements = _review_statements(
        db, lambda: restaurants_router.my_restaurant(OwnerUser(owner_id), db)
    )
    review_statements = [s for s in statements if "review" in s.lower()]
    assert len(review_statements) == 1
    assert "restaurant_id IN" in review_statements[0]


def test_restaurant_listing_scopes_the_summary_to_the_listed_restaurants(platform):
    db, _mine = platform
    # Called directly rather than through the client, so the filter parameters
    # have to be passed explicitly instead of arriving as Depends defaults.
    statements = _review_statements(
        db,
        lambda: restaurants_router.list_restaurants(
            cuisine=None, q=None, city=None, lat=None, lng=None, db=db
        ),
    )
    review_statements = [s for s in statements if "review" in s.lower()]
    assert len(review_statements) == 1
    assert "restaurant_id IN" in review_statements[0]


def test_restaurant_without_reviews_is_absent_so_the_payload_default_applies(platform):
    db, _mine = platform
    fresh = Restaurant(
        user_id=db.query(User).filter(User.email == "nsum_owner@example.com").one().id,
        name="NSumFresh",
        address="a",
        cuisine="test",
    )
    db.add(fresh)
    db.flush()
    summary = restaurants_router._review_summary(db, [fresh.id])
    assert fresh.id not in summary
    payload = restaurants_router._restaurant_payload(fresh, summary)
    assert payload["review_count"] == 0
    assert payload["reviews_rating"] == 0.0
