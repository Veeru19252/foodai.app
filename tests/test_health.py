"""Health endpoint checks.

The health check is what the platform polls to decide whether to keep routing
traffic to an instance, so its failure modes matter more than they look: a
check that reports "ok" without touching the database keeps a broken
instance in rotation and silences the alarm.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend import main  # noqa: F401  (imported so the app is loadable)


def test_health_reports_ok_against_a_live_database(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "foodai-backend"
    # A bare {"status": "ok"} would also be returned by a check that never
    # reached Postgres, so the DB verdict has to be explicit.
    assert body["database"] == "ok"


def test_health_returns_503_when_the_database_is_unreachable(client, monkeypatch):
    """A dead database must take the instance out of rotation, not report ok."""

    def _boom(*_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    # get_db yields a Session, so this is the call the route actually makes.
    monkeypatch.setattr("sqlalchemy.orm.Session.execute", _boom, raising=True)

    resp = client.get("/api/health")
    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"] == "Database unreachable."


def test_health_does_not_leak_driver_detail(client, monkeypatch, caplog):
    """The 503 body must not echo the connection URL or driver internals."""

    def _boom(*_args, **_kwargs):
        raise OperationalError(
            "SELECT 1",
            {},
            Exception("could not connect to postgresql://foodai:hunter2@db/foodai"),
        )

    monkeypatch.setattr("sqlalchemy.orm.Session.execute", _boom, raising=True)
    resp = client.get("/api/health")
    assert resp.status_code == 503
    assert "hunter2" not in resp.text
    assert "postgresql://" not in resp.text
    # The cause should still be logged for the operator.
    assert any("health check failed" in r.message for r in caplog.records)


def test_health_needs_no_authentication(client):
    """The platform's prober has no token, so this must stay public."""
    resp = client.get("/api/health")
    assert resp.status_code in (200, 503)
