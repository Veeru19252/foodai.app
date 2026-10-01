"""
End-to-end API tests against the isolated foodai_test database.
Covers auth, catalog, orders + promos, assignment, tracking, ML, and
role-based access control.
"""

import eta_service

from tests.conftest import login, verify_phone


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_login_seeded_user(client):
    data = login(client, "customer@foodai.com")
    assert data["user"]["email"] == "customer@foodai.com"
    assert data["user"]["role"] == "customer"
    assert data["access_token"]


def test_register_unique_user(client):
    resp = client.post(
        "/auth/register",
        json={"name": "Test User", "email": "test-user@example.com", "password": "password123", "role": "customer"},
    )
    assert resp.status_code == 201
    assert resp.json()["user"]["email"] == "test-user@example.com"


def test_register_duplicate_email(client):
    resp = client.post(
        "/auth/register",
        json={"name": "Dup", "email": "customer@foodai.com", "password": "password123", "role": "customer"},
    )
    assert resp.status_code == 409


def test_register_cannot_escalate_to_admin(client):
    """Public registration must never mint a privileged account.

    Regression test: the register endpoint used to trust `role` from the request
    body, so an anonymous caller could create an admin and read every
    admin-only endpoint. Admin access must come from seeding or from an
    authenticated admin promoting a user, never from the signup form.
    """
    resp = client.post(
        "/auth/register",
        json={"name": "Escalator", "email": "escalator@example.com", "password": "password123", "role": "admin"},
    )
    assert resp.status_code == 403

    # No account may have been created by the rejected request...
    assert client.post(
        "/auth/login", json={"email": "escalator@example.com", "password": "password123"}
    ).status_code == 401

    # ...and the rejected role must not work on any other privileged role.
    for role in ("admin",):
        resp = client.post(
            "/auth/register",
            json={"name": f"Esc {role}", "email": f"esc-{role}@example.com", "password": "password123", "role": role},
        )
        assert resp.status_code == 403, f"role={role} was not rejected"


def test_register_allows_legitimate_partner_roles(client):
    """Restaurant and delivery partners are legitimate self-registrants."""
    for role in ("customer", "restaurant", "delivery"):
        resp = client.post(
            "/auth/register",
            json={"name": f"Partner {role}", "email": f"partner-{role}@example.com", "password": "password123", "role": role},
        )
        assert resp.status_code == 201, f"role={role} should be allowed"
        assert resp.json()["user"]["role"] == role


def test_register_rejects_unknown_role(client):
    resp = client.post(
        "/auth/register",
        json={"name": "Bogus", "email": "bogus@example.com", "password": "password123", "role": "superadmin"},
    )
    assert resp.status_code == 403


def test_login_wrong_password(client):
    resp = client.post("/auth/login", json={"email": "customer@foodai.com", "password": "nope"})
    assert resp.status_code == 401


def test_me(client):
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "customer"


def test_list_restaurants(client):
    resp = client.get("/restaurants")
    assert resp.status_code == 200
    names = [r["name"] for r in resp.json()]
    assert "Spice Garden" in names


def test_cuisine_filter(client):
    resp = client.get("/restaurants?cuisine=Chinese")
    names = [r["name"] for r in resp.json()]
    assert names == ["Wok This Way"]


def test_city_filter(client):
    resp = client.get("/restaurants?city=Bengaluru")
    assert resp.status_code == 200
    body = resp.json()
    assert body
    assert all(r["city"] == "Bengaluru" for r in body)
    # Case-insensitive: same restaurants either way.
    lower = client.get("/restaurants?city=bengaluru").json()
    assert [r["id"] for r in lower] == [r["id"] for r in body]


def test_city_filter_combined_with_cuisine(client):
    resp = client.get("/restaurants?city=Bengaluru&cuisine=Chinese")
    names = [r["name"] for r in resp.json()]
    assert names == ["Wok This Way"]


def test_lat_lng_returns_distance_eta_sorted(client):
    # Demo home near Indiranagar; Bengaluru spots must rank ahead of the
    # rest of India by straight-line distance.
    resp = client.get("/restaurants?lat=12.9719&lng=77.6412")
    assert resp.status_code == 200
    body = resp.json()
    assert body
    for r in body:
        assert r["distance_km"] is not None and r["distance_km"] >= 0
        assert r["eta_min"] is not None and r["eta_min"] > 0
    distances = [r["distance_km"] for r in body]
    assert distances == sorted(distances)
    assert body[0]["city"] == "Bengaluru"


def test_no_lat_lng_keeps_null_geo_fields(client):
    resp = client.get("/restaurants")
    assert resp.status_code == 200
    for r in resp.json():
        assert r["distance_km"] is None
        assert r["eta_min"] is None


def test_invalid_lat_lng_rejected_422(client):
    assert client.get("/restaurants?lat=95&lng=77").status_code == 422
    assert client.get("/restaurants?lat=12&lng=200").status_code == 422
    assert client.get("/restaurants?lat=abc&lng=77").status_code == 422


def test_restaurants_cities_endpoint(client):
    resp = client.get("/restaurants/cities")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"cities"}
    cities = body["cities"]
    assert cities == sorted(cities)
    assert "Bengaluru" in cities


def test_menu_for_restaurant(client):
    resp = client.get("/restaurants/1/menu")
    assert resp.status_code == 200
    assert any(m["name"] == "Paneer Butter Masala" for m in resp.json())


def test_menu_unknown_restaurant_404(client):
    assert client.get("/restaurants/9999/menu").status_code == 404


def test_create_order_with_promo(client):
    token = login(client, "customer@foodai.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/orders",
        json=_gate(
            client,
            restaurant_id=1,
            items=[{"menu_item_id": 1, "quantity": 2}, {"menu_item_id": 5, "quantity": 1}],
            coupon_code="WELCOME10",
        ),
        headers=headers,
    )
    assert resp.status_code == 201
    order = resp.json()
    # 2 * 220 + 200 = 640; WELCOME10 = 10% capped at 50 -> food subtotal 590.
    # The delivery fee is surge-dependent (₹25 base, up to ₹37.5), so the
    # total is asserted against the fee the server actually charged.
    assert order["discount_amount"] == 50.0
    assert 25.0 <= order["delivery_fee"] <= 37.5
    assert order["total"] == round(590.0 + order["delivery_fee"], 2)
    assert order["status"] == "PLACED"
    assert len(order["items"]) == 2
    return order["id"], token


