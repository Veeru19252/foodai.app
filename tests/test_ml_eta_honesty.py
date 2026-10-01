"""Honesty guarantees for the ML ETA endpoints.

The ETA model must never be presented as "ML" when it is missing or worse
than the distance/speed formula, and the endpoints must degrade gracefully
instead of returning 503.
"""

from __future__ import annotations

import pytest

import eta_service
import tracking


def login(client, email: str = "customer@foodai.com", password: str = "password123") -> dict:
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth(client) -> dict:
    return {"Authorization": f"Bearer {login(client)['access_token']}"}


def test_formula_eta_matches_tracking_distance_eta():
    distance_km, expected = tracking.compute_distance_eta(12.97, 77.59, 12.90, 77.60)
    assert eta_service.formula_eta(distance_km, tracking.PREP_BUFFER_MIN) == pytest.approx(
        expected
    )


def test_eta_reports_source_and_never_503(client):
    resp = client.get(
        "/ml/eta?restaurant_id=1&distance_km=5&prep_time_min=15", headers=_auth(client)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] in {"ml", "formula"}
    assert body["fallback"] is (body["source"] == "formula")
    assert body["eta_min"] > 0


def test_eta_falls_back_when_model_missing(client, monkeypatch):
    monkeypatch.setattr(eta_service, "load_model", lambda: None)
    resp = client.get(
        "/ml/eta?restaurant_id=1&distance_km=5&prep_time_min=15", headers=_auth(client)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fallback"] is True
    assert body["source"] == "formula"
    assert body["eta_min"] == pytest.approx(round(eta_service.formula_eta(5.0, 15.0), 1))


def test_eta_falls_back_when_model_worse_than_baseline(client, monkeypatch):
    monkeypatch.setattr(
        eta_service,
        "model_metrics",
        lambda: {"xgboost": {"mae": 9.9}, "baseline": {"mae": 1.0}},
    )
    resp = client.get(
        "/ml/eta?restaurant_id=1&distance_km=5&prep_time_min=15", headers=_auth(client)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fallback"] is True
    assert body["source"] == "formula"


def test_explain_degrades_without_explainer(client, monkeypatch):
    import explain_service

    monkeypatch.setattr(explain_service, "explain_eta", lambda features: None)
    resp = client.post(
        "/ml/eta/explain?restaurant_id=1&distance_km=5&prep_time_min=15",
        headers=_auth(client),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fallback"] is True
    assert body["explanation"] is None
