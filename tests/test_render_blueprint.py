"""Render deployment blueprint checks.

The blueprint is the only place that decides what a public deploy looks like.
Every guard in backend/config.py keys off ENVIRONMENT, so if the blueprint
omits it the deploy silently runs in development mode: it seeds password123
demo accounts, echoes OTP codes in the /auth/otp/request response body, and
signs tokens with the public default JWT secret. That failure is invisible
until someone logs in to a public URL, which is why it is pinned here.
"""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml not installed")

BLUEPRINT = pathlib.Path(__file__).resolve().parents[1] / "render.yaml"


@pytest.fixture(scope="module")
def blueprint() -> dict:
    return yaml.safe_load(BLUEPRINT.read_text())


def _backend_env(blueprint: dict) -> dict:
    for service in blueprint["services"]:
        if service.get("name") == "foodai-backend":
            return {entry["key"]: entry for entry in service["envVars"]}
    raise AssertionError("render.yaml has no foodai-backend service")


def test_blueprint_parses():
    assert BLUEPRINT.exists(), "render.yaml is missing from the repo root"


def test_backend_deploy_runs_in_production_mode(blueprint):
    """The single most important line in the blueprint."""
    env = _backend_env(blueprint)
    assert "ENVIRONMENT" in env, (
        "render.yaml must set ENVIRONMENT=production; without it backend/config.py "
        "treats a public deploy as development (demo seeding, OTP codes in "
        "responses, public default JWT secret)"
    )
    assert env["ENVIRONMENT"].get("value") == "production"


def test_backend_deploy_pins_cors_to_the_frontend_origin(blueprint):
    """Production now refuses to boot without an explicit CORS_ORIGINS."""
    env = _backend_env(blueprint)
    assert "CORS_ORIGINS" in env, (
        "backend/config.py raises at import time in production when CORS_ORIGINS "
        "is unset, so the blueprint must supply the frontend's origin"
    )


def test_backend_deploy_does_not_force_payments_test_mode(blueprint):
    """Forcing test mode on would re-enable the public demo Razorpay secret."""
    env = _backend_env(blueprint)
    assert "PAYMENTS_TEST_MODE" not in env, (
        "PAYMENTS_TEST_MODE=1 in the blueprint makes the deploy use the public "
        "demo Razorpay credentials; production must fall through to the key guard"
    )


def test_frontend_points_at_the_backend_service(blueprint):
    for service in blueprint["services"]:
        if service.get("name") == "foodai-frontend":
            env = {e["key"]: e for e in service["envVars"]}
            assert "NEXT_PUBLIC_API_URL" in env
            return
    raise AssertionError("render.yaml has no foodai-frontend service")


def test_start_command_runs_migrations_before_serving(blueprint):
    """A fresh Postgres has no tables; serving first would 500 on every request."""
    start = _backend_env(blueprint)  # ensure the backend service exists
    for service in blueprint["services"]:
        if service.get("name") == "foodai-backend":
            cmd = service["startCommand"]
            assert "alembic upgrade head" in cmd, cmd
            assert cmd.index("alembic upgrade head") < cmd.index("uvicorn"), cmd
            return
    raise AssertionError(f"unreachable: {start}")
