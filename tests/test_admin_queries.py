"""Admin dashboard query-shape tests.

The admin dashboard is polled, and it reads related rows (customer and
restaurant names) for every order it returns. Those two properties are easy to
regress and expensive in production:

* leaving the relationships lazy issues two extra SELECTs per order, so the
  query count grows with the table (401 queries for 200 orders);
* computing revenue by loading every order total into Python makes memory and
  time grow with the order history.

These assert query *counts*, not just output, so a re-introduced N+1 fails
here. The output is asserted too, since an eager-load bug that drops a name
would otherwise pass silently.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend.models import VALID_ORDER_STATUSES, Order, Restaurant, User
from backend.routers import admin


class AdminUser:
    """Stands in for the dependency; require_roles is covered by the API tests."""

    role = "admin"


@pytest.fixture
def populated_db():
    """N orders, each with its own customer and restaurant.

    Distinct rows per order matter: with a handful of shared rows SQLAlchemy's
    identity map would absorb most of the lazy loads and hide the N+1. Real
    ids are returned rather than assumed, since seeded demo data means they do
    not start at 1.
    """
    db = SessionLocal()
    n = 40
    users: list[User] = []
    restaurants: list[Restaurant] = []
    try:
        for i in range(n):
            u = User(
                email=f"qshape{i}@example.com",
                name=f"Q{i}",
                password_hash="x",
                role="customer",
            )
            db.add(u)
            users.append(u)
        db.flush()
        for i in range(n):
            r = Restaurant(
                user_id=users[i].id,
                name=f"Diner {i}",
                address="a",
                cuisine="test",
            )
            db.add(r)
            restaurants.append(r)
        db.flush()
        for i in range(n):
            db.add(
                Order(
                    customer_id=users[i].id,
                    restaurant_id=restaurants[i].id,
                    status="PLACED",
                    total=10.0 + i,
                    created_at=datetime(2026, 10, 1, 12, 0, 0),
                )
            )
        db.commit()
        # Map each of this fixture's order ids to its index, so the assertions
        # below do not depend on the shared database's id sequence.
        mine = {
            o.id: i
            for i, o in enumerate(
                db.query(Order)
                .filter(Order.customer_id.in_([u.id for u in users]))
                .order_by(Order.customer_id)
                .all()
            )
        }
        yield db, n, mine
    finally:
        # Leave the shared session-scoped database as we found it: children
        # first, then parents, so the foreign keys stay satisfied.
        if users:
            db.query(Order).filter(
                Order.customer_id.in_([u.id for u in users])
            ).delete(synchronize_session=False)
            db.query(Restaurant).filter(
                Restaurant.user_id.in_([u.id for u in users])
            ).delete(synchronize_session=False)
            db.query(User).filter(
                User.email.like("qshape%@example.com")
            ).delete(synchronize_session=False)
            db.commit()
        db.close()


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


def test_all_orders_does_not_issue_a_query_per_order(populated_db):
    """The dashboard must not scale its query count with the table."""
    db, n, _mine = populated_db
    queries = _count_queries(db, lambda: admin.all_orders(AdminUser(), db))
    # 2 = the page query plus the X-Total-Count COUNT; it must not grow with n.
    assert queries <= 2, (
        f"admin.all_orders issued {queries} queries for {n} orders; "
        "customer/restaurant must be eager-loaded"
    )


def test_all_orders_returns_the_related_names(populated_db):
    """Eager loading must not quietly drop the names it was meant to prefetch."""
    db, n, expected = populated_db
    rows = admin.all_orders(AdminUser(), db)

    # Scope to this fixture's orders: the shared database may hold rows from
    # the seeded demo data or other tests, so the newest row overall is not
    # necessarily one of ours.
    mine = {r["id"]: r for r in rows if r["id"] in expected}
    assert len(mine) == n
    for order_id, index in expected.items():
        row = mine[order_id]
        assert row["customer_name"] == f"Q{index}", row
        assert row["restaurant_name"] == f"Diner {index}", row
        assert row["total"] == round(10.0 + index, 2)


def test_overview_does_not_issue_a_query_per_role_or_status(populated_db):
    """Grouped counts: the overview must not scale with roles/statuses.

    The dashboard polls this endpoint, so the old one-query-per-value shape
    cost 14 round-trips per poll. Six is the floor: role counts, status counts,
    active deliveries, revenue, restaurants, menu items.
    """
    db, _n, _mine = populated_db
    queries = _count_queries(db, lambda: admin.overview(AdminUser(), db))
    assert queries <= 6, (
        f"admin.overview issued {queries} queries; expected 6 grouped counts"
    )


def test_overview_reports_every_role_and_status_even_at_zero(populated_db):
    """Grouping must not drop a role or status that currently has no rows."""
    db, _n, _mine = populated_db
    body = admin.overview(AdminUser(), db)
    assert set(body["users"]) == {"customer", "restaurant", "delivery", "admin"}
    assert set(body["orders_by_status"]) == set(VALID_ORDER_STATUSES)
    assert all(isinstance(v, int) for v in body["users"].values())
    assert all(isinstance(v, int) for v in body["orders_by_status"].values())


def test_overview_revenue_is_summed_in_the_database(client, monkeypatch):
    """A SQL SUM, not a Python sum over every order row.

    Patched at the query level so the assertion fails if anyone reintroduces
    the load-everything-then-sum-in-Python shape, without asserting on the
    database's own plan.
    """
    from sqlalchemy.orm import Query

    original_all = Query.all
    calls = {"all_with_entities": 0}

    def counting_all(self, *args, **kwargs):
        # with_entities(...) is the shape the old implementation used to pull
        # every total into Python.
        if self.column_descriptions and len(self.column_descriptions) == 1:
            calls["all_with_entities"] += 1
        return original_all(self, *args, **kwargs)

    monkeypatch.setattr(Query, "all", counting_all)
    body = client.get("/admin/overview", headers=_admin_headers(client)).json()
    assert body["revenue"] >= 0
    assert calls["all_with_entities"] == 0, (
        "overview must not load order rows to sum them; use func.sum"
    )


def test_overview_revenue_matches_the_orders(client):
    db = SessionLocal()
    try:
        expected = round(
            sum(o.total for o in db.query(Order).all()), 2
        )
    finally:
        db.close()
    body = client.get("/admin/overview", headers=_admin_headers(client)).json()
    assert body["revenue"] == expected
    assert body["total_orders"] == sum(body["orders_by_status"].values())


def _admin_headers(client):
    from conftest import login

    return {"Authorization": f"Bearer {login(client, 'admin@foodai.com')['access_token']}"}
