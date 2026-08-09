"""
End-to-end API tests against the isolated foodai_test database.
Covers auth, catalog, orders + promos, assignment, tracking, ML, and
role-based access control.
"""

import eta_service

from tests.conftest import login


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
        json={
            "restaurant_id": 1,
            "items": [{"menu_item_id": 1, "quantity": 2}, {"menu_item_id": 5, "quantity": 1}],
            "coupon_code": "WELCOME10",
            "delivery_address": "5th Block, Koramangala",
            "delivery_lat": 12.9719,
            "delivery_lng": 77.6412,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    order = resp.json()
    # 2 * 220 + 200 = 640; WELCOME10 = 10% capped at 50 -> total 590.
    assert order["total"] == 590.0
    assert order["discount_amount"] == 50.0
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
        json={"restaurant_id": 1, "items": [{"menu_item_id": 9999, "quantity": 1}]},
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
    resp = client.patch(
        f"/orders/{order_id}/status",
        json={"status": "OUT_FOR_DELIVERY"},
        headers={"Authorization": f"Bearer {rest_token}"},
    )
    assert resp.status_code == 200
    return order_id, driver, customer_token, rest_token


def test_customer_cannot_confirm_order(client):
    token = login(client, "customer@foodai.com")["access_token"]
    resp = client.patch(
        "/orders/1/status",
        json={"status": "CONFIRMED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


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
        json={"restaurant_id": 1, "items": [{"menu_item_id": 1, "quantity": 2}]},
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


def test_tracking_includes_timeline(client):
    token = login(client, "customer@foodai.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/orders",
        json={"restaurant_id": 2, "items": [{"menu_item_id": 6, "quantity": 1}]},
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
    assert body["restaurants"] == 5


def test_unauthenticated_requests_rejected(client):
    assert client.get("/orders").status_code == 401
    assert client.get("/tracking/1").status_code == 401
    assert client.get("/ml/eta?restaurant_id=1").status_code == 401


def _customer_headers(client):
    token = login(client, "customer@foodai.com")["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _line(menu_item_id, quantity):
    return {"menu_item_id": menu_item_id, "quantity": quantity}


# ---- Phase 3: batch orders ----

def test_create_batch_order(client):
    headers = _customer_headers(client)
    resp = client.post(
        "/orders/batch",
        json={
            "orders": [
                {
                    "restaurant_id": 1,
                    "items": [_line(1, 2)],
                    "coupon_code": "WELCOME10",
                    "delivery_address": "5th Block, Koramangala",
                    "delivery_lat": 12.9719,
                    "delivery_lng": 77.6412,
                },
                {
                    "restaurant_id": 2,
                    "items": [_line(8, 1)],
                    "delivery_address": "5th Block, Koramangala",
                    "delivery_lat": 12.9719,
                    "delivery_lng": 77.6412,
                },
            ]
        },
        headers=headers,
    )
    assert resp.status_code == 201
    orders = resp.json()["orders"]
    assert len(orders) == 2
    # Restaurant 1: 2 * 220 = 440; WELCOME10 = 10% (44, below cap 50) -> 396.
    assert orders[0]["restaurant_id"] == 1
    assert orders[0]["total"] == 396.0
    assert orders[1]["restaurant_id"] == 2
    return [o["id"] for o in orders], headers


def test_batch_order_empty_rejected(client):
    resp = client.post(
        "/orders/batch", json={"orders": []}, headers=_customer_headers(client)
    )
    assert resp.status_code == 422


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


# ---- Phase 3: driver starts delivery ----

def test_assigned_driver_can_dispatch(client):
    order_id, driver, _cust, _rest = test_restaurant_full_lifecycle(client)
    # Pick a fresh order and let the assigned driver dispatch it.
    order_id, _h = test_create_batch_order(client)
    order_id = order_id[0]
    driver_token = login(client, driver["email"])["access_token"]
    resp = client.patch(
        f"/orders/{order_id}/status",
        json={"status": "OUT_FOR_DELIVERY"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    # The driver isn't assigned to this new order yet.
    assert resp.status_code == 403

    rest_token = login(client, "spice@foodai.com")["access_token"]
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
    other_token = login(client, "rider@foodai.com")["access_token"]
    resp = client.patch(
        f"/orders/{order_id[0]}/status",
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
    client.patch(f"/orders/{order_id}/status", json={"status": "OUT_FOR_DELIVERY"}, headers={"Authorization": f"Bearer {rest_token}"})
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
