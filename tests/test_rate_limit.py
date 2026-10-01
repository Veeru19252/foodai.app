"""
Rate-limiting regression tests (Layer 4) against the isolated foodai_test DB.

The suite-wide conftest raises the throttles so ordinary tests are unaffected;
these tests lower them via monkeypatch and use unique identifiers so they do
not interfere with each other or with the rest of the suite.
"""

import random
import uuid

from backend import config


def _unique_email() -> str:
    return f"rl-{uuid.uuid4().hex[:12]}@example.com"


def _unique_phone() -> str:
    return "9" + "".join(random.choices("0123456789", k=9))


def test_login_is_throttled_per_email(client, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "LOGIN_IP_MAX_ATTEMPTS", 100000)
    email = _unique_email()

    # Three failed attempts are allowed (401); the fourth is throttled (429).
    for _ in range(3):
        resp = client.post("/auth/login", json={"email": email, "password": "wrong"})
        assert resp.status_code == 401, resp.text

    resp = client.post("/auth/login", json={"email": email, "password": "wrong"})
    assert resp.status_code == 429, resp.text
    assert "Retry-After" in resp.headers


def test_successful_login_resets_email_bucket(client, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "LOGIN_IP_MAX_ATTEMPTS", 100000)
    email = _unique_email()
    password = "secret123"

    reg = client.post(
        "/auth/register",
        json={"name": "RL", "email": email, "password": password, "role": "customer"},
    )
    assert reg.status_code == 201, reg.text

    # Two failures, then a success clears the per-email counter.
    for _ in range(2):
        client.post("/auth/login", json={"email": email, "password": "wrong"})
    ok = client.post("/auth/login", json={"email": email, "password": password})
    assert ok.status_code == 200, ok.text

    # The bucket was reset, so failures start from zero again.
    for _ in range(3):
        resp = client.post("/auth/login", json={"email": email, "password": "wrong"})
        assert resp.status_code == 401, resp.text


def test_otp_verify_is_throttled_per_phone(client, monkeypatch):
    monkeypatch.setattr(config, "OTP_VERIFY_MAX_ATTEMPTS", 3)
    phone = _unique_phone()

    # No OTP was requested, so each attempt is a 400 -- but it still counts.
    for _ in range(3):
        resp = client.post("/auth/otp/verify", json={"phone": phone, "code": "000000"})
        assert resp.status_code == 400, resp.text

    resp = client.post("/auth/otp/verify", json={"phone": phone, "code": "000000"})
    assert resp.status_code == 429, resp.text
    assert "Retry-After" in resp.headers
