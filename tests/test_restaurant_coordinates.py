"""Restaurant coordinate resolution tests.

A restaurant's lat/lng drive routing, ETA and driver payouts. A restaurant
created through the API used to be stored with no coordinates at all, because
RestaurantCreate had no such fields, so every delivery from it fell back to the
demo home: misrouted, and billed to the driver at the distance cap.

POST /admin/restaurants now resolves a position from an explicit pair or a known
city and refuses to create a restaurant it cannot place.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import tracking
from backend.routers.admin import create_restaurant
from backend.schemas import RestaurantCreate
from backend.tracking_state import resolve_restaurant_coordinates


class AdminUser:
    id = 1
    role = "admin"


@pytest.fixture
def owner_id(db):
    """A restaurant-role user to own the rows created below.

    ``restaurants.user_id`` is NOT NULL, but POST /admin/restaurants lets
    ``user_id`` be omitted -- so at HEAD, omitting it raised an IntegrityError
    instead of a 400. These tests create with an owner; the ownerless path is
    covered on its own below.
    """
    from backend.models import Restaurant, User

    owner = User(
        email="coord_owner@example.com",
        name="CoordOwner",
        password_hash="x",
        role="restaurant",
    )
    db.add(owner)
    db.flush()
    yield owner.id
    # Not wrapped in a bare except on purpose: this row carries a non-Argon2id
    # password_hash, and a silently failed cleanup leaves it behind for
    # test_seeded_passwords_are_argon2id to trip over later in the run.
    try:
        db.query(Restaurant).filter(Restaurant.user_id == owner.id).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id == owner.id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_explicit_coordinates_win():
    """lat/lng is the only precise answer, so it is never overridden."""
    city, point = resolve_restaurant_coordinates(
        "Mumbai", lat=19.1, lng=72.8
    )
    assert point == (19.1, 72.8)
    assert city == "Mumbai"


def test_known_city_resolves_to_its_centre():
    assert resolve_restaurant_coordinates("Pune") == (
        "Pune",
        tracking.CITY_CENTERS["Pune"],
    )


def test_city_matching_ignores_case_and_surrounding_whitespace():
    """A typo in case or padding should not put a kitchen in the wrong state."""
    for written in ("pune", "  PUNE  ", "PuNe"):
        assert resolve_restaurant_coordinates(written)[1] == tracking.CITY_CENTERS["Pune"]


def test_unknown_city_resolves_to_nothing_rather_than_a_wrong_place():
    """Silently defaulting to Bengaluru would misroute in a way nobody sees.

    Resolving to nothing lets the caller reject the create.
    """
    assert resolve_restaurant_coordinates("Atlantis") == ("Atlantis", None)
    assert resolve_restaurant_coordinates(None) == (None, None)


def test_every_known_city_resolves_to_a_point_inside_india():
    """The table is the app's own; a bad entry would misroute every order."""
    for city, (lat, lng) in tracking.CITY_CENTERS.items():
        assert 6.0 <= lat <= 36.0, f"{city} latitude {lat} is outside India"
        assert 68.0 <= lng <= 98.0, f"{city} longitude {lng} is outside India"


def test_half_a_coordinate_is_rejected():
    """A point with only a latitude cannot be placed on a map."""
    with pytest.raises(ValueError, match="must be given together"):
        RestaurantCreate(
            name="Half", address="a", cuisine="test", lat=12.97
        )
    with pytest.raises(ValueError, match="must be given together"):
        RestaurantCreate(
            name="Half", address="a", cuisine="test", lng=77.59
        )


def test_out_of_range_coordinates_are_rejected():
    with pytest.raises(ValueError):
        RestaurantCreate(name="Bad", address="a", cuisine="test", lat=91.0, lng=77.0)
    with pytest.raises(ValueError):
        RestaurantCreate(name="Bad", address="a", cuisine="test", lat=12.0, lng=181.0)


