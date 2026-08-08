"""
FoodAI - SHAP explainability service (pure module)
==================================================

Explains ETA predictions from the trained XGBoost model
(``models/eta_model.joblib``) with SHAP values, exposing pure, testable
helpers for surfacing which order features pushed a prediction up or down.

The feature pipeline mirrors ``scripts/train_eta.py`` exactly: the feature
vector is the numeric block

    [distance_km, prep_time_min, hour_of_day, day_of_week, is_weekend, traffic_factor]

followed by the one-hot customer-zone block

    [zone_A, zone_B, zone_C, zone_D, zone_E]

i.e. the exact column order of ``train_eta.FULL_COLUMNS`` (the input ``hour``
key is used raw as ``hour_of_day``, with ``hour_of_day`` accepted as an
alias). Keeping the pipeline in sync with ``eta_service.predict_eta``
guarantees the SHAP explanation refers to the same 11-feature vector the model
scores.

Design constraints
------------------
* Pure module: no streamlit/folium/plotly imports, so it can be imported from
  a plain ``python3`` REPL with no extra packages beyond ``numpy``, ``joblib``
  and the dependency-free ``tracking`` module.
* ``shap`` is imported lazily on first use and the ``TreeExplainer`` is cached
  in a module-level global, so ``import explain_service`` stays fast even when
  shap is missing.
* If the model file is missing or shap cannot be imported, ``explain_eta()``
  returns ``None`` — it never raises.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from eta_service import load_model  # reuse the lru_cached model loader

if TYPE_CHECKING:
    from shap import TreeExplainer

__all__ = ["explain_eta", "FEATURE_COLUMNS"]

# --- Feature schema (mirrors scripts/train_eta.py / eta_service.py) --------

FEATURE_COLUMNS = [
    "distance_km",
    "prep_time_min",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "traffic_factor",
    "zone_A",
    "zone_B",
    "zone_C",
    "zone_D",
    "zone_E",
]

ZONE_LETTERS = ("A", "B", "C", "D", "E")

# --- Explainer cache -------------------------------------------------------
# Built lazily on first successful use; a failed build (model missing or shap
# unavailable) is NOT cached, so a model that appears later is picked up.

_explainer: TreeExplainer | None = None


# --- Pure helpers ----------------------------------------------------------


def _zone_vector(zone: str) -> list[float]:
    """Return the one-hot encoding for a zone letter, e.g. 'C' -> [0.0, 0.0, 1.0, 0.0, 0.0]."""
    return [1.0 if letter == zone else 0.0 for letter in ZONE_LETTERS]


def _feature_row(features: dict) -> list[float]:
    """Build the 11-float feature vector in FEATURE_COLUMNS order.

    Mirrors ``eta_service.predict_eta``: ``hour`` is used raw as
    ``hour_of_day`` (with ``hour_of_day`` accepted as an alias key) and
    ``customer_zone`` is one-hot encoded into the zone block.
    """
    hour = features["hour"] if "hour" in features else features["hour_of_day"]
    return [
        float(features["distance_km"]),
        float(features["prep_time_min"]),
        float(hour),
        float(features["day_of_week"]),
        float(features["is_weekend"]),
        float(features["traffic_factor"]),
        *_zone_vector(features["customer_zone"]),
    ]


def _get_explainer() -> TreeExplainer | None:
    """Return the cached SHAP TreeExplainer, or None when it can't be built.

    ``shap`` is imported lazily on first call so importing this module stays
    fast even when shap is missing. The explainer is cached in the module
    global ``_explainer``; a failed build (model missing or shap unavailable)
    is not cached, so the next call retries and picks up a model that appears
    later.
    """
    global _explainer
    if _explainer is not None:
        return _explainer
    model = load_model()
    if model is None:
        return None
    try:
        import shap

        _explainer = shap.TreeExplainer(model)
    except ImportError:
        return None
    return _explainer


# --- Public API ------------------------------------------------------------


def explain_eta(features: dict) -> dict | None:
    """Explain an ETA prediction via SHAP values, or None without a model.

    Accepts the same feature dict as ``eta_service.predict_eta``:
    ``distance_km``, ``prep_time_min``, ``hour`` (or ``hour_of_day``),
    ``day_of_week``, ``is_weekend``, ``traffic_factor``, ``customer_zone``.

    Returns::

        {"base_value": float,
         "contributions": [{"feature": str, "value": float, "shap": float}, ...]}

    with one entry per ``FEATURE_COLUMNS`` (zone one-hots carry their actual
    0/1 value), sorted by ``abs(shap)`` descending. Returns ``None`` when the
    model file is missing or shap cannot be imported — never raises.
    """
    explainer = _get_explainer()
    if explainer is None:
        return None

    row = _feature_row(features)
    values = explainer.shap_values(np.asarray([row], dtype=float))
    shap_vector = np.asarray(values)[0]  # single-output regressor -> (11,)
    base_value = float(np.asarray(explainer.expected_value).flatten()[0])

    contributions = [
        {
            "feature": column,
            "value": float(row[index]),
            "shap": float(shap_vector[index]),
        }
        for index, column in enumerate(FEATURE_COLUMNS)
    ]
    contributions.sort(key=lambda item: abs(item["shap"]), reverse=True)
    return {"base_value": base_value, "contributions": contributions}
