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

from collections import namedtuple

from backend.db import SessionLocal  # noqa: E402
from backend.models import Order, Restaurant  # noqa: E402
from backend.tracking_state import restaurant_start  # noqa: E402

# The five columns live_orders_frame actually reads. Selecting columns instead
# of whole entities matters here: this scans the entire orders table on every
# retrain, and each row contributes five scalars.
_OrderPoint = namedtuple(
    "_OrderPoint", "id restaurant_id created_at delivery_lat delivery_lng"
)


def _zone_for_order(order, restaurant_point=None) -> Optional[str]:
    """Assign a delivery zone: the order's delivery point if known, else its
    restaurant's zone, else None (order is skipped).

    ``restaurant_point`` is the restaurant's coordinates when the caller already
    has them, which keeps the whole-table scan below from lazy-loading
    ``order.restaurant`` once per order.
    """
    if order.delivery_lat is not None and order.delivery_lng is not None:
        return eta_service.nearest_zone(order.delivery_lat, order.delivery_lng)
    try:
        lat, lng = restaurant_start(order, restaurant_point)
        return eta_service.nearest_zone(lat, lng)
    except ValueError:
        return None


def live_orders_frame() -> pd.DataFrame:
    """Convert live DB orders into the same columns as data/orders.csv."""
    rows = []
    db = SessionLocal()
    try:
        # One query for every restaurant with coordinates. Orders without a
        # delivery point fall back to their restaurant's zone, and leaving that
        # relationship lazy cost one SELECT per such order.
        restaurant_points = {
            rid: (lat, lng)
            for rid, lat, lng in db.query(Restaurant.id, Restaurant.lat, Restaurant.lng).filter(
                Restaurant.lat.isnot(None), Restaurant.lng.isnot(None)
            )
        }
        orders = db.query(
            Order.id,
            Order.restaurant_id,
            Order.created_at,
            Order.delivery_lat,
            Order.delivery_lng,
        ).all()
        for order_id, restaurant_id, created_at, delivery_lat, delivery_lng in orders:
            order = _OrderPoint(order_id, restaurant_id, created_at, delivery_lat, delivery_lng)
            if order.created_at is None:
                continue
            zone = _zone_for_order(order, restaurant_points.get(order.restaurant_id))
            if zone is None:
                continue
            rows.append(
                {
                    "order_id": order.id,
                    "restaurant_id": order.restaurant_id,
                    "customer_zone": zone,
                    "distance_km": 0.0,
                    "hour": order.created_at.hour,
                    "day_of_week": order.created_at.weekday(),
                    "is_weekend": 1 if order.created_at.weekday() in (5, 6) else 0,
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
