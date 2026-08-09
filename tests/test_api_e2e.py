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