def test_promo_validate(client):
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.post(
        "/orders/promo/validate",
        json={"code": "WELCOME10", "order_total": 640},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "message": "Promo code applied!", "discount": 50.0}


def test_promo_rejected_below_min(client):
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.post(
        "/orders/promo/validate",
        json={"code": "FLAT50", "order_total": 50},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_order_rejects_price_fraud(client):
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.post(
        "/orders",
        json=_gate(
            client,
            restaurant_id=1,
            items=[{"menu_item_id": 9999, "quantity": 1}],
        ),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_restaurant_full_lifecycle(client):
    order_id, customer_token = test_create_order_with_promo(client)
    rest_token = login(client, "spice@foodai.com")["access_token"]

    # Restaurant sees the order
    resp = client.get("/orders/restaurant", headers={"Authorization": f"Bearer {rest_token}"})
    assert resp.status_code == 200
    assert any(o["id"] == order_id for o in resp.json())

    # Drivers available
    resp = client.get("/orders/drivers", headers={"Authorization": f"Bearer {rest_token}"})
    assert resp.status_code == 200
    driver = resp.json()[0]

    # Assign delivery
    resp = client.post(
        f"/orders/{order_id}/assign",
        json={"driver_id": driver["id"]},
        headers={"Authorization": f"Bearer {rest_token}"},
    )
    assert resp.status_code == 200

    # Start delivery stamps pickup_time
    _dispatch(client, order_id, rest_token)
    return order_id, driver, customer_token, rest_token


def test_customer_cannot_confirm_order(client):
    """A customer may not drive the order into CONFIRMED.

    Uses a freshly created order rather than a hardcoded id: the route checks
    the lifecycle transition *before* the actor's role, so an order that is no
    longer in PLACED would answer 400 instead of 403 and the test would pass or
    fail for the wrong reason.
    """
    order_ids, _headers = test_create_batch_order(client)
    order_id = order_ids[0]
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.patch(
        f"/orders/{order_id}/status",
        json={"status": "CONFIRMED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text
    # And the order was not actually moved.
    rest_token = login(client, "spice@foodai.com")["access_token"]
    detail = client.get(
        f"/orders/{order_id}", headers={"Authorization": f"Bearer {rest_token}"}
    )
    assert detail.json()["status"] == "PLACED"


def test_tracking_access_control(client):
    order_id, driver, _cust, _rest = test_restaurant_full_lifecycle(client)

    # Assigned driver can track
    driver_token = login(client, driver["email"])["access_token"]
    resp = client.get(f"/tracking/{order_id}", headers={"Authorization": f"Bearer {driver_token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OUT_FOR_DELIVERY"
    assert body["route_distance_km"] > 0
    assert len(body["route"]) > 0

    # A different driver is denied
    other_token = login(client, "rider@foodai.com")["access_token"]
    resp = client.get(f"/tracking/{order_id}", headers={"Authorization": f"Bearer {other_token}"})
    assert resp.status_code == 403


def test_ml_eta(client):
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.get(
        "/ml/eta?restaurant_id=1&distance_km=5&prep_time_min=15",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["eta_min"] is not None
    # If the model file is present locally, the ML path must be used.
    if eta_service.load_model() is not None:
        assert body["fallback"] is False


def test_ml_forecast(client):
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.get("/ml/forecast", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["zones"]) == {"A", "B", "C", "D", "E"}


def test_ml_explain(client):
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.post(
        "/ml/eta/explain?restaurant_id=1&distance_km=5&prep_time_min=15",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    if not body["fallback"]:
        assert len(body["explanation"]["contributions"]) == 11


def test_ml_forecast_series(client):
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.get(
        "/ml/forecast/series?hours=3",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["series"]) == 3
    for item in body["series"]:
        assert "label" in item
        assert set(item["zones"]) == {"A", "B", "C", "D", "E"}


def test_ml_recommendations(client):
    # customer@foodai.com has order history by this point -> real scores.
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.get("/ml/recommendations", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback"] is False
    assert 1 <= len(body["recommendations"]) <= 4
    rec = body["recommendations"][0]
    assert rec["name"]
    assert rec["reason"]
    assert "score" in rec

    # A brand-new customer without orders degrades to fallback.
    new_token = login(client, "test-user@example.com")["access_token"]
    resp = client.get(
        "/ml/recommendations", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["fallback"] is True

    # Owner accounts are not customers.
    owner_token = login(client, "spice@foodai.com")["access_token"]
    resp = client.get(
        "/ml/recommendations", headers={"Authorization": f"Bearer {owner_token}"}
    )
    assert resp.status_code == 403


def test_item_recommendations(client):
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.get(
        "/ml/recommendations/items?restaurant_id=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) <= 5
    assert "fallback" in body
    for item in body["items"]:
        assert item["name"]
        assert "score" in item


def test_reorder_order(client):
    token = login(client, "customer@foodai.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/orders",
        json=_gate(client, restaurant_id=1, items=[{"menu_item_id": 1, "quantity": 2}]),
        headers=headers,
    )
    assert resp.status_code == 201
    source_id = resp.json()["id"]

    resp = client.post(f"/orders/{source_id}/reorder", headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["restaurant_id"] == 1
    assert body["status"] == "PLACED"
    assert body["items"][0]["quantity"] == 2
    assert body["total"] > 0

    # Reordering someone else's order is forbidden.
    other = login(client, "test-user@example.com")["access_token"]
    resp = client.post(
        f"/orders/{source_id}/reorder",
        headers={"Authorization": f"Bearer {other}"},
    )
    assert resp.status_code == 403


def test_addresses_crud(client):
    token = login(client, "customer@foodai.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/addresses", headers=headers)
    assert resp.status_code == 200

    resp = client.post(
        "/addresses",
        json={"label": "Home", "address": "12 MG Road", "lat": 12.97, "lng": 77.59},
        headers=headers,
    )
    assert resp.status_code == 201
    addr = resp.json()
    assert addr["label"] == "Home"

    resp = client.get("/addresses", headers=headers)
    assert any(a["id"] == addr["id"] for a in resp.json())

    # Deleting someone else's address is forbidden.
    other = login(client, "test-user@example.com")["access_token"]
    resp = client.delete(
        f"/addresses/{addr['id']}",
        headers={"Authorization": f"Bearer {other}"},
    )
    assert resp.status_code == 403

    resp = client.delete(f"/addresses/{addr['id']}", headers=headers)
    assert resp.status_code == 200


def test_admin_role_update(client):
    admin_token = login(client, "admin@foodai.com")["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # test-user@example.com is a customer by default.
    resp = client.get("/admin/users", headers=headers)
    users = {u["email"]: u for u in resp.json()}
    target_id = users["test-user@example.com"]["id"]

    resp = client.patch(
        f"/admin/users/{target_id}/role",
        json={"role": "delivery"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "delivery"

    resp = client.patch(
        f"/admin/users/{target_id}/role",
        json={"role": "customer"},
        headers=headers,
    )
    assert resp.status_code == 200

    # Invalid roles and non-admins are rejected.
    resp = client.patch(
        f"/admin/users/{target_id}/role",
        json={"role": "superuser"},
        headers=headers,
    )
    assert resp.status_code == 400

    customer_token = login(client, "customer@foodai.com")["access_token"]
    resp = client.patch(
        f"/admin/users/{target_id}/role",
        json={"role": "delivery"},
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp.status_code == 403


def test_auto_assign(client):
    customer_token = login(client, "customer@foodai.com")["access_token"]
    customer_headers = {"Authorization": f"Bearer {customer_token}"}
    resp = client.post(
        "/orders",
        json=_gate(client, restaurant_id=1, items=[{"menu_item_id": 2, "quantity": 1}]),
        headers=customer_headers,
    )
    order_id = resp.json()["id"]

    owner_token = login(client, "spice@foodai.com")["access_token"]
    resp = client.post(
        f"/orders/{order_id}/auto-assign",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["delivery_id"]
    assert body["driver_name"]
    assert "Lowest load" in body["reason"]

    # Already assigned -> idempotent.
    resp = client.post(
        f"/orders/{order_id}/auto-assign",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["delivery_id"] == body["delivery_id"]

    # A customer cannot trigger auto-dispatch.
    resp = client.post(
        f"/orders/{order_id}/auto-assign",
        headers=customer_headers,
    )
    assert resp.status_code == 403


def test_order_nudge(client):
    customer_token = login(client, "customer@foodai.com")["access_token"]
    customer_headers = {"Authorization": f"Bearer {customer_token}"}
    resp = client.post(
        "/orders",
        json=_gate(client, restaurant_id=2, items=[{"menu_item_id": 6, "quantity": 1}]),
        headers=customer_headers,
    )
    order_id = resp.json()["id"]

    owner_token = login(client, "dosa@foodai.com")["access_token"]
    resp = client.get(
        f"/orders/{order_id}/nudge",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk"] in ("LOW", "MEDIUM", "HIGH")
    assert "message" in body
    assert body["eta_min"] is None or body["eta_min"] >= 0

    # The customer cannot view the nudge (restaurant-side feature).
    resp = client.get(
        f"/orders/{order_id}/nudge",
        headers=customer_headers,
    )
    assert resp.status_code == 403


def test_driver_earnings(client):
    token = login(client, "rider@foodai.com")["access_token"]
    resp = client.get(
        "/orders/driver/earnings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_earnings"] >= 0
    assert body["total_deliveries"] >= 0
    assert body["completed_deliveries"] >= 0
    assert body["per_delivery_rate"] == 60.0
    assert body["per_km_rate"] == 12.0
    assert isinstance(body["recent"], list)

    # A customer cannot read driver earnings.
    customer_token = login(client, "customer@foodai.com")["access_token"]
    resp = client.get(
        "/orders/driver/earnings",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp.status_code == 403


def test_driver_earnings_distance_is_capped(client):
    """A far-away delivery point cannot inflate the driver's payout."""
    from datetime import datetime

    from backend.db import SessionLocal
    from backend.models import Delivery, Order
    from backend.routers.orders import (
        MAX_EARNINGS_DISTANCE_KM,
        PER_DELIVERY_RATE,
        PER_KM_RATE,
    )

    # ~500 km from the restaurant: far beyond any real delivery.
    gate = _gate(
        client,
        delivery_lat=17.0,
        delivery_lng=78.0,
        location_confirm_lat=17.0,
        location_confirm_lng=78.0,
    )
    resp = client.post(
        "/orders",
        json={"restaurant_id": 1, "items": [_line(1, 1)], **gate},
        headers=_customer_headers(client),
    )
    assert resp.status_code == 201, resp.text
    order_id = resp.json()["id"]

    rest_token = login(client, "spice@foodai.com")["access_token"]
    drivers = client.get(
        "/orders/drivers", headers={"Authorization": f"Bearer {rest_token}"}
    ).json()
    driver = next(d for d in drivers if d["email"] == "rider@foodai.com")
    client.post(
        f"/orders/{order_id}/assign",
        json={"driver_id": driver["id"]},
        headers={"Authorization": f"Bearer {rest_token}"},
    )

    db = SessionLocal()
    try:
        d = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        d.delivered_time = datetime.utcnow()
        db.query(Order).filter(Order.id == order_id).update({"status": "DELIVERED"})
        db.commit()
    finally:
        db.close()

    driver_token = login(client, "rider@foodai.com")["access_token"]
    body = client.get(
        "/orders/driver/earnings",
        headers={"Authorization": f"Bearer {driver_token}"},
    ).json()
    row = next(r for r in body["recent"] if r["order_id"] == order_id)
    assert row["distance_km"] == MAX_EARNINGS_DISTANCE_KM
    assert row["earned"] == round(
        PER_DELIVERY_RATE + PER_KM_RATE * MAX_EARNINGS_DISTANCE_KM, 2
    )


def test_restaurant_menu_management(client):
    owner_token = login(client, "spice@foodai.com")["access_token"]
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    resp = client.get("/restaurants/me", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Spice Garden"

    resp = client.post(
        "/restaurants/me/menu",
        json={"name": "Choco Lava Cake", "price": 120, "prep_time_min": 10},
        headers=owner_headers,
    )
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    resp = client.patch(
        f"/restaurants/me/menu/{item_id}",
        json={"price": 130},
        headers=owner_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["price"] == 130.0

    # Another restaurant owner cannot touch this item.
    other_token = login(client, "dosa@foodai.com")["access_token"]
    resp = client.patch(
        f"/restaurants/me/menu/{item_id}",
        json={"price": 1},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 404

    resp = client.delete(
        f"/restaurants/me/menu/{item_id}",
        headers=owner_headers,
    )
    assert resp.status_code == 200


def test_restaurant_offers(client):
    owner_token = login(client, "spice@foodai.com")["access_token"]
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    resp = client.post(
        "/restaurants/me/offers",
        json={
            "code": "SPICE20",
            "description": "20% off at Spice Garden",
            "discount_type": "percent",
            "discount_value": 20,
            "min_order_value": 150,
            "max_discount": 60,
        },
        headers=owner_headers,
    )
    assert resp.status_code == 201
    offer = resp.json()
    assert offer["code"] == "SPICE20"
    assert offer["scope"] == "restaurant"
    assert offer["active"] is True

    resp = client.get("/restaurants/me/offers", headers=owner_headers)
    codes = [o["code"] for o in resp.json()]
    assert "SPICE20" in codes
    assert "WELCOME10" in codes  # platform offers show too

    resp = client.patch(
        f"/restaurants/me/offers/{offer['id']}/toggle",
        headers=owner_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    # Only the owning restaurant can toggle it.
    other_token = login(client, "dosa@foodai.com")["access_token"]
    resp = client.patch(
        f"/restaurants/me/offers/{offer['id']}/toggle",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 404


def test_restaurant_analytics(client):
    owner_token = login(client, "spice@foodai.com")["access_token"]
    resp = client.get(
        "/restaurants/me/analytics",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["restaurant_name"] == "Spice Garden"
    assert body["total_orders"] >= 0
    assert body["revenue"] >= 0
    assert isinstance(body["orders_by_status"], dict)
    assert isinstance(body["popular_items"], list)
    assert body["orders_last_7_days"] >= 0
    assert "avg_rating" in body
    assert "review_count" in body

    # A customer cannot access restaurant analytics.
    customer_token = login(client, "customer@foodai.com")["access_token"]
    resp = client.get(
        "/restaurants/me/analytics",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp.status_code == 403


def test_tracking_includes_timeline(client):
    token = login(client, "customer@foodai.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/orders",
        json=_gate(client, restaurant_id=2, items=[{"menu_item_id": 6, "quantity": 1}]),
        headers=headers,
    )
    order_id = resp.json()["id"]
    resp = client.get(f"/tracking/{order_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "created_at" in body
    assert "pickup_time" in body
    assert "delivered_time" in body



def test_admin_overview_guarded(client):
    token = login(client, "customer@foodai.com")["access_token"]
    assert client.get("/admin/overview", headers={"Authorization": f"Bearer {token}"}).status_code == 403

    admin_token = login(client, "admin@foodai.com")["access_token"]
    resp = client.get("/admin/overview", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["users"]["admin"] == 1
    assert body["restaurants"] == 15


def test_unauthenticated_requests_rejected(client):
    assert client.get("/orders").status_code == 401
    assert client.get("/tracking/1").status_code == 401
    assert client.get("/ml/eta?restaurant_id=1").status_code == 401


def _customer_headers(client):
    token = login(client, "customer@foodai.com")["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _line(menu_item_id, quantity):
    return {"menu_item_id": menu_item_id, "quantity": quantity}


def _advance(client, order_id, rest_token, statuses):
    """Patch an order through `statuses`, asserting each one succeeds."""
    headers = {"Authorization": f"Bearer {rest_token}"}
    body = None
    for status in statuses:
        resp = client.patch(
            f"/orders/{order_id}/status", json={"status": status}, headers=headers
        )
        assert resp.status_code == 200, f"{status}: {resp.text}"
        body = resp.json()
    return body


def _prepare(client, order_id, rest_token):
    """Walk an order to PREPARING, leaving dispatch as the only step left."""
    return _advance(client, order_id, rest_token, ("CONFIRMED", "PREPARING"))


def _dispatch(client, order_id, rest_token):
    """Walk an order along the strict lifecycle to OUT_FOR_DELIVERY.

    The graph has no skip-ahead edges, so a test that wants an order in
    transit has to confirm and prepare it first, exactly as the restaurant
    UI does. Returns the final status response body.
    """
    return _advance(
        client, order_id, rest_token, ("CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY")
    )


def _gate(client, **overrides):
    """Order payload with the pre-order verification gate satisfied.

    Requests + verifies an OTP for a fresh phone number and returns the base
    delivery/confirmation fields every order needs. Extra kwargs override.
    """
    verified = verify_phone(client)
    payload = {
        "delivery_phone": verified["phone"],
        "otp_token": verified["otp_token"],
        "location_confirmed": True,
        "location_confirm_lat": 12.9719,
        "location_confirm_lng": 77.6412,
        "delivery_address": "5th Block, Koramangala",
        "delivery_lat": 12.9719,
        "delivery_lng": 77.6412,
    }
    payload.update(overrides)
    return payload


# ---- Phase 3: batch orders ----

def test_create_batch_order(client):
    headers = _customer_headers(client)
    gate = _gate(client)
    resp = client.post(
        "/orders/batch",
        json={
            "orders": [
                {
                    "restaurant_id": 1,
                    "items": [_line(1, 2)],
                    "coupon_code": "WELCOME10",
                    **gate,
                },
                {
                    "restaurant_id": 2,
                    "items": [_line(8, 1)],
                    **gate,
                },
            ]
        },
        headers=headers,
    )
    assert resp.status_code == 201
    orders = resp.json()["orders"]
    assert len(orders) == 2
    # Restaurant 1: 2 * 220 = 440; WELCOME10 = 10% (44, below cap 50) -> 396.
    # The delivery fee is surge-dependent (₹25 base, up to ₹37.5) and is only
    # charged on the first (primary) batch order.
    assert orders[0]["restaurant_id"] == 1
    assert 25.0 <= orders[0]["delivery_fee"] <= 37.5
    assert orders[0]["total"] == round(396.0 + orders[0]["delivery_fee"], 2)
    # Secondary restaurant in the batch: no extra delivery fee.
    assert orders[1]["restaurant_id"] == 2
    assert orders[1]["delivery_fee"] == 0.0
    return [o["id"] for o in orders], headers


def test_batch_order_empty_rejected(client):
    resp = client.post(
        "/orders/batch", json={"orders": []}, headers=_customer_headers(client)
    )
    assert resp.status_code == 422


# ---- Phase: phone OTP verification gate ----

def test_otp_request_and_verify(client):
    token = login(client, "customer@foodai.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/auth/otp/request", json={"phone": "9876500001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["test_mode"] is True
    code = body["dev_code"]
    assert len(code) == 6

    resp = client.post(
        "/auth/otp/verify",
        json={"phone": "9876500001", "code": code},
        headers=headers,
    )
    assert resp.status_code == 200
    verified = resp.json()
    assert verified["ok"] is True
    assert verified["phone"] == "9876500001"
    assert verified["otp_token"]

    # Authenticated callers get their freshly-stamped profile back in the
    # same shape as the login/register user payload.
    assert verified["user"] is not None
    assert verified["user"]["phone"] == "9876500001"
    assert verified["user"]["phone_verified_at"] is not None

    # Verifying stamps the customer's profile so checkout can pre-fill.
    me = client.get("/auth/me", headers=headers).json()
    assert me["phone"] == "9876500001"
    assert me["phone_verified_at"] is not None


def test_otp_verify_guest_returns_null_user(client):
    resp = client.post("/auth/otp/request", json={"phone": "9876500006"})
    assert resp.status_code == 200
    code = resp.json()["dev_code"]
    resp = client.post("/auth/otp/verify", json={"phone": "9876500006", "code": code})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["user"] is None


def test_otp_wrong_code_rejected(client):
    resp = client.post("/auth/otp/request", json={"phone": "9876500002"})
    assert resp.status_code == 200
    code = resp.json()["dev_code"]
    wrong = "000000" if code != "000000" else "000001"
    resp = client.post("/auth/otp/verify", json={"phone": "9876500002", "code": wrong})
    assert resp.status_code == 400
    assert "attempt" in resp.json()["detail"].lower()


def test_otp_rejects_invalid_phone(client):
    # 10 digits but starts with 1 (not a valid Indian mobile) -> 400.
    assert client.post("/auth/otp/request", json={"phone": "1234567890"}).status_code == 400
    # Over-long -> 400.
    assert client.post("/auth/otp/request", json={"phone": "98765432109"}).status_code == 400
    # Too short for the schema -> 422.
    assert client.post("/auth/otp/request", json={"phone": "98765"}).status_code == 422


def test_otp_resend_rate_limited(client):
    resp = client.post("/auth/otp/request", json={"phone": "9876500003"})
    assert resp.status_code == 200
    resp = client.post("/auth/otp/request", json={"phone": "9876500003"})
    assert resp.status_code == 429


def test_order_requires_location_confirmation(client):
    resp = client.post(
        "/orders",
        json=_gate(client, restaurant_id=1, items=[_line(1, 1)], location_confirmed=False),
        headers=_customer_headers(client),
    )
    assert resp.status_code == 400
    assert "location" in resp.json()["detail"].lower()


def test_order_requires_otp_token(client):
    resp = client.post(
        "/orders",
        json={
            "restaurant_id": 1,
            "items": [_line(1, 1)],
            "delivery_phone": "9876500004",
            "location_confirmed": True,
        },
        headers=_customer_headers(client),
    )
    assert resp.status_code == 400
    assert "OTP" in resp.json()["detail"]


def test_order_rejects_otp_for_other_phone(client):
    verified = verify_phone(client)
    resp = client.post(
        "/orders",
        json={
            "restaurant_id": 1,
            "items": [_line(1, 1)],
            "delivery_phone": "9876500005",
            "otp_token": verified["otp_token"],
            "location_confirmed": True,
        },
        headers=_customer_headers(client),
    )
    assert resp.status_code == 400
    assert "OTP" in resp.json()["detail"]


# ---- Phase 3: cancel ----

def test_customer_can_cancel_placed_order(client):
    order_id, headers = test_create_batch_order(client)
    resp = client.post(f"/orders/{order_id[0]}/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"


def test_cannot_cancel_after_dispatch(client):
    order_id, driver, _cust, rest_token = test_restaurant_full_lifecycle(client)
    resp = client.post(
        f"/orders/{order_id}/cancel", headers=_customer_headers(client)
    )
    assert resp.status_code == 400


def test_cannot_cancel_other_users_order(client):
    order_id, headers = test_create_batch_order(client)
    other = {"Authorization": "Bearer " + login(client, "test-user@example.com")["access_token"]}
    resp = client.post(f"/orders/{order_id[0]}/cancel", headers=other)
    assert resp.status_code == 403


def test_status_endpoint_refuses_skipped_dispatch(client):
    """A PLACED order cannot jump to OUT_FOR_DELIVERY or DELIVERED.

    The unit tests in test_order_state.py pin the graph; this pins the route,
    so a future handler that assigns `order.status = ...` directly instead of
    routing through `order_state.can_transition` fails here rather than in
    production. The error names the state actually required so the restaurant
    UI can tell the user what to press.
    """
    order_id, _headers = test_create_batch_order(client)
    oid = order_id[0]
    rest_token = login(client, "spice@foodai.com")["access_token"]
    rest_headers = {"Authorization": f"Bearer {rest_token}"}
    driver = client.get("/orders/drivers", headers=rest_headers).json()[0]
    resp = client.post(
        f"/orders/{oid}/assign", json={"driver_id": driver["id"]}, headers=rest_headers
    )
    assert resp.status_code == 200

    for target in ("OUT_FOR_DELIVERY", "DELIVERED"):
        resp = client.patch(
            f"/orders/{oid}/status", json={"status": target}, headers=rest_headers
        )
        assert resp.status_code == 400, f"PLACED -> {target} must be refused: {resp.text}"
        assert "CONFIRMED" in resp.json()["detail"]

    # Confirming is allowed, and the order is still not yet in transit.
    resp = client.patch(
        f"/orders/{oid}/status", json={"status": "CONFIRMED"}, headers=rest_headers
    )
    assert resp.status_code == 200
    resp = client.patch(
        f"/orders/{oid}/status", json={"status": "OUT_FOR_DELIVERY"}, headers=rest_headers
    )
    assert resp.status_code == 400
    assert "PREPARING" in resp.json()["detail"]


# ---- Phase 3: driver starts delivery ----

def test_assigned_driver_can_dispatch(client):
    order_id, driver, _cust, _rest = test_restaurant_full_lifecycle(client)
    # Pick a fresh order and let the assigned driver dispatch it.
    order_id, _h = test_create_batch_order(client)
    order_id = order_id[0]
    rest_token = login(client, "spice@foodai.com")["access_token"]
    _prepare(client, order_id, rest_token)

    driver_token = login(client, driver["email"])["access_token"]
    resp = client.patch(
        f"/orders/{order_id}/status",
        json={"status": "OUT_FOR_DELIVERY"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    # The driver isn't assigned to this new order yet.
    assert resp.status_code == 403

    client.post(
        f"/orders/{order_id}/assign",
        json={"driver_id": driver["id"]},
        headers={"Authorization": f"Bearer {rest_token}"},
    )
    resp = client.patch(
        f"/orders/{order_id}/status",
        json={"status": "OUT_FOR_DELIVERY"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "OUT_FOR_DELIVERY"


def test_unassigned_driver_cannot_dispatch(client):
    order_id, headers = test_create_batch_order(client)
    order_id = order_id[0]
    rest_token = login(client, "spice@foodai.com")["access_token"]
    # Prepare it so dispatch is the only remaining step, isolating the
    # authorization check from the transition graph.
    _prepare(client, order_id, rest_token)
    other_token = login(client, "rider@foodai.com")["access_token"]
    resp = client.patch(
        f"/orders/{order_id}/status",
        json={"status": "OUT_FOR_DELIVERY"},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403


# ---- Phase 3: reviews ----

def _delivered_order_id(client):
    """Create, assign, and dispatch an order, then force delivery via DB."""
    order_id, _headers = test_create_batch_order(client)
    order_id = order_id[0]
    rest_token = login(client, "spice@foodai.com")["access_token"]
    driver = client.get("/orders/drivers", headers={"Authorization": f"Bearer {rest_token}"}).json()[0]
    client.post(f"/orders/{order_id}/assign", json={"driver_id": driver["id"]}, headers={"Authorization": f"Bearer {rest_token}"})
    _dispatch(client, order_id, rest_token)
    # Mark delivered directly so the review gate is reachable without waiting.
    from backend.models import Delivery, Order
    from backend.db import SessionLocal
    from datetime import datetime
    db = SessionLocal()
    try:
        d = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        d.delivered_time = datetime.utcnow()
        db.query(Order).filter(Order.id == order_id).update({"status": "DELIVERED"})
        db.commit()
    finally:
        db.close()
    return order_id


def test_create_review_after_delivery(client):
    order_id = _delivered_order_id(client)
    resp = client.post(
        "/reviews",
        json={"order_id": order_id, "rating": 5, "comment": "Delicious!"},
        headers=_customer_headers(client),
    )
    assert resp.status_code == 201
    assert resp.json()["rating"] == 5
    assert resp.json()["restaurant_id"] == 1


def test_duplicate_review_rejected(client):
    order_id = _delivered_order_id(client)
    headers = _customer_headers(client)
    assert client.post("/reviews", json={"order_id": order_id, "rating": 4}, headers=headers).status_code == 201
    assert client.post("/reviews", json={"order_id": order_id, "rating": 5}, headers=headers).status_code == 400


def test_review_requires_delivered_order(client):
    order_id, headers = test_create_batch_order(client)
    resp = client.post("/reviews", json={"order_id": order_id[0], "rating": 3}, headers=headers)
    assert resp.status_code == 400


def test_restaurant_reviews_and_rating(client):
    order_id = _delivered_order_id(client)
    client.post("/reviews", json={"order_id": order_id, "rating": 5, "comment": "Great"}, headers=_customer_headers(client))

    resp = client.get("/reviews/restaurant/1")
    assert resp.status_code == 200
    assert any(r["rating"] == 5 for r in resp.json())

    resp = client.get("/reviews/restaurant/1/rating")
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_count"] >= 1
    assert body["rating"] is not None

    # Restaurant list now carries review aggregates.
    resp = client.get("/restaurants")
    entry = next(r for r in resp.json() if r["id"] == 1)
    assert entry["review_count"] >= 1
    assert entry["reviews_rating"] >= 1.0


# ---- Bundle D: scheduling, surge, receipts, replies, notifications ----

def _restaurant_headers(client):
    token = login(client, "spice@foodai.com")["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_scheduled_order(client):
    headers = _customer_headers(client)
    resp = client.post(
        "/orders",
        json=_gate(
            client,
            restaurant_id=1,
            items=[_line(1, 1)],
            scheduled_for="2099-01-01T13:00:00",
        ),
        headers=headers,
    )
    assert resp.status_code == 201
    order = resp.json()
    assert order["status"] == "PLACED"
    assert order["scheduled_for"] is not None
    assert order["delivery_fee"] >= 25.0
    assert order["surge_multiplier"] >= 1.0


def test_scheduled_order_rejects_past(client):
    resp = client.post(
        "/orders",
        json=_gate(
            client,
            restaurant_id=1,
            items=[_line(1, 1)],
            scheduled_for="2020-01-01T13:00:00",
        ),
        headers=_customer_headers(client),
    )
    assert resp.status_code == 400


def test_surge_endpoint(client):
    resp = client.get("/orders/surge", headers=_customer_headers(client))
    assert resp.status_code == 200
    body = resp.json()
    assert body["surge_multiplier"] >= 1.0
    assert body["surge_multiplier"] <= 1.5
    assert body["delivery_fee"] >= 25.0
    assert body["total_load"] >= 0


def test_order_receipt_and_email(client):
    order_id, headers = test_create_batch_order(client)
    order_id = order_id[0]
    resp = client.get(f"/orders/{order_id}/receipt", headers=headers)
    assert resp.status_code == 200
    receipt = resp.json()
    assert receipt["order_id"] == order_id
    assert receipt["food_total"] >= 0
    assert receipt["delivery_fee"] >= 0
    assert receipt["surge_multiplier"] >= 1.0
    assert receipt["grand_total"] == round(
        max(0.0, receipt["food_total"] - receipt["discount_amount"])
        + receipt["delivery_fee"],
        2,
    )
    assert receipt["billed_to"] == "customer@foodai.com"

    resp = client.post(f"/orders/{order_id}/receipt/email", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["emailed"] is True
    assert resp.json()["to"] == "customer@foodai.com"


def test_receipt_restricted(client):
    order_id, _headers = test_create_batch_order(client)
    other = {"Authorization": "Bearer " + login(client, "dosa@foodai.com")["access_token"]}
    assert client.get(f"/orders/{order_id[0]}/receipt", headers=other).status_code == 403


def test_review_photo_and_owner_reply(client):
    order_id = _delivered_order_id(client)
    customer = _customer_headers(client)
    resp = client.post(
        "/reviews",
        json={
            "order_id": order_id,
            "rating": 4,
            "comment": "Nice biryani",
            "photo_url": "https://example.com/biryani.jpg",
        },
        headers=customer,
    )
    assert resp.status_code == 201
    review = resp.json()
    assert review["photo_url"] == "https://example.com/biryani.jpg"
    assert review["owner_reply"] is None

    # The owning restaurant can reply.
    resp = client.post(
        f"/reviews/{review['id']}/reply",
        json={"reply": "Thank you! Visit again."},
        headers=_restaurant_headers(client),
    )
    assert resp.status_code == 200
    assert resp.json()["owner_reply"] == "Thank you! Visit again."
    assert resp.json()["replied_at"] is not None

    # A different restaurant cannot reply.
    other = {"Authorization": "Bearer " + login(client, "dosa@foodai.com")["access_token"]}
    resp = client.post(
        f"/reviews/{review['id']}/reply",
        json={"reply": "No!"},
        headers=other,
    )
    assert resp.status_code == 403

    # The owner can list their restaurant's reviews (with the reply visible).
    resp = client.get("/reviews/me", headers=_restaurant_headers(client))
    assert resp.status_code == 200
    assert any(
        r["id"] == review["id"] and r["owner_reply"] == "Thank you! Visit again."
        for r in resp.json()
    )

    # A customer cannot use the owner reviews endpoint.
    resp = client.get("/reviews/me", headers=customer)
    assert resp.status_code == 403


def test_notifications_flow(client):
    headers = _customer_headers(client)
    rest_headers = _restaurant_headers(client)

    # Placing an order notifies the restaurant owner.
    resp = client.post(
        "/orders",
        json=_gate(client, restaurant_id=1, items=[_line(1, 1)]),
        headers=headers,
    )
    assert resp.status_code == 201
    order_id = resp.json()["id"]

    resp = client.get("/notifications", headers=rest_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["unread"] >= 1
    types = [n["type"] for n in body["items"]]
    assert "new_order" in types

    # Assigning a driver notifies the driver.
    driver = client.get("/orders/drivers", headers=rest_headers).json()[0]
    client.post(
        f"/orders/{order_id}/assign",
        json={"driver_id": driver["id"]},
        headers=rest_headers,
    )
    driver_headers = {"Authorization": "Bearer " + login(client, driver["email"])["access_token"]}
    driver_notifs = client.get("/notifications", headers=driver_headers).json()["items"]
    assert any(n["type"] == "delivery_assigned" for n in driver_notifs)

    # Dispatching notifies the customer.
    client.patch(
        f"/orders/{order_id}/status",
        json={"status": "OUT_FOR_DELIVERY"},
        headers=rest_headers,
    )
    cust_notifs = client.get("/notifications", headers=headers).json()["items"]
    assert any(n["type"] == "order_update" for n in cust_notifs)

    # Marking one read decrements unread and persists.
    first = client.get("/notifications", headers=headers).json()["items"][0]
    resp = client.post(f"/notifications/{first['id']}/read", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["read"] is True

    resp = client.post("/notifications/read-all", headers=headers)
    assert resp.status_code == 200
    assert client.get("/notifications", headers=headers).json()["unread"] == 0


def test_driver_live_location(client):
    """The assigned driver can report GPS fixes; tracking reflects them live."""
    customer_token = login(client, "customer@foodai.com")["access_token"]
    customer_headers = {"Authorization": f"Bearer {customer_token}"}
    resp = client.post(
        "/orders",
        json=_gate(client, restaurant_id=1, items=[{"menu_item_id": 2, "quantity": 1}]),
        headers=customer_headers,
    )
    order_id = resp.json()["id"]

    owner_token = login(client, "spice@foodai.com")["access_token"]
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    driver_token = login(client, "rider@foodai.com")["access_token"]
    driver_headers = {"Authorization": f"Bearer {driver_token}"}

    resp = client.post(
        f"/orders/{order_id}/assign",
        json={"driver_id": 7},  # rider@foodai.com
        headers=owner_headers,
    )
    assert resp.status_code == 200

    # A customer cannot report the driver's location.
    resp = client.put(
        f"/orders/{order_id}/driver-location",
        json={"lat": 12.0, "lng": 77.0},
        headers=customer_headers,
    )
    assert resp.status_code == 403

    # The assigned driver can. The fix should surface on the tracking state.
    resp = client.put(
        f"/orders/{order_id}/driver-location",
        json={"lat": 12.3456, "lng": 77.6543},
        headers=driver_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert abs(body["driver_lat"] - 12.3456) < 1e-6

    tracking = client.get(f"/tracking/{order_id}", headers=customer_headers).json()
    assert tracking["position_source"] == "live"
    assert abs(tracking["rider_lat"] - 12.3456) < 1e-6
    assert abs(tracking["rider_lng"] - 77.6543) < 1e-6

    # Invalid coordinates are rejected by the schema.
    resp = client.put(
        f"/orders/{order_id}/driver-location",
        json={"lat": 999.0, "lng": 77.0},
        headers=driver_headers,
    )
    assert resp.status_code == 422


def test_admin_retrain_forecast(client):
    """Only admins may retrain; the response carries fresh metrics."""
    customer_token = login(client, "customer@foodai.com")["access_token"]
    resp = client.post(
        "/ml/forecast/retrain",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp.status_code == 403

    admin_token = login(client, "admin@foodai.com")["access_token"]
    resp = client.post(
        "/ml/forecast/retrain",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["samples"]["corpus"] > 0
    assert body["samples"]["live"] >= 0
    assert body["samples"]["total"] == body["samples"]["corpus"] + body["samples"]["live"]
    assert "xgboost" in body["metrics"]
    assert body["metrics"]["xgboost"]["mae"] >= 0.0
    assert body["metrics"]["moving_average"]["mape"] >= 0.0

    # The freshly written model is what the forecast endpoint reads.
    forecast = client.get("/ml/forecast", headers={"Authorization": f"Bearer {admin_token}"})
    assert forecast.status_code == 200
    assert forecast.json()["fallback"] is False


# ---- Order state machine ----

def _make_dispatched_order(client):
    """An order at OUT_FOR_DELIVERY with `rider@foodai.com` assigned.

    Returns (order_id, restaurant_headers, driver_headers, customer_headers).
    """
    order_id, _h = test_create_batch_order(client)
    oid = order_id[0]
    rest_token = login(client, "spice@foodai.com")["access_token"]
    rest_headers = {"Authorization": f"Bearer {rest_token}"}
    driver_headers = {"Authorization": "Bearer " + login(client, "rider@foodai.com")["access_token"]}
    rider_id = next(
        d["id"]
        for d in client.get("/orders/drivers", headers=rest_headers).json()
        if d["email"] == "rider@foodai.com"
    )
    client.post(
        f"/orders/{oid}/assign", json={"driver_id": rider_id}, headers=rest_headers
    )
    # The restaurant confirms + prepares; only the dispatch step is the driver's.
    _advance(client, oid, rest_token, ("CONFIRMED", "PREPARING"))
    resp = client.patch(
        f"/orders/{oid}/status",
        json={"status": "OUT_FOR_DELIVERY"},
        headers=driver_headers,
    )
    assert resp.status_code == 200, resp.text
    return oid, rest_headers, driver_headers, _customer_headers(client)


def test_cancelled_order_cannot_be_resurrected(client):
    """A cancelled order must not be re-dispatched, delivered, or paid.

    This is the bug that motivated the state machine: the simulation loop
    advances any OUT_FOR_DELIVERY order to DELIVERED, so a cancelled order
    could be "delivered" and billed.
    """
    order_id, _h = test_create_batch_order(client)
    oid = order_id[0]
    customer = _customer_headers(client)
    resp = client.post(f"/orders/{oid}/cancel", headers=customer)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CANCELLED"

    for target in ("OUT_FOR_DELIVERY", "DELIVERED", "PLACED", "CONFIRMED"):
        resp = client.patch(
            f"/orders/{oid}/status", json={"status": target}, headers=customer
        )
        assert resp.status_code == 400, f"{target} should be refused on a CANCELLED order"
        assert "final state" in resp.json()["detail"]


def test_delivered_order_is_final(client):
    """DELIVERED has no outgoing edges in the lifecycle graph."""
    oid, _rest, driver, _customer = _make_dispatched_order(client)
    resp = client.patch(
        f"/orders/{oid}/status", json={"status": "DELIVERED"}, headers=driver
    )
    assert resp.status_code == 200, resp.text
    for target in ("PLACED", "CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY"):
        resp = client.patch(
            f"/orders/{oid}/status", json={"status": target}, headers=driver
        )
        assert resp.status_code == 400, f"{target} should be refused on a DELIVERED order"


def test_cannot_skip_backwards_in_lifecycle(client):
    """DELIVERED -> PLACED and PREPARING -> PLACED are not edges."""
    oid, rest, _driver, _customer = _make_dispatched_order(client)
    # A restaurant trying to drag a dispatched order back to PLACED.
    resp = client.patch(
        f"/orders/{oid}/status", json={"status": "PLACED"}, headers=rest
    )
    assert resp.status_code == 400
    # And a customer trying to skip their own order straight to DELIVERED.
    resp = client.patch(
        f"/orders/{oid}/status",
        json={"status": "DELIVERED"},
        headers=_customer_headers(client),
    )
    assert resp.status_code in (400, 403)


def test_restaurant_cannot_cancel_via_status_endpoint(client):
    """CANCELLING is only reachable through POST /cancel, which checks the actor.

    Previously `PATCH /status {"status": "CANCELLED"}` fell through to the
    generic branch, where `is_restaurant_owner` alone was sufficient -- so a
    restaurant could cancel a customer's order despite the documented
    customer-or-admin rule on POST /cancel.
    """
    order_id, _h = test_create_batch_order(client)
    oid = order_id[0]
    rest_headers = {"Authorization": "Bearer " + login(client, "spice@foodai.com")["access_token"]}
    resp = client.patch(
        f"/orders/{oid}/status", json={"status": "CANCELLED"}, headers=rest_headers
    )
    assert resp.status_code == 400
    assert "cancel" in resp.json()["detail"].lower()
    # The order is untouched.
    resp = client.get(f"/orders/{oid}", headers=rest_headers)
    assert resp.json()["status"] == "PLACED"


def test_restaurant_cannot_mark_delivered(client):
    """Only the assigned driver or an admin can mark an order DELIVERED.

    COD collection is gated on DELIVERED, so a restaurant able to set it could
    unblock cash collection on an order its rider never dropped off.
    """
    oid, rest, _driver, _customer = _make_dispatched_order(client)
    resp = client.patch(
        f"/orders/{oid}/status", json={"status": "DELIVERED"}, headers=rest
    )
    assert resp.status_code == 403
    assert "assigned driver" in resp.json()["detail"]


def test_legal_lifecycle_is_still_accepted(client):
    """The strict happy path must keep working: PLACED->CONFIRMED->PREPARING."""
    order_id, _h = test_create_batch_order(client)
    oid = order_id[0]
    rest_headers = {"Authorization": "Bearer " + login(client, "spice@foodai.com")["access_token"]}
    for target in ("CONFIRMED", "PREPARING"):
        resp = client.patch(
            f"/orders/{oid}/status", json={"status": target}, headers=rest_headers
        )
        assert resp.status_code == 200, f"{target}: {resp.text}"
        assert resp.json()["status"] == target