def test_creating_a_restaurant_without_a_position_is_refused(db, owner_id):
    """The point of the change: no restaurant is stored that cannot be routed.

    This is the case that used to succeed and leave NULL columns behind.
    """
    with pytest.raises(HTTPException) as excinfo:
        create_restaurant(
            RestaurantCreate(
                name="Nowhere", address="a", cuisine="test", user_id=owner_id
            ),
            AdminUser(),
            db,
        )
    assert excinfo.value.status_code == 400
    assert "Bengaluru" in excinfo.value.detail, (
        "the error should list the cities that do resolve"
    )

    db.rollback()
    from backend.models import Restaurant

    assert (
        db.query(Restaurant).filter(Restaurant.name == "Nowhere").count() == 0
    ), "a refused create must not leave a row behind"


def test_creating_a_restaurant_with_an_unknown_city_is_refused(db, owner_id):
    with pytest.raises(HTTPException) as excinfo:
        create_restaurant(
            RestaurantCreate(
                name="Typo", address="a", cuisine="test", city="Puni", user_id=owner_id
            ),
            AdminUser(),
            db,
        )
    assert excinfo.value.status_code == 400
    db.rollback()


def test_created_restaurant_is_stored_with_its_position(db, owner_id):
    """The created row carries the resolved city and point, not NULLs."""
    from backend.models import Restaurant

    payload = RestaurantCreate(
        name="Coordinate Cafe",
        address="a",
        cuisine="test",
        city="kolkata",
        user_id=owner_id,
    )
    created = create_restaurant(payload, AdminUser(), db)
    try:
        row = db.query(Restaurant).filter(Restaurant.id == created["id"]).one()
        assert row.city == "Kolkata"
        assert (row.lat, row.lng) == tracking.CITY_CENTERS["Kolkata"]

        # And the value the routing path reads is this one, not the demo home.
        from backend.tracking_state import restaurant_start

        class FakeOrder:
            restaurant = row
            restaurant_id = row.id

        assert restaurant_start(FakeOrder()) == tracking.CITY_CENTERS["Kolkata"]
    finally:
        db.query(Restaurant).filter(Restaurant.id == created["id"]).delete(
            synchronize_session=False
        )
        db.commit()


def test_created_restaurant_keeps_explicit_coordinates_verbatim(db, owner_id):
    from backend.models import Restaurant

    payload = RestaurantCreate(
        name="Pin Drop",
        address="a",
        cuisine="test",
        lat=15.4,
        lng=75.8,
        user_id=owner_id,
    )
    created = create_restaurant(payload, AdminUser(), db)
    try:
        row = db.query(Restaurant).filter(Restaurant.id == created["id"]).one()
        assert (row.lat, row.lng) == (15.4, 75.8)
        assert row.city is None
    finally:
        db.query(Restaurant).filter(Restaurant.id == created["id"]).delete(
            synchronize_session=False
        )
        db.commit()

def test_creating_a_restaurant_without_an_owner_is_a_400(db):
    """A bad request should not reach the INSERT and come back a 500.

    ``restaurants.user_id`` is NOT NULL, and ``RestaurantCreate.user_id`` is
    optional, so omitting it used to raise IntegrityError from the flush.
    """
    with pytest.raises(HTTPException) as excinfo:
        create_restaurant(
            RestaurantCreate(name="Orphan", address="a", cuisine="test", city="Pune"),
            AdminUser(),
            db,
        )
    assert excinfo.value.status_code == 400
    assert "user_id" in excinfo.value.detail

    db.rollback()
    from backend.models import Restaurant

    assert db.query(Restaurant).filter(Restaurant.name == "Orphan").count() == 0


def test_a_non_restaurant_user_cannot_own_a_restaurant(db):
    """The owner must hold the restaurant role, or they cannot receive orders."""
    from backend.models import User

    customer = User(
        email="coord_cust@example.com",
        name="CoordCust",
        password_hash="x",
        role="customer",
    )
    db.add(customer)
    db.flush()
    customer_id = customer.id
    try:
        with pytest.raises(HTTPException) as excinfo:
            create_restaurant(
                RestaurantCreate(
                    name="WrongOwner",
                    address="a",
                    cuisine="test",
                    city="Pune",
                    user_id=customer_id,
                ),
                AdminUser(),
                db,
            )
        assert excinfo.value.status_code == 400
        db.rollback()
    finally:
        db.query(User).filter(User.id == customer_id).delete(synchronize_session=False)
        db.commit()
