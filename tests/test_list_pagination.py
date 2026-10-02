"""Pagination regressions for the previously unbounded list endpoints.

Every endpoint here read a whole table and returned a bare JSON array: a
customer's order history, a driver's deliveries, an admin table, the public
restaurant catalogue, and both review listings. None had a ``LIMIT``, so both
response size and query cost grew with the table rather than with the page.

The contract kept deliberately narrow. Responses are still bare arrays, and
callers that do not pass ``limit``/``offset`` still get everything up to a
generous default. What is new is that the cap exists and that a response says how
many rows it left out via ``X-Total-Count``.

These call handlers directly with the paging arguments, matching the other
query-shape suites in this repo, so the ``Response`` object is passed explicitly.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Response

from backend.db import SessionLocal
from backend.models import Delivery, Order, Restaurant, Review, User
from backend.pagination import DEFAULT_LIMIT, MAX_LIMIT
from backend.routers import admin as admin_router
from backend.routers import orders as orders_router
from backend.routers import restaurants as restaurants_router
from backend.routers import reviews as reviews_router


class CustomerUser:
    def __init__(self, id: int):
        self.id = id
        self.role = "customer"


class AdminUser:
    id = 1
    role = "admin"


class DriverUser:
    def __init__(self, id: int):
        self.id = id
        self.role = "delivery"


class RestaurantUser:
    def __init__(self, id: int):
        self.id = id
        self.role = "restaurant"
        self.restaurants = []


def _purge(db) -> None:
    """Remove anything a previous interrupted run may have left behind.

    Deletes through bulk queries, never through ORM relationships, so the
    foreign keys stay satisfied without relying on cascade behaviour.
    """
    emails = db.query(User.id).filter(User.email.like("npage%"))
    order_ids = db.query(Order.id).filter(
        (Order.customer_id.in_(emails)) | (Order.restaurant_id.in_(emails))
    )
    db.query(Review).filter(Review.order_id.in_(order_ids)).delete(
        synchronize_session=False
    )
    db.query(Review).filter(Review.user_id.in_(emails)).delete(
        synchronize_session=False
    )
    db.query(Review).filter(Review.restaurant_id.in_(emails)).delete(
        synchronize_session=False
    )
    db.query(Delivery).filter(Delivery.order_id.in_(order_ids)).delete(
        synchronize_session=False
    )
    db.query(Order).filter(Order.customer_id.in_(emails)).delete(
        synchronize_session=False
    )
    db.query(Order).filter(Order.restaurant_id.in_(emails)).delete(
        synchronize_session=False
    )
    db.query(Restaurant).filter(Restaurant.user_id.in_(emails)).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.email.like("npage%")).delete(
        synchronize_session=False
    )
    db.commit()


@pytest.fixture
def paged_platform():
    """One customer with 25 orders and one driver with 25 deliveries.

    Distinct restaurants per order, so a lazy load in the order listing cannot
    be absorbed by the identity map and quietly pass a query-count assertion.
    """
    db = SessionLocal()
    _purge(db)
    customer = User(
        email="npage_customer@example.com",
        name="NPageCustomer",
        password_hash="x",
        role="customer",
    )
    owner = User(
        email="npage_owner@example.com",
        name="NPageOwner",
        password_hash="x",
        role="restaurant",
    )
    driver = User(
        email="npage_driver@example.com",
        name="NPageDriver",
        password_hash="x",
        role="delivery",
    )
    db.add_all([customer, owner, driver])
    db.flush()

    n = 25
    restaurants = []
    for i in range(n):
        restaurant = Restaurant(
            user_id=owner.id,
            name=f"NPage Diner {i}",
            address="a",
            cuisine="test",
            city="Chennai",
        )
        db.add(restaurant)
        db.flush()
        restaurants.append(restaurant)

    for i in range(n):
        order = Order(
            customer_id=customer.id,
            restaurant_id=restaurants[i].id,
            status="DELIVERED",
            total=float(i + 1),
        )
        db.add(order)
        db.flush()
        # Delivery carries no status column; the order holds it.
        db.add(Delivery(order_id=order.id, driver_id=driver.id))
        db.add(
            Review(
                order_id=order.id,
                user_id=customer.id,
                restaurant_id=restaurants[i].id,
                rating=(i % 5) + 1,
                comment="x",
            )
        )
    db.commit()
    restaurant_ids = [r.id for r in restaurants]
    yield {
        "db": db,
        "n": n,
        "customer_id": customer.id,
        "owner_id": owner.id,
        "driver_id": driver.id,
        "restaurant_ids": restaurant_ids,
    }
    _purge(db)
    db.close()


def _total_of(response) -> int:
    return int(response.headers["X-Total-Count"])


# ---- /orders ----


def test_my_orders_returns_only_the_requested_page(paged_platform):
    db, n, customer_id = (
        paged_platform["db"],
        paged_platform["n"],
        paged_platform["customer_id"],
    )
    response = Response()
    rows = orders_router.my_orders(CustomerUser(customer_id), db, response, 10, 0)
    assert len(rows) == 10
    # The header is what makes the truncation visible; without it a caller
    # cannot tell a short history from a capped one.
    assert _total_of(response) == n


def test_my_orders_pages_walk_the_whole_history_without_repeating(paged_platform):
    db, n, customer_id = (
        paged_platform["db"],
        paged_platform["n"],
        paged_platform["customer_id"],
    )
    seen = []
    response = Response()
    for offset in range(0, n, 10):
        rows = orders_router.my_orders(
            CustomerUser(customer_id), db, response, 10, offset
        )
        seen.extend(row["id"] for row in rows)
    assert sorted(seen) == sorted(set(seen))
    assert len(seen) == n


def test_my_orders_defaults_to_the_documented_cap(paged_platform):
    db, customer_id = paged_platform["db"], paged_platform["customer_id"]
    response = Response()
    orders_router.my_orders(CustomerUser(customer_id), db, response)
    assert int(response.headers["X-Total-Count"]) == paged_platform["n"]
    # The fixture is under the default, so an unpaged call is unchanged for a
    # realistic history -- the cap only bites on a pathological table.
    assert DEFAULT_LIMIT >= paged_platform["n"]


# ---- /orders/driver ----


def test_driver_orders_returns_only_the_requested_page(paged_platform):
    db, n, driver_id = (
        paged_platform["db"],
        paged_platform["n"],
        paged_platform["driver_id"],
    )
    response = Response()
    rows = orders_router.driver_orders(DriverUser(driver_id), db, response, 8, 0)
    assert len(rows) == 8
    assert _total_of(response) == n


# ---- /orders/restaurant ----


def test_restaurant_orders_returns_only_the_requested_page(paged_platform):
    db, n, owner_id = (
        paged_platform["db"],
        paged_platform["n"],
        paged_platform["owner_id"],
    )
    response = Response()
    rows = orders_router.restaurant_orders(
        RestaurantUser(owner_id), db, response, 6, 0
    )
    assert len(rows) == 6
    assert _total_of(response) == n


# ---- /admin/users, /admin/orders ----


def test_admin_users_returns_only_the_requested_page(paged_platform):
    db = paged_platform["db"]
    response = Response()
    rows = admin_router.list_users(AdminUser(), db, response, 4, 0)
    assert len(rows) == 4
    # The admin table is the whole platform -- seeded demo users plus the fixture
    # -- so the header has to describe all of them, not just the page.
    platform_total = db.query(User).count()
    assert _total_of(response) == platform_total
    assert platform_total > len(rows)


def test_admin_orders_returns_only_the_requested_page(paged_platform):
    db, n = paged_platform["db"], paged_platform["n"]
    response = Response()
    rows = admin_router.all_orders(AdminUser(), db, response, 5, 0)
    assert len(rows) == 5
    assert _total_of(response) >= n


# ---- /restaurants ----


def test_restaurant_listing_returns_only_the_requested_page(paged_platform):
    db, restaurant_ids = (
        paged_platform["db"],
        paged_platform["restaurant_ids"],
    )
    response = Response()
    rows = restaurants_router.list_restaurants(
        cuisine=None,
        q=None,
        city=None,
        lat=None,
        lng=None,
        db=db,
        response=response,
        limit=7,
        offset=0,
    )
    assert len(rows) == 7
    # The catalogue is public and unfiltered here, so the header counts the
    # whole table -- seeded demo restaurants plus the fixture's.
    platform_total = db.query(Restaurant).count()
    assert _total_of(response) == platform_total
    assert platform_total > len(rows)


def test_restaurant_listing_pages_never_repeat_a_row_on_a_rating_tie(paged_platform):
    """Equal ratings must still produce a total order, or paging skips rows.

    Ordering by rating alone leaves ties in whatever order the database feels
    like, so two pages could each return the same restaurant and silently drop
    another. The fixture's restaurants all share the default rating, so this
    fails against an un-tiebroken sort.
    """
    db = paged_platform["db"]
    seen = []
    for offset in range(0, paged_platform["n"], 5):
        response = Response()
        rows = restaurants_router.list_restaurants(
            cuisine=None,
            q=None,
            city=None,
            lat=None,
            lng=None,
            db=db,
            response=response,
            limit=5,
            offset=offset,
        )
        seen.extend(row["id"] for row in rows)
    assert len(seen) == len(set(seen)), f"a row repeated across pages: {seen}"
    assert len(seen) == paged_platform["n"]


def test_restaurant_listing_pages_stay_within_the_filter(paged_platform):
    db, restaurant_ids = (
        paged_platform["db"],
        paged_platform["restaurant_ids"],
    )
    response = Response()
    rows = restaurants_router.list_restaurants(
        cuisine="test",
        q=None,
        city="Chennai",
        lat=None,
        lng=None,
        db=db,
        response=response,
        limit=6,
        offset=0,
    )
    listed = {row["id"] for row in rows}
    assert listed <= set(restaurant_ids)
    # Both filters applied, so the count is of the filtered set, not the table.
    assert _total_of(response) == len(restaurant_ids)


# ---- reviews ----


def test_public_review_list_returns_only_the_requested_page(paged_platform):
    db, restaurant_ids = (
        paged_platform["db"],
        paged_platform["restaurant_ids"],
    )
    response = Response()
    rows = reviews_router.list_reviews(
        restaurant_ids[0], db, response, 1, 0
    )
    assert len(rows) == 1
    assert _total_of(response) == 1


def test_owner_review_list_returns_only_the_requested_page(paged_platform):
    db, n, owner_id = (
        paged_platform["db"],
        paged_platform["n"],
        paged_platform["owner_id"],
    )
    response = Response()
    owner = RestaurantUser(owner_id)
    owner.restaurants = (
        db.query(Restaurant).filter(Restaurant.user_id == owner_id).all()
    )
    rows = reviews_router.my_restaurant_reviews(owner, db, response, 9, 0)
    assert len(rows) == 9
    assert _total_of(response) == n


def test_owner_review_list_reports_zero_when_the_owner_has_no_restaurants(
    paged_platform,
):
    """An owner with no restaurants still needs a header, or the UI cannot tell
    'no reviews yet' from 'the request failed'."""
    db = paged_platform["db"]
    response = Response()
    owner = RestaurantUser(paged_platform["customer_id"])
    owner.restaurants = []
    assert reviews_router.my_restaurant_reviews(owner, db, response) == []
    assert _total_of(response) == 0


# ---- bounds ----


@pytest.mark.parametrize(
    "limit, offset", [(0, 0), (-1, 0), (MAX_LIMIT + 1, 0), (10, -1)]
)
def test_out_of_range_paging_is_rejected(paged_platform, limit, offset):
    """A limit or offset outside its range is a 422, not a silently clamped row.

    Clamping would let a caller believe they asked for the last 20 rows and
    silently receive something else.
    """
    db, customer_id = paged_platform["db"], paged_platform["customer_id"]
    with pytest.raises(HTTPException) as exc:
        orders_router.my_orders(
            CustomerUser(customer_id), db, Response(), limit, offset
        )
    assert exc.value.status_code == 422


def test_paging_rejects_a_limit_that_would_ask_for_the_whole_table(paged_platform):
    db, customer_id = paged_platform["db"], paged_platform["customer_id"]
    with pytest.raises(HTTPException) as exc:
        orders_router.my_orders(
            CustomerUser(customer_id), db, Response(), 10**6, 0
        )
    assert exc.value.status_code == 422
    assert str(MAX_LIMIT) in exc.value.detail