"""
FoodAI - ETA prediction service (pure module)
=============================================

Loads the trained XGBoost ETA model (``models/eta_model.joblib``) and exposes
pure, testable helpers for estimating delivery time from order features.

This module mirrors the feature pipeline in ``scripts/train_eta.py`` exactly:
the feature vector is the numeric block

    [distance_km, prep_time_min, hour_of_day, day_of_week, is_weekend, traffic_factor]

followed by the one-hot customer-zone block

    [zone_A, zone_B, zone_C, zone_D, zone_E]

i.e. the exact column order of ``train_eta.FULL_COLUMNS`` (the input ``hour``
key is used raw as ``hour_of_day``). Keeping the two pipelines in sync
guarantees inference sees the same fixed-width float input the model was
trained on.

Design constraints
------------------
* Pure module: no streamlit/folium imports and no database access, so it can
  be imported from a plain ``python3`` REPL with no extra packages beyond
  ``joblib`` and the dependency-free ``tracking`` module.
* If the model file is missing, ``load_model()`` prints a one-time warning and
  ``best_eta()`` falls back to ``tracking.compute_eta``'s speed formula.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import tracking

try:
    import joblib
except ModuleNotFoundError:
    joblib = None  # type: ignore

if TYPE_CHECKING:
    from xgboost import XGBRegressor

__all__ = [
    "load_model",
    "predict_eta",
    "ZONE_ANCHORS",
    "nearest_zone",
    "features_for_order",
    "best_eta",
    "NUMERIC_COLUMNS",
    "ZONE_COLUMNS",
    "FULL_COLUMNS",
]

# --- Paths -----------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / "models" / "eta_model.joblib"

# --- Feature schema (mirrors scripts/train_eta.py) -------------------------

NUMERIC_COLUMNS = [
    "distance_km",
    "prep_time_min",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "traffic_factor",
]
ZONE_LETTERS = ("A", "B", "C", "D", "E")
ZONE_COLUMNS = [f"zone_{letter}" for letter in ZONE_LETTERS]
FULL_COLUMNS = NUMERIC_COLUMNS + ZONE_COLUMNS

# Zone reference anchors keyed by letter; a customer point maps to the letter
# whose anchor is nearest (used to one-hot encode the zone block). Anchored to
# five major metros so any pan-India delivery point snaps to a zone; the model
# schema stays a fixed 5 one-hot columns (A-E).
ZONE_ANCHORS = {
    "A": (28.6139, 77.2090),  # New Delhi
    "B": (19.0760, 72.8777),  # Mumbai
    "C": (12.9716, 77.5946),  # Bengaluru
    "D": (17.3850, 78.4867),  # Hyderabad
    "E": (13.0827, 80.2707),  # Chennai
}

# --- Model loading ---------------------------------------------------------


@lru_cache(maxsize=1)
def load_model() -> Optional[XGBRegressor]:
    """Load and cache the trained ETA model, or None if the file is missing.

    The result is cached, so the absence warning is printed at most once.
    Safe to call repeatedly: ``predict_eta`` and ``best_eta`` both use it.
    """
    if joblib is None:
        print("eta_service: joblib not installed — using formula fallback")
        return None
    if not MODEL_PATH.exists():
        print(
            "eta_service: models/eta_model.joblib not found — using formula fallback"
        )
        return None
    return joblib.load(MODEL_PATH)


# --- Pure helpers ----------------------------------------------------------


def _zone_vector(zone: str) -> list[float]:
    """Return the one-hot encoding for a zone letter, e.g. 'C' -> [0.0, 0.0, 1.0, 0.0, 0.0]."""
    return [1.0 if letter == zone else 0.0 for letter in ZONE_LETTERS]


def nearest_zone(lat: float, lng: float) -> str:
    """Return the zone letter whose anchor is nearest to (lat, lng)."""
    point = (lat, lng)
    return min(
        ZONE_LETTERS,
        key=lambda letter: tracking.haversine_km(point, ZONE_ANCHORS[letter]),
    )


def features_for_order(
    restaurant_id: int,
    distance_km: float,
    prep_time_min: float,
    customer_home: tuple[float, float] | None = None,
) -> dict:
    """Build the 7-key feature dict for an order at the current time.

    ``customer_home`` defaults to ``tracking.DEFAULT_CUSTOMER_HOME``; the zone
    is derived by snapping the home point to the nearest ``ZONE_ANCHORS``.
    Time fields come from a single ``datetime.now()`` snapshot: ``hour`` is the
    raw clock hour, ``day_of_week`` is Monday=0 .. Sunday=6, and ``is_weekend``
    is 1 on Saturday/Sunday.
    """
    home = tracking.DEFAULT_CUSTOMER_HOME if customer_home is None else customer_home
    now = datetime.now()
    day_of_week = now.weekday()
    return {
        "distance_km": distance_km,
        "prep_time_min": prep_time_min,
        "hour": now.hour,
        "day_of_week": day_of_week,
        "is_weekend": 1 if day_of_week in (5, 6) else 0,
        "traffic_factor": 1.0,
        "customer_zone": nearest_zone(*home),
    }


def predict_eta(features: dict) -> Optional[float]:
    """Predict delivery minutes from order features, or None without a model.

    Expected keys: ``distance_km``, ``prep_time_min``, ``hour``,
    ``day_of_week``, ``is_weekend``, ``traffic_factor``, ``customer_zone``.
    The vector is built in ``train_eta.FULL_COLUMNS`` order: the numeric block
    (``hour`` used raw as ``hour_of_day``) followed by the one-hot zone block,
    all as float to match the training pipeline's dtype.
    """
    model = load_model()
    if model is None:
        return None
    vector = [
        float(features["distance_km"]),
        float(features["prep_time_min"]),
        float(features["hour"]),  # hour -> hour_of_day (raw value)
        float(features["day_of_week"]),
        float(features["is_weekend"]),
        float(features["traffic_factor"]),
    ] + _zone_vector(features["customer_zone"])
    return float(model.predict([vector])[0])


def best_eta(
    route: list[tuple[float, float]],
    progress: float,
    restaurant_id: int,
    prep_time_min: float = 15,
    customer_home: Optional[tuple[float, float]] = None,
) -> tuple[float, str]:
    """Return (eta_minutes, source), preferring the ML model when available.

    With a model, predicts the full-trip minutes from route length and prep
    time, then scales by the remaining fraction ``1 - progress``. Without one,
    delegates to ``tracking.compute_eta``'s distance/speed formula.

    ``customer_home`` is the order's delivery point and feeds the zone
    one-hot encoding; it defaults to ``tracking.DEFAULT_CUSTOMER_HOME``.
    """
    if load_model() is None:
        return (
            tracking.compute_eta(route, progress, tracking.AVG_SPEED_KMH),
            "formula",
        )

    full_trip_feats = features_for_order(
        restaurant_id,
        distance_km=tracking.route_length_km(route),
        prep_time_min=prep_time_min,
        customer_home=customer_home,
    )
    ml_full = predict_eta(full_trip_feats)
    if ml_full is None:  # defensive: model vanished between checks
        return (
            tracking.compute_eta(route, progress, tracking.AVG_SPEED_KMH),
            "formula",
        )

    projected = ml_full * max(0.0, 1.0 - progress)
    return (round(projected, 1), "ml")
