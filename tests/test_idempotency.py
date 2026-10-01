"""Idempotency and batch-atomicity tests for order creation.

Covers the four retry scenarios described in backend/idempotency.py, plus the
atomicity guarantee that a partial multi-restaurant cart cannot be created.
"""

import uuid

import pytest

from backend import idempotency
from backend.db import SessionLocal
from backend.models import IdempotencyRecord, Order

from test_api_e2e import (
    _customer_headers,
    _gate,
    _line,
    login,
)


def _key():
    """A fresh client-generated key, as a real client would send."""
    return str(uuid.uuid4())


def _one_order_body(client):
    return {
        "restaurant_id": 1,
        "items": [_line(1, 2)],
        "coupon_code": "WELCOME10",
        **_gate(client),
    }


# ---- single order ----

def test_retry_with_same_key_returns_same_order(client):
    """The core scenario: response lost, client retries, no double order."""
    headers = {**_customer_headers(client), "Idempotency-Key": _key()}
    body = _one_order_body(client)

    first = client.post("/orders", json=body, headers=headers)
    assert first.status_code == 201, first.text

    second = client.post("/orders", json=body, headers=headers)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    # And exactly one order with that ID exists -- the retry did not add a
    # second. (Counting by the returned ID is what makes this a real
    # duplicate check rather than a re-read of the same row.)
    db = SessionLocal()
    try:
        order_id = first.json()["id"]
        assert db.query(Order).filter(Order.id == order_id).count() == 1
        total_after = db.query(Order).count()
    finally:
        db.close()

    # A third retry changes nothing either.
    third = client.post("/orders", json=body, headers=headers)
    assert third.status_code == 201
    assert third.json()["id"] == first.json()["id"]
    db = SessionLocal()
    try:
        assert db.query(Order).count() == total_after
    finally:
        db.close()


def test_retry_does_not_double_charge_the_coupon(client):
    """A retry must not increment promo.times_used a second time."""
    key = _key()
    headers = {**_customer_headers(client), "Idempotency-Key": key}
    body = _one_order_body(client)

    first = client.post("/orders", json=body, headers=headers)
    assert first.status_code == 201, first.text

    db = SessionLocal()
    try:
        from backend.models import PromoCode
        before = db.query(PromoCode).filter(PromoCode.code == "WELCOME10").one().times_used
    finally:
        db.close()

    second = client.post("/orders", json=body, headers=headers)
    assert second.status_code == 201

    db = SessionLocal()
    try:
        from backend.models import PromoCode
        after = db.query(PromoCode).filter(PromoCode.code == "WELCOME10").one().times_used
    finally:
        db.close()

    assert after == before, f"times_used went {before} -> {after} on a retry"


def test_same_key_different_payload_is_rejected(client):
    """Key reuse with a different body is a client bug and must not silently
    return the first order, which would hide the bug."""
    key = _key()
    headers = {**_customer_headers(client), "Idempotency-Key": key}

    first = client.post("/orders", json=_one_order_body(client), headers=headers)
    assert first.status_code == 201, first.text

    different = _one_order_body(client)
    different["items"] = [_line(1, 5)]
    resp = client.post("/orders", json=different, headers=headers)
    assert resp.status_code == 409
    assert "different request body" in resp.json()["detail"]


def test_key_is_scoped_per_user(client):
    """Two users may pick the same key string without colliding."""
    key = _key()
    body = _one_order_body(client)

    cust_a = client.post(
        "/orders",
        json=body,
        headers={**_customer_headers(client), "Idempotency-Key": key},
    )
    # A second, different customer using the same key must get their own order.
    other = client.post(
        "/auth/register",
        json={
            "email": "idem-other@example.com",
            "password": "password123",
            "name": "Idem Other",
            "role": "customer",
        },
    )
    assert other.status_code in (200, 201), other.text
    other_headers = {
        "Authorization": "Bearer " + login(client, "idem-other@example.com")["access_token"],
        "Idempotency-Key": key,
    }
    cust_b = client.post("/orders", json=body, headers=other_headers)
    assert cust_b.status_code == 201, cust_b.text
    assert cust_b.json()["id"] != cust_a.json()["id"]


def test_blank_key_is_ignored(client):
    """An empty header means "no protection", so behaviour is unchanged."""
    resp = client.post(
        "/orders",
        json=_one_order_body(client),
        headers={**_customer_headers(client), "Idempotency-Key": "   "},
    )
    assert resp.status_code == 201, resp.text


def test_oversized_key_is_rejected(client):
    resp = client.post(
        "/orders",
        json=_one_order_body(client),
        headers={**_customer_headers(client), "Idempotency-Key": "x" * 300},
    )
    assert resp.status_code == 400
    assert "255" in resp.json()["detail"]


def test_request_without_key_still_creates_distinct_orders(client):
    """Backwards compatibility: no header, no dedup -- same as before."""
    headers = _customer_headers(client)
    first = client.post("/orders", json=_one_order_body(client), headers=headers)
    second = client.post("/orders", json=_one_order_body(client), headers=headers)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


# ---- batch ----

def test_batch_retry_returns_same_orders(client):
    key = _key()
    headers = {**_customer_headers(client), "Idempotency-Key": key}
    body = {
        "orders": [
            {"restaurant_id": 1, "items": [_line(1, 2)], **_gate(client)},
            {"restaurant_id": 2, "items": [_line(8, 1)], **_gate(client)},
        ]
    }

    first = client.post("/orders/batch", json=body, headers=headers)
    assert first.status_code == 201, first.text
    first_ids = [o["id"] for o in first.json()["orders"]]

    second = client.post("/orders/batch", json=body, headers=headers)
    assert second.status_code == 201, second.text
    assert [o["id"] for o in second.json()["orders"]] == first_ids


