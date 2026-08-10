"""
Pytest fixtures for the FoodAI backend.
=======================================
Forces the DATABASE_URL to the isolated foodai_test database BEFORE any
backend module is imported (backend.config reads the env at import time).
"""

import os
import random

os.environ["DATABASE_URL"] = (
    "postgresql+psycopg2://foodai:foodai_pass@127.0.0.1:5432/foodai_test"
)

import pytest
from fastapi.testclient import TestClient

from backend.db import Base, SessionLocal, engine
from backend.main import app
from backend import seed


@pytest.fixture(autouse=True)
def isolated_ml_artifacts(tmp_path):
    """Keep the admin retrain test from rewriting the repo's model files.

    ml_train.py reads its output paths from module-level constants at call
    time, so monkeypatching them to a temp dir means every pytest run leaves
    the working tree clean.
    """
    from backend import ml_train

    monkey = pytest.MonkeyPatch()
    monkey.setattr(ml_train, "MODEL_PATH", tmp_path / "forecast_model.joblib")
    monkey.setattr(ml_train, "META_PATH", tmp_path / "forecast_meta.json")
    monkey.setattr(ml_train, "METRICS_PATH", tmp_path / "metrics_forecast.json")
    yield
    monkey.undo()


@pytest.fixture(scope="session")
def client():
    # Fresh schema + seed data per test session.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed.seed_if_empty(db)
    finally:
        db.close()
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str, password: str = "password123") -> dict:
    """Log in and return {access_token, refresh_token, user}."""
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def verify_phone(client: TestClient, phone: str = None, token: str = None) -> dict:
    """Request + verify an OTP and return {phone, otp_token, ...}.

    The demo has no SMS provider, so the code comes back as dev_code on the
    request response. Uses a fresh random number by default so tests never
    trip the per-phone resend cooldown (60s).
    """
    if phone is None:
        phone = "9" + "".join(random.choices("0123456789", k=9))
    resp = client.post("/auth/otp/request", json={"phone": phone})
    assert resp.status_code == 200, resp.text
    code = resp.json()["dev_code"]
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = client.post(
        "/auth/otp/verify",
        json={"phone": phone, "code": code},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()
