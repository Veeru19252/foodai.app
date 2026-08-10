"""
FoodAI backend - retraining utilities
======================================
Admin-triggered retraining for the demand-forecast model. Reuses the exact
feature pipeline from ``scripts/train_forecast.py`` (imported from the repo
root ``scripts/`` directory) so training and inference can never drift: it
aggregates the historical corpus (``data/orders.csv``) plus every live order
in the database into a per-zone hourly demand series, retrains the XGBoost
model, and writes the same ``models/forecast_model.joblib`` +
``models/forecast_meta.json`` files that ``forecast_service.py`` loads at
prediction time.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import joblib
import pandas as pd

import eta_service

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "forecast_model.joblib"
META_PATH = ROOT / "models" / "forecast_meta.json"
METRICS_PATH = ROOT / "outputs" / "metrics_forecast.json"
CORPUS_PATH = ROOT / "data" / "orders.csv"

sys.path.insert(0, str(ROOT / "scripts"))
import train_forecast as trainer  # noqa: E402

from backend.db import SessionLocal  # noqa: E402
from backend.models import Order  # noqa: E402
from backend.tracking_state import restaurant_start  # noqa: E402


def _zone_for_order(order) -> Optional[str]:
    """Assign a delivery zone: the order's delivery point if known, else its
    restaurant's zone, else None (order is skipped)."""
    if order.delivery_lat is not None and order.delivery_lng is not None:
        return eta_service.nearest_zone(order.delivery_lat, order.delivery_lng)
    try:
        lat, lng = restaurant_start(order)
        return eta_service.nearest_zone(lat, lng)
    except ValueError:
        return None


def live_orders_frame() -> pd.DataFrame:
    """Convert live DB orders into the same columns as data/orders.csv."""
    rows = []
    db = SessionLocal()
    try:
        orders = db.query(Order).all()
        for o in orders:
            if o.created_at is None:
                continue
            zone = _zone_for_order(o)
            if zone is None:
                continue
            rows.append(
                {
                    "order_id": o.id,
                    "restaurant_id": o.restaurant_id,
                    "customer_zone": zone,
                    "distance_km": 0.0,
                    "hour": o.created_at.hour,
                    "day_of_week": o.created_at.weekday(),
                    "is_weekend": 1 if o.created_at.weekday() in (5, 6) else 0,
                    "prep_time_min": 0.0,
                    "traffic_factor": 1.0,
                    "delivery_min": 0.0,
                }
            )
    finally:
        db.close()
    return pd.DataFrame(rows)


def retrain_forecast() -> dict:
    """Retrain the demand model from the corpus + live orders.

    Returns metrics (XGBoost vs the moving-average baseline), the sample
    counts used, and the paths written, for the admin UI to display.
    """
    if not CORPUS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CORPUS_PATH}. Run scripts/simulate_orders.py first."
        )

    corpus = pd.read_csv(CORPUS_PATH)
    live = live_orders_frame()
    combined = pd.concat([corpus, live], ignore_index=True)

    demand = trainer.build_demand_series(combined)
    demand = trainer.add_lag_features(demand)

    train, test = trainer.time_ordered_split(demand, trainer.TEST_SIZE)

    X_train = trainer.make_features(train)
    y_train = train["order_count"].astype(float)
    X_test = trainer.make_features(test)
    y_test = test["order_count"].astype(float)

    model = trainer.train_xgboost(X_train, y_train)
    metrics = trainer.collect_metrics(y_test, X_test, test, model)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    meta = {
        "feature_columns": trainer.FEATURE_COLUMNS,
        "zones": list(trainer.ZONES),
    }
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "model_path": str(MODEL_PATH),
        "samples": {
            "corpus": len(corpus),
            "live": len(live),
            "total": len(combined),
        },
        "demand_buckets": int(len(demand)),
        "metrics": metrics,
        "retrained_at": datetime.utcnow().isoformat() + "Z",
    }
