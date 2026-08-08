"""
FoodAI - Demand forecasting service (pure module)
=================================================

Loads the trained XGBoost demand model (``models/forecast_model.joblib``) and
the schema metadata (``models/forecast_meta.json``), then exposes pure,
testable helpers for predicting next-hour order counts per customer zone.

This module mirrors the feature pipeline in ``scripts/train_forecast.py``
exactly: the feature vector is the temporal block

    [hour_of_day, day_of_week, is_weekend, prev_1h, prev_3h_avg]

followed by the one-hot customer-zone block

    [zone_A, zone_B, zone_C, zone_D, zone_E]

The column order is read from ``forecast_meta.json`` (written by the training
script as ``FEATURE_COLUMNS``) and the vector is built by iterating that list,
so inference stays in sync with the training schema even if it changes. When
the metadata is missing, a hardcoded ``DEFAULT_FEATURE_COLUMNS`` (equal to the
current training schema) is used.

Design constraints
------------------
* Pure module: no streamlit/folium imports and no database access, so it can
  be imported from a plain ``python3`` REPL with no extra packages beyond
  ``joblib`` (``xgboost`` is only needed to run the model, and only referenced
  under TYPE_CHECKING for annotations).
* If the model file is missing, ``load_model()`` prints a one-time warning and
  ``predict_next_hour()`` returns ``None``; ``forecast_all_zones()`` then
  falls back to each zone's ``prev_3h_avg`` (moving average) so callers never
  crash. ``load_meta()`` similarly warns once and returns ``None``, causing
  the default feature schema / zone list to be used.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import joblib

if TYPE_CHECKING:
    from xgboost import XGBRegressor

__all__ = [
    "load_model",
    "load_meta",
    "predict_next_hour",
    "forecast_all_zones",
]

# --- Paths -----------------------------------------------------------------

# forecast_service.py lives at the repo root (like eta_service.py), so the
# project root is this file's parent directory.
ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / "models" / "forecast_model.joblib"
META_PATH = ROOT / "models" / "forecast_meta.json"

# --- Feature schema (mirrors scripts/train_forecast.py) --------------------

DEFAULT_ZONES = ("A", "B", "C", "D", "E")
DEFAULT_FEATURE_COLUMNS = [
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "prev_1h",
    "prev_3h_avg",
] + [f"zone_{letter}" for letter in DEFAULT_ZONES]

# Columns that are not ``zone_*`` are temporal and map 1:1 from the features
# dict (see ``_feature_vector``).
_ZONE_PREFIX = "zone_"

# --- One-time warning guards ----------------------------------------------
# The lru_cache already limits body execution, but the flags make the
# "print once" guarantee explicit even if the cache were cleared.

_model_warning_shown = False
_meta_warning_shown = False

# --- Model / metadata loading ---------------------------------------------


@lru_cache(maxsize=1)
def load_model() -> XGBRegressor | None:
    """Load and cache the trained forecast model, or None if the file is missing.

    The result is cached, so the absence warning is printed at most once.
    Safe to call repeatedly: ``predict_next_hour`` and ``forecast_all_zones``
    both use it.
    """
    global _model_warning_shown
    if not MODEL_PATH.exists():
        if not _model_warning_shown:
            print(
                "forecast_service: models/forecast_model.joblib not found "
                "— falling back to moving average"
            )
            _model_warning_shown = True
        return None
    return joblib.load(MODEL_PATH)


@lru_cache(maxsize=1)
def load_meta() -> dict | None:
    """Load and cache the training schema metadata, or None if the file is missing.

    Returns the dict written by ``scripts/train_forecast.py``::

        {"feature_columns": [...], "zones": [...]}

    When the file is missing a one-time warning is printed and ``None`` is
    returned, prompting callers to fall back to ``DEFAULT_FEATURE_COLUMNS`` /
    ``DEFAULT_ZONES``.
    """
    global _meta_warning_shown
    if not META_PATH.exists():
        if not _meta_warning_shown:
            print(
                "forecast_service: models/forecast_meta.json not found "
                "— using default feature schema"
            )
            _meta_warning_shown = True
        return None
    with META_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


# --- Pure helpers ----------------------------------------------------------


def _meta_columns() -> list[str]:
    """Return feature_columns from metadata, or DEFAULT_FEATURE_COLUMNS."""
    meta = load_meta()
    if (
        meta is not None
        and isinstance(meta.get("feature_columns"), list)
        and meta["feature_columns"]
    ):
        return list(meta["feature_columns"])
    return list(DEFAULT_FEATURE_COLUMNS)


def _zones() -> list[str]:
    """Return zone letters from metadata, or DEFAULT_ZONES."""
    meta = load_meta()
    if meta is not None and isinstance(meta.get("zones"), list) and meta["zones"]:
        return list(meta["zones"])
    return list(DEFAULT_ZONES)


def _feature_vector(features: dict, feature_columns: list[str]) -> list[float]:
    """Build a fixed-width float vector in ``feature_columns`` order.

    Temporal columns are copied straight from the ``features`` dict (defaulting
    to 0.0 when absent); ``zone_*`` columns are one-hot from the
    ``customer_zone`` key. Iterating the columns list guarantees the exact
    order the model was trained on, even if the schema changes.
    """
    zone = features["customer_zone"]
    vector: list[float] = []
    for column in feature_columns:
        if column.startswith(_ZONE_PREFIX):
            vector.append(1.0 if zone == column[len(_ZONE_PREFIX):] else 0.0)
        else:
            vector.append(float(features.get(column, 0.0)))
    return vector


def _zone_history(zone: str, prev_counts_by_zone: dict) -> list[float]:
    """Return the previous hourly counts for a zone, most recent last.

    Accepts either a scalar count (``{"A": 4}``) or a list of hourly counts
    (``{"A": [2, 3, 4]}``). Every value is clamped to >= 0.
    """
    raw = prev_counts_by_zone.get(zone, [])
    if isinstance(raw, (list, tuple)):
        values: list = list(raw)
    else:
        values = [raw] if raw is not None else []
    return [max(0.0, float(value)) for value in values]


# --- Public API ------------------------------------------------------------


def predict_next_hour(features: dict) -> float | None:
    """Predict the next-hour order count for a zone, or None without a model.

    Expected keys: ``hour_of_day``, ``day_of_week``, ``is_weekend``,
    ``prev_1h``, ``prev_3h_avg``, ``customer_zone``. The vector is built by
    iterating the ``feature_columns`` from metadata (the training schema), so
    column order always matches the model. Predictions are clamped to >= 0.
    """
    model = load_model()
    if model is None:
        return None
    vector = _feature_vector(features, _meta_columns())
    prediction = float(model.predict([vector])[0])
    return max(0.0, prediction)


def forecast_all_zones(
    hour: int, day_of_week: int, is_weekend: int, prev_counts_by_zone: dict
) -> dict[str, float]:
    """Predict next-hour demand for every zone: {zone_letter: count}.

    For each zone, ``prev_1h`` is the most recent available count and
    ``prev_3h_avg`` is the mean of the last 3 available counts (or fewer;
    0 when the zone has no history). Each zone is scored with
    ``predict_next_hour``; if the model is missing that returns ``None`` and
    the zone's ``prev_3h_avg`` (moving average) is used instead, so this
    function never crashes without a model. All counts are clamped to >= 0.
    """
    result: dict[str, float] = {}
    for zone in _zones():
        history = _zone_history(zone, prev_counts_by_zone)
        prev_1h = history[-1] if history else 0.0
        window = history[-3:]
        prev_3h_avg = sum(window) / len(window) if window else 0.0

        prediction = predict_next_hour(
            {
                "hour_of_day": hour,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend,
                "prev_1h": prev_1h,
                "prev_3h_avg": prev_3h_avg,
                "customer_zone": zone,
            }
        )
        if prediction is None:  # model missing -> moving-average fallback
            prediction = prev_3h_avg
        result[zone] = max(0.0, float(prediction))
    return result
