"""Regression tests for the auth hardening work.

Covers the guarantees that are easy to silently regress: typed JWTs (an access
token is not a refresh token and vice versa), Argon2id password storage with
legacy-hash upgrade on login, and OTP codes only being returned in dev mode.
"""

from __future__ import annotations

import hashlib
import random

from backend import security
from backend.db import SessionLocal
from backend.models import User


def login(client, email: str = "customer@foodai.com", password: str = "password123") -> dict:
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _fresh_phone() -> str:
    return "9" + "".join(random.choices("0123456789", k=9))


# ---- typed JWTs ----

def test_decode_access_token_rejects_refresh_token():
    refresh = security.create_refresh_token(1, "customer")
    access = security.create_access_token(1, "customer")

    assert security.decode_access_token(refresh) is None
    assert security.decode_refresh_token(access) is None
    assert security.decode_access_token(access) is not None
    assert security.decode_refresh_token(refresh) is not None


def test_access_token_rejected_as_refresh(client):
    tokens = login(client)
    resp = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401, resp.text


def test_refresh_token_rejected_as_access(client):
    tokens = login(client)
    resp = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )
    assert resp.status_code == 401, resp.text


# ---- password storage ----

def test_seeded_passwords_are_argon2id(client):
    db = SessionLocal()
    try:
        hashes = [u.password_hash for u in db.query(User).all()]
    finally:
        db.close()
    assert hashes
    assert all(h.startswith("$argon2id$") for h in hashes)


def test_legacy_sha256_hash_upgrades_on_login(client):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "customer@foodai.com").first()
        original = user.password_hash
        user.password_hash = hashlib.sha256(b"password123").hexdigest()
        db.commit()
    finally:
        db.close()

    try:
        assert login(client)["access_token"]

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "customer@foodai.com").first()
            assert user.password_hash.startswith("$argon2id$")
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "customer@foodai.com").first()
            user.password_hash = original
            db.commit()
        finally:
            db.close()


# ---- OTP dev-mode gating ----

def test_otp_dev_code_present_in_dev_mode(client):
    from backend import config

    assert config.OTP_DEV_MODE is True  # conftest sets OTP_DEV_MODE=1
    resp = client.post("/auth/otp/request", json={"phone": _fresh_phone()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["test_mode"] is True
    assert body["dev_code"]


def test_otp_dev_code_hidden_when_dev_mode_off(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "OTP_DEV_MODE", False)
    resp = client.post("/auth/otp/request", json={"phone": _fresh_phone()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["test_mode"] is False
    assert body["dev_code"] is None


# ---- OTP digest is keyed ----

def test_otp_hash_is_keyed_not_plain_sha256():
    from backend.routers.auth import _hash_otp

    code = "123456"
    digest = _hash_otp(code)
    assert digest != hashlib.sha256(code.encode()).hexdigest()
    assert digest == _hash_otp(code)  # deterministic
    assert len(digest) == 64


def test_stored_otp_hash_is_keyed(client):
    from backend.db import SessionLocal
    from backend.models import OtpCode
    from backend.routers.auth import _hash_otp

    phone = _fresh_phone()
    resp = client.post("/auth/otp/request", json={"phone": phone})
    assert resp.status_code == 200, resp.text
    code = resp.json()["dev_code"]

    db = SessionLocal()
    try:
        row = (
            db.query(OtpCode)
            .filter(OtpCode.phone == phone)
            .order_by(OtpCode.id.desc())
            .first()
        )
    finally:
        db.close()

    assert row is not None
    assert row.code_hash == _hash_otp(code)
    assert row.code_hash != hashlib.sha256(code.encode()).hexdigest()
