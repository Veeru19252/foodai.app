"""
End-to-end payment tests (Layer 4) against the isolated foodai_test database.

Covers the COD state machine (PENDING -> PAID / FAILED) and the test-mode
Razorpay intent -> verify flow, including the real HMAC-SHA256 signature
check with the same demo secret the frontend simulates.
"""

import hashlib
import hmac

from tests.conftest import login, verify_phone

# Matches backend/routers/payments.py RAZORPAY_KEY_SECRET fallback.
RAZORPAY_KEY_SECRET = "foodai_demo_secret"


def _razorpay_signature(order_id: str, payment_id: str) -> str:
    """Reproduce the frontend's simulateRazorpaySignature()."""
    return hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _create_order(client, token, payment_method="COD"):
    headers = {"Authorization": f"Bearer {token}"}
    verified = verify_phone(client, token=token)
    resp = client.post(
        "/orders",
        json={
            "restaurant_id": 1,
            "items": [{"menu_item_id": 1, "quantity": 1}],
            "delivery_address": "5th Block, Koramangala",
            "delivery_lat": 12.9719,
            "delivery_lng": 77.6412,
            "payment_method": payment_method,
            "delivery_phone": verified["phone"],
            "otp_token": verified["otp_token"],
            "location_confirmed": True,
            "location_confirm_lat": 12.9719,
            "location_confirm_lng": 77.6412,
            "delivery_city": "Bengaluru",
            "delivery_state": "Karnataka",
            "delivery_pincode": "560095",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_cod_defaults_to_pending(client):
    token = login(client, "customer@foodai.com")["access_token"]
    order = _create_order(client, token, "COD")
    assert order["payment_method"] == "COD"
    assert order["payment_status"] == "PENDING"
    # structured delivery address persisted end to end
    assert order["delivery_phone"]
    assert len(order["delivery_phone"]) == 10
    assert order["delivery_city"] == "Bengaluru"
    assert order["delivery_state"] == "Karnataka"
    assert order["delivery_pincode"] == "560095"
    assert order["location_confirmed"] is True
    assert order["phone_verified"] is True


def test_cod_confirm_and_cancel_flow(client):
    customer_token = login(client, "customer@foodai.com")["access_token"]
    customer_headers = {"Authorization": f"Bearer {customer_token}"}
    rest_token = login(client, "spice@foodai.com")["access_token"]
    rest_headers = {"Authorization": f"Bearer {rest_token}"}
    rider_token = login(client, "rider@foodai.com")["access_token"]
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    # Cancel before collection -> FAILED (the customer may reverse their own COD).
    order = _create_order(client, customer_token, "COD")
    resp = client.post(
        f"/payments/orders/{order['id']}/cod/cancel", headers=customer_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_status"] == "FAILED"

    # The customer is the payer, not the collector: cash may only be marked
    # collected by the assigned driver (or admin) after the order is DELIVERED.
    order2 = _create_order(client, customer_token, "COD")
    resp = client.post(
        f"/payments/orders/{order2['id']}/cod/confirm", headers=customer_headers
    )
    assert resp.status_code == 400, resp.text
    assert "delivered" in resp.json()["detail"]

    # Restaurant assigns the driver and dispatches; the rider completes the trip.
    drivers = client.get("/orders/drivers", headers=rest_headers).json()
    rider_id = next(d["id"] for d in drivers if d["email"] == "rider@foodai.com")
    resp = client.post(
        f"/orders/{order2['id']}/assign",
        json={"driver_id": rider_id},
        headers=rest_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.patch(
        f"/orders/{order2['id']}/status",
        json={"status": "OUT_FOR_DELIVERY"},
        headers=rest_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.patch(
        f"/orders/{order2['id']}/status",
        json={"status": "DELIVERED"},
        headers=rider_headers,
    )
    assert resp.status_code == 200, resp.text

    # A different driver (not assigned to this order) cannot collect the cash.
    other_rider_token = login(client, "priya@foodai.com")["access_token"]
    other_headers = {"Authorization": f"Bearer {other_rider_token}"}
    resp = client.post(
        f"/payments/orders/{order2['id']}/cod/confirm", headers=other_headers
    )
    assert resp.status_code == 403, resp.text

    # The assigned driver confirms after delivery -> PAID.
    resp = client.post(
        f"/payments/orders/{order2['id']}/cod/confirm", headers=rider_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_status"] == "PAID"

    # Confirming again is rejected.
    resp = client.post(
        f"/payments/orders/{order2['id']}/cod/confirm", headers=rider_headers
    )
    assert resp.status_code == 400


def test_razorpay_intent_verify_flow(client):
    token = login(client, "customer@foodai.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    order = _create_order(client, token, "RAZORPAY")
    assert order["payment_status"] == "PENDING"

    intent = client.post(
        "/payments/razorpay/order",
        json={"order_id": order["id"]},
        headers=headers,
    )
    assert intent.status_code == 200, intent.text
    intent_data = intent.json()
    assert intent_data["test_mode"] is True
    assert intent_data["amount_paise"] == int(round(order["total"], 2) * 100)
    assert intent_data["razorpay_order_id"].startswith("order_")

    # correct signature -> PAID
    payment_id = "pay_demo_1234"
    signature = _razorpay_signature(intent_data["razorpay_order_id"], payment_id)
    resp = client.post(
        "/payments/razorpay/verify",
        json={
            "order_id": order["id"],
            "razorpay_order_id": intent_data["razorpay_order_id"],
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment_status"] == "PAID"
    assert resp.json()["payment_id"] == payment_id


def test_razorpay_wrong_signature_rejected(client):
    token = login(client, "customer@foodai.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    order = _create_order(client, token, "RAZORPAY")

    intent = client.post(
        "/payments/razorpay/order",
        json={"order_id": order["id"]},
        headers=headers,
    ).json()
    resp = client.post(
        "/payments/razorpay/verify",
        json={
            "order_id": order["id"],
            "razorpay_order_id": intent["razorpay_order_id"],
            "razorpay_payment_id": "pay_demo_1234",
            "razorpay_signature": "a" * 64,  # definitely wrong
        },
        headers=headers,
    )
    assert resp.status_code == 400

    # order stays PENDING, money never settled
    status = client.get(f"/payments/orders/{order['id']}", headers=headers)
    assert status.json()["payment_status"] == "PENDING"


def test_payment_status_visible_on_order_list(client):
    token = login(client, "customer@foodai.com")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    order = _create_order(client, token, "RAZORPAY")

    orders = client.get("/orders", headers=headers).json()
    row = next(o for o in orders if o["id"] == order["id"])
    assert row["payment_method"] == "RAZORPAY"
    assert row["payment_status"] == "PENDING"
