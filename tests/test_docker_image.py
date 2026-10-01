"""Guards the Docker image contents against the runtime's file dependencies.

The admin retrain endpoint imports ``scripts/train_forecast.py`` and reads
``data/orders.csv``; the ETA quality gate reads ``outputs/metrics_eta.json``.
If the Dockerfile stops copying any of these (or ``.dockerignore`` starts
excluding them), retraining breaks in the container while still passing
locally.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _dockerfile() -> str:
    return (ROOT / "backend" / "Dockerfile").read_text()


def _dockerignore() -> set:
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    return {ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")}


def test_dockerfile_copies_runtime_data_dirs():
    dockerfile = _dockerfile()
    for path in ("scripts/", "data/", "outputs/"):
        assert f"COPY {path} {path}" in dockerfile, f"Dockerfile must COPY {path}"


def test_dockerignore_does_not_exclude_runtime_data():
    ignored = _dockerignore()
    for path in ("scripts", "data", "outputs"):
        assert path not in ignored, f".dockerignore must not exclude {path}"
