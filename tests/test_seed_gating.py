"""
Demo-seeding guard tests.

The suite seeds demo data (SEED_DEMO_DATA=1 in conftest), so these tests
exercise the guard directly rather than through the app lifespan.
"""

import pytest

from backend import config, seed
from backend.db import SessionLocal


def test_seed_is_a_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "SEED_DEMO_DATA", False)
    db = SessionLocal()
    try:
        assert seed.seed_if_empty(db) is False
    finally:
        db.close()


def test_seed_refuses_default_password_in_production(monkeypatch):
    monkeypatch.setattr(config, "SEED_DEMO_DATA", True)
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "DEMO_USER_PASSWORD", "password123")
    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError):
            seed.seed_if_empty(db)
    finally:
        db.close()