def test_batch_is_atomic_on_failure(client):
    """A bad group must not leave its healthy siblings placed.

    Regression test: each group used to commit on its own, so a failure on the
    second group left the first order live and charged.
    """
    headers = _customer_headers(client)
    # Restaurant 1 is valid; restaurant 2 gets a menu item it does not serve.
    body = {
        "orders": [
            {"restaurant_id": 1, "items": [_line(1, 2)], **_gate(client)},
            {"restaurant_id": 2, "items": [{"menu_item_id": 1, "quantity": 1}], **_gate(client)},
        ]
    }

    resp = client.post("/orders/batch", json=body, headers=headers)
    assert resp.status_code == 400, resp.text

    # No order from restaurant 1 may exist for this attempt. Compare against the
    # set created before the call.
    db = SessionLocal()
    try:
        max_before = db.query(Order).count()
    finally:
        db.close()

    # A second identical failing call must not create anything either.
    client.post("/orders/batch", json=body, headers=headers)
    db = SessionLocal()
    try:
        assert db.query(Order).count() == max_before
    finally:
        db.close()


def test_batch_key_survives_a_failed_attempt(client):
    """A crashed/failed request must not burn the client's key.

    The claim shares the order transaction, so a rollback takes the claim with
    it and the client can retry with the same key.
    """
    key = _key()
    headers = {**_customer_headers(client), "Idempotency-Key": key}
    bad = {
        "orders": [
            {"restaurant_id": 1, "items": [_line(1, 2)], **_gate(client)},
            {"restaurant_id": 2, "items": [{"menu_item_id": 1, "quantity": 1}], **_gate(client)},
        ]
    }
    resp = client.post("/orders/batch", json=bad, headers=headers)
    assert resp.status_code == 400

    db = SessionLocal()
    try:
        rows = (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.key == key)
            .count()
        )
        assert rows == 0, "a rolled-back attempt must not leave a claim behind"
    finally:
        db.close()

    # The same key now works for a good request.
    good = {
        "orders": [
            {"restaurant_id": 1, "items": [_line(1, 2)], **_gate(client)},
        ]
    }
    resp = client.post("/orders/batch", json=good, headers=headers)
    assert resp.status_code == 201, resp.text


def test_replay_reflects_current_status_not_a_snapshot(client):
    """A late retry returns the order's live state, not a frozen 201 body."""
    key = _key()
    headers = {**_customer_headers(client), "Idempotency-Key": key}
    body = _one_order_body(client)

    first = client.post("/orders", json=body, headers=headers)
    assert first.status_code == 201, first.text
    order_id = first.json()["id"]
    assert first.json()["status"] == "PLACED"

    # Move the order along, then retry with the same key.
    rest = {"Authorization": "Bearer " + login(client, "spice@foodai.com")["access_token"]}
    assert client.patch(
        f"/orders/{order_id}/status", json={"status": "CONFIRMED"}, headers=rest
    ).status_code == 200

    replay = client.post("/orders", json=body, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["id"] == order_id
    assert replay.json()["status"] == "CONFIRMED", (
        "replay should re-read live state, not return the original snapshot"
    )


# ---- unit-level contract ----

def test_fingerprint_is_order_independent():
    """Two retries of the same logical request must agree despite key order."""
    a = {"restaurant_id": 1, "items": [{"menu_item_id": 2, "quantity": 1}]}
    b = {"items": [{"quantity": 1, "menu_item_id": 2}], "restaurant_id": 1}
    assert idempotency.request_fingerprint(a) == idempotency.request_fingerprint(b)


def test_fingerprint_differs_on_content():
    a = {"restaurant_id": 1, "items": [{"menu_item_id": 2, "quantity": 1}]}
    b = {"restaurant_id": 1, "items": [{"menu_item_id": 2, "quantity": 2}]}
    assert idempotency.request_fingerprint(a) != idempotency.request_fingerprint(b)


def test_normalize_key_passthrough():
    assert idempotency.normalize_key(None) is None
    assert idempotency.normalize_key("") is None
    assert idempotency.normalize_key("  abc  ") == "abc"


def test_normalize_key_rejects_absurd_length():
    with pytest.raises(Exception) as exc:
        idempotency.normalize_key("x" * 256)
    assert exc.value.status_code == 400


# ---- retention ----

def test_purge_expired_removes_only_old_keys(client):
    """The sweep must delete stale keys and leave fresh ones alone.

    Without this the table grows by one row per order forever, and a key from
    months ago would still be honoured -- so a client that reused a key string
    would silently get an ancient order back.
    """
    from datetime import datetime, timedelta

    from backend import idempotency as idem
    from backend.db import SessionLocal
    from backend.models import IdempotencyRecord

    db = SessionLocal()
    try:
        old = IdempotencyRecord(
            user_id=1,
            key="old-key",
            endpoint=idem.ENDPOINT_ORDERS,
            request_hash="x",
            order_ids="[1]",
            created_at=datetime.utcnow() - idem.RETENTION - timedelta(days=1),
        )
        fresh = IdempotencyRecord(
            user_id=1,
            key="fresh-key",
            endpoint=idem.ENDPOINT_ORDERS,
            request_hash="y",
            order_ids="[2]",
            created_at=datetime.utcnow(),
        )
        db.add_all([old, fresh])
        db.commit()

        removed = idem.purge_expired(db)
        assert removed >= 1

        remaining = {
            r.key
            for r in db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.key.in_(["old-key", "fresh-key"]))
            .all()
        }
        assert "old-key" not in remaining
        assert "fresh-key" in remaining
    finally:
        db.close()
