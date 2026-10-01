"""Config wiring sanity checks.

Guards against values that used to be hard-coded in the source drifting away
from the environment-driven config.
"""

from __future__ import annotations

import contextlib
import importlib
import os

import pytest

from backend import config, simulation


def test_simulation_interval_comes_from_config():
    assert simulation.SIM_INTERVAL_SECONDS == config.SIM_INTERVAL_SECONDS
    assert simulation.SIM_INTERVAL_SECONDS > 0


def test_production_flag_matches_environment():
    assert config.IS_PRODUCTION is (config.ENVIRONMENT == "production")


def test_cors_origins_drop_blank_entries():
    """A trailing comma must not become a '' origin, which matches nothing."""
    with reloaded_config(CORS_ORIGINS="https://a.example, ,https://b.example") as cfg:
        assert cfg.CORS_ORIGINS == ["https://a.example", "https://b.example"]


def test_production_refuses_default_localhost_cors_origins():
    """Without CORS_ORIGINS, production would reject its own deployed frontend.

    The local defaults only match a developer's machine, so a production deploy
    that forgot the variable would start cleanly and then refuse every browser
    request from its own domain -- a failure that looks like a proxy problem.
    The guard has to engage at import time, which is what this reload checks.
    """
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        with reloaded_config(
            ENVIRONMENT="production",
            JWT_SECRET="x" * 40,
            PAYMENTS_TEST_MODE="1",
        ):
            pass


def test_production_accepts_an_explicit_cors_origin():
    with reloaded_config(
        ENVIRONMENT="production",
        CORS_ORIGINS="https://foodai.onrender.com",
        JWT_SECRET="x" * 40,
        PAYMENTS_TEST_MODE="1",
    ) as cfg:
        assert cfg.IS_PRODUCTION is True
        assert cfg.CORS_ORIGINS == ["https://foodai.onrender.com"]


@contextlib.contextmanager
def reloaded_config(**env):
    """Re-import backend.config with `env` applied, then restore it.

    backend.config reads the environment once at import time, so exercising a
    production guard means re-importing it. os.environ is snapshotted and put
    back and the module re-imported on the way out, because leaving it
    reloaded under a test's env would silently change every later test that
    reads config (and would leave the TestClient's CORS list inconsistent with
    the module it was built from).
    """
    saved = dict(os.environ)
    for key, value in env.items():
        os.environ[key] = value
    try:
        yield importlib.reload(config)
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)
