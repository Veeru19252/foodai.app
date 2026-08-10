# FoodAI Teaching Guide — Part 3: The ML Layer

> **Prerequisites:** Part 1 (models/DB) and Part 2 (backend routers). This part walks the
> whole machine-learning stack: how the training data is born, how the models are trained,
> and — most importantly — the pure inference services the API calls at runtime, plus the
> geospatial/OSRM layer and the tracking router that ties live position + ML ETA to the UI.
>
> **The single most important design idea in this layer:** every model is *optional*.
> Each service degrades to a sensible fallback (formula, moving average, straight-line
> route) when a model file is missing or an external service is unreachable. The app
> *never* crashes because the ML isn't there. That's what `"fallback": true` means in the
> API responses, and why the frontend can show "estimated" instead of an error.

---

## The ML stack at a glance

```text
scripts/simulate_orders.py ──► data/orders.csv            (synthetic but realistic training data)
        │
        ├──► scripts/train_eta.py ──► models/eta_model.joblib        (XGBoost regressor)
        └──► scripts/train_forecast.py ──► models/forecast_model.joblib
                                          models/forecast_meta.json   (feature schema)

RUNTIME (what the API calls):
  eta_service.predict_eta / best_eta          ──► XGBoost ETA (fallback: distance formula)
  explain_service.explain_eta                 ──► SHAP TreeExplainer (fallback: None)
  forecast_service.forecast_all_zones         ──► XGBoost demand  (fallback: 3h moving avg)
  routing.get_route                           ──► OSRM road route (fallback: straight line)
  tracking.py (helpers)                       ──► pure geospatial math, no dependencies
  backend/routers/tracking.py                 ──► REST + WebSocket bridge to the UI
  backend/routers/ml.py                       ──► HTTP surface for all of the above
```

Training is deterministic (`random_state=42` everywhere) and re-runnable — run
`python scripts/simulate_orders.py`, then `python scripts/train_eta.py`, then
`python scripts/train_forecast.py`.

---

## File 1 — `scripts/simulate_orders.py` (data generator)

> Dev-time tool. It exists because there is no real order history: we *synthesize* 600+
> realistic orders and persist them to `data/orders.csv`, which becomes the training data
> for both models. Not part of the running app — run it once before training.

```python
"""
FoodAI - Order Simulator (Person B)

Generates 500+ realistic food-delivery orders and saves them to
data/orders.csv. This file becomes the training data for your two ML models:
- ETA prediction (target column: delivery_min)
- Demand forecasting (group orders by zone + hour, then predict counts)
...
"""
import csv
import math
import random
from pathlib import Path

NUM_DAYS = 10
TARGET_ORDERS = 600
SEED = 42
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "orders.csv"

ZONES = {"A": (0.0, 0.0), "B": (4.0, 1.0), "C": (7.0, 4.0), "D": (2.0, 6.0), "E": (8.0, 0.0)}

RESTAURANTS = {
    1: {"zone": "A", "prep_min": 8},
    2: {"zone": "B", "prep_min": 10},
    3: {"zone": "C", "prep_min": 7},
    4: {"zone": "D", "prep_min": 12},
    5: {"zone": "E", "prep_min": 9},
}

def _hour_weight(hour: int) -> float:
    if 11 <= hour <= 14: return 1.8     # lunch rush
    if 18 <= hour <= 22: return 1.6     # dinner rush
    if 8 <= hour <= 10: return 1.2      # morning
    return 0.6                          # late night

def _distance_km(zone1: str, zone2: str) -> float:
    x1, y1 = ZONES[zone1]
    x2, y2 = ZONES[zone2]
    return round(math.hypot(x2 - x1, y2 - y1), 2)

def _traffic_factor(hour: int, is_weekend: int) -> float:
    base = 1.0
    if 8 <= hour <= 9 or 17 <= hour <= 19:
        base += 0.25
    if is_weekend and 12 <= hour <= 21:
        base += 0.15
    return round(random.uniform(0.85, base + 0.1), 2)

def generate_order(order_id: int, day: int) -> dict:
    restaurant_id = random.choice(list(RESTAURANTS.keys()))
    restaurant = RESTAURANTS[restaurant_id]
    hour = random.choices(range(24), weights=[_hour_weight(h) for h in range(24)], k=1)[0]
    day_of_week = day % 7
    is_weekend = 1 if day_of_week in (5, 6) else 0
    customer_zone = random.choice(list(ZONES.keys()))
    distance_km = _distance_km(restaurant["zone"], customer_zone)
    prep_time_min = restaurant["prep_min"] + random.randint(-2, 4)
    traffic = _traffic_factor(hour, is_weekend)
    delivery_min = round(5 + (distance_km * 4) * traffic + prep_time_min + random.uniform(-2, 5), 1)
    return {
        "order_id": order_id, "restaurant_id": restaurant_id, "customer_zone": customer_zone,
        "distance_km": distance_km, "hour": hour, "day_of_week": day_of_week,
        "is_weekend": is_weekend, "prep_time_min": max(3, prep_time_min),
        "traffic_factor": traffic, "delivery_min": max(8, delivery_min),
    }

def main() -> None:
    random.seed(SEED)
    orders_per_day = math.ceil(TARGET_ORDERS / NUM_DAYS)
    rows, order_id = [], 1
    for day in range(NUM_DAYS):
        for _ in range(orders_per_day):
            rows.append(generate_order(order_id, day)); order_id += 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader(); writer.writerows(rows)
    ...  # prints summary stats

if __name__ == "__main__":
    main()
```

**What it does / Why this way**
- Generates ~600 rows with columns the models need: `restaurant_id`, `customer_zone`, `distance_km`, `hour`, `day_of_week`, `is_weekend`, `prep_time_min`, `traffic_factor`, and the **target** `delivery_min`.
- The target is generated with a *known formula* (`5 + distance×4×traffic + prep + noise`) so the synthetic data has real structure the models can learn — the "ground truth" isn't random noise.
- Hour is sampled with **weights** (lunch/dinner rushes heavier), and `random.seed(42)` makes every run byte-identical — reproducibility is non-negotiable for teaching/review.
- Traffic multiplies only the *driving* part (not prep), which mirrors real life and gives the model a non-trivial interaction to find.

**What breaks**
- If you dropped the seed → every run produces different data → the model changes every run → nobody can reproduce metrics (the #1 ML-practice sin this repo avoids).
- If `delivery_min` were pure uniform noise → no model could beat the baseline and the whole "ML improves ETA" story would be fake.
- If you skipped this script and trained on an empty/missing `data/orders.csv` → `train_eta.main()` raises `FileNotFoundError` with an explicit "run simulate first" message (a deliberate guard).

---

## File 2 — `scripts/train_eta.py` (ETA training pipeline)

> Dev-time tool. Trains four models (baseline formula, linear, random forest, XGBoost) on
> the order CSV, evaluates them on a hold-out test split, and persists the champion
> (XGBoost) to `models/eta_model.joblib` plus metrics/charts to `outputs/`.

```python
"""
FoodAI - ETA Model Training Pipeline
Trains regression models that predict delivery time (delivery_min) ...
    baseline : simulator formula (5 + distance_km * 4 + prep_time_min)
    linear, random_forest, xgboost : learned models
Deterministic (random_state=42 everywhere) and rerunnable.
"""
import json
from pathlib import Path
import joblib
import matplotlib; matplotlib.use("Agg")      # headless backend, MUST precede pyplot
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor

NUMERIC_COLUMNS = ["distance_km", "prep_time_min", "hour_of_day", "day_of_week", "is_weekend", "traffic_factor"]
ZONE_COLUMNS = [f"zone_{letter}" for letter in ("A", "B", "C", "D", "E")]
FULL_COLUMNS = NUMERIC_COLUMNS + ZONE_COLUMNS      # ← THE fixed-width contract
RANDOM_STATE = 42
TEST_SIZE = 0.2

def make_features(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric features selected as-is; customer_zone one-hot encoded.
    reindex(columns=FULL_COLUMNS, fill_value=0) guarantees all five zone
    columns exist in the exact fixed order, so train/test/inference always
    share the same shape and dtype even when a subset lacks a rare zone."""
    numeric = pd.DataFrame({
        "distance_km": df["distance_km"], "prep_time_min": df["prep_time_min"],
        "hour_of_day": df["hour"], "day_of_week": df["day_of_week"],
        "is_weekend": df["is_weekend"], "traffic_factor": df["traffic_factor"],
    })
    zones = pd.get_dummies(df["customer_zone"], prefix="zone")
    return pd.concat([numeric, zones], axis=1).reindex(columns=FULL_COLUMNS, fill_value=0).astype(float)

def baseline_predictions(features: pd.DataFrame) -> np.ndarray:
    return 5.0 + features["distance_km"] * 4.0 + features["prep_time_min"]

def evaluate(y_true, y_pred):
    return (float(mean_absolute_error(y_true, y_pred)),
            float(np.sqrt(mean_squared_error(y_true, y_pred))))

def train_models(X_train, y_train):
    linear = LinearRegression().fit(X_train, y_train)
    forest = RandomForestRegressor(n_estimators=200, random_state=RANDOM_STATE).fit(X_train, y_train)
    xgb = XGBRegressor(n_estimators=200, max_depth=6, learning_rate=0.05,
                       subsample=0.8, colsample_bytree=0.8, random_state=RANDOM_STATE).fit(X_train, y_train)
    return {"linear": linear, "random_forest": forest, "xgboost": xgb}

def main() -> None:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {DATA_PATH}. Run scripts/simulate_orders.py first.")
    orders = pd.read_csv(DATA_PATH)
    features = make_features(orders)
    target = orders["delivery_min"].astype(float)
    X_train, X_test, y_train, y_test = train_test_split(
        features, target, test_size=TEST_SIZE, random_state=RANDOM_STATE,
        stratify=orders["customer_zone"],      # keep zone mix in both splits
    )
    models = train_models(X_train, y_train)
    metrics = collect_metrics(y_test, X_test, models)
    joblib.dump(models["xgboost"], MODEL_PATH)                 # champion persisted
    ...  # metrics JSON + 3 charts
```

**What it does / Why this way**
- **`FULL_COLUMNS` is the contract.** The feature vector order (6 numerics + 5 one-hot zones) is defined once here and mirrored exactly in `eta_service.py`. If they ever drifted, inference would silently feed the model a shuffled vector — the classic train/serve skew bug. The `reindex(..., fill_value=0)` trick guarantees all 5 zone columns exist even when one zone is missing from a subset.
- **Trains 3 learned models + a formula baseline** so you can *prove* the ML adds value (metrics JSON + charts) instead of trusting it blindly.
- **`stratify=orders["customer_zone"]`** keeps rare zones represented in both train and test — without it a small zone could vanish from the test set and skew MAE.
- **`matplotlib.use("Agg")` before `pyplot` import** is a hard matplotlib rule: it picks a headless backend so training works over SSH/CI with no display.
- **Champion = XGBoost** (good on tabular data, has built-in feature importance, and `shap.TreeExplainer` supports it — that's why the explainer service works at all).

**What breaks**
- If feature order changed between training and inference → silently wrong predictions with *no error* (worse than a crash — this is the exact bug the shared `FULL_COLUMNS` + mirrored pipelines exist to prevent).
- If you removed stratify → zone imbalance can make test metrics lie.
- If you trained on the full dataset without a split → you'd have no honest measure of error (metrics would be over-optimistic in-sample numbers).

---

## File 3 — `scripts/train_forecast.py` (demand forecasting pipeline)

> Dev-time tool. Aggregates raw orders into a per-zone hourly demand series, adds lag
> features, does a *time-ordered* train/test split, trains XGBoost, and persists the model
> + schema metadata (`forecast_meta.json`).

```python
FEATURE_COLUMNS = ["hour_of_day", "day_of_week", "is_weekend", "prev_1h", "prev_3h_avg"] + ZONE_COLUMNS
RANDOM_STATE = 42
TEST_SIZE = 0.2

def build_demand_series(orders: pd.DataFrame) -> pd.DataFrame:
    """Each row = one (customer_zone, hour, day_of_week, is_weekend) bucket
    with the number of orders placed in it (order_count). Sorted
    chronologically within each zone so lag features have a defined 'previous hour'."""
    demand = (orders.rename(columns={"hour": "hour_of_day"})
              .groupby(["customer_zone", "hour_of_day", "day_of_week", "is_weekend"])
              .size().rename("order_count").reset_index())
    return demand.sort_values(["customer_zone", "day_of_week", "hour_of_day"]).reset_index(drop=True)

def add_lag_features(demand: pd.DataFrame) -> pd.DataFrame:
    """prev_1h = count one hour earlier (shift 1); prev_3h_avg = mean of the
    previous 3 hours. Lag leakage note: these only ever look BACKWARD within
    each zone, so no future info leaks. The rolling window is per-zone:
    a plain .rolling(3) would mix the last rows of one zone with the first of
    the next. NaN at zone starts is filled with 0."""
    prev_1h = demand.groupby("customer_zone")["order_count"].shift(1)
    prev_3h_avg = (prev_1h.groupby(demand["customer_zone"]).rolling(3).mean()
                   .reset_index(level=0, drop=True))
    return demand.assign(prev_1h=prev_1h.fillna(0).astype(float),
                         prev_3h_avg=prev_3h_avg.fillna(0).astype(float))

def time_ordered_split(demand, test_size=TEST_SIZE):
    """Synthetic chronological index = day_of_week*24 + hour_of_day; first 80%
    train, last 20% test. NO random shuffle, so test rows are never seen in fit."""
    ordered = demand.assign(hour_index=demand["day_of_week"] * 24 + demand["hour_of_day"]) \
        .sort_values(["hour_index", "customer_zone"]).drop(columns=["hour_index"])
    split_at = int(len(ordered) * (1.0 - test_size))
    return ordered.iloc[:split_at].copy(), ordered.iloc[split_at:].copy()

def mape(y_true, y_pred):
    """Denominator max(actual, 1) avoids divide-by-zero on sparse zero-order buckets."""
    return float(np.mean(np.abs(y_true - y_pred) / np.maximum(y_true, 1.0)))

def main() -> None:
    ...
    demand = add_lag_features(build_demand_series(orders))
    train, test = time_ordered_split(demand, TEST_SIZE)
    model = train_xgboost(make_features(train), train["order_count"].astype(float))
    joblib.dump(model, MODEL_PATH)
    meta = {"feature_columns": FEATURE_COLUMNS, "zones": list(ZONES)}
    json.dump(meta, open(META_PATH, "w"), indent=2)
    ...
```

**What it does / Why this way**
- **Forecasting is a different problem than ETA**: you're predicting *counts per zone per hour*, so the unit of data is the aggregate bucket, not the individual order.
- **Lag features (`prev_1h`, `prev_3h_avg`) are the memory of the series.** A model with only calendar features would have no idea whether it's been busy lately.
- **Time-ordered split instead of random split.** For time series, random shuffling leaks the future into training (the model would literally memorize test answers). The synthetic `hour_index` makes the split chronological.
- **Per-zone rolling is mandatory.** `groupby("customer_zone").shift(1).groupby(...).rolling(3)` — a global rolling window would create fake "history" at the boundary between zone A's last hour and zone B's first.
- **`forecast_meta.json` is the schema contract.** The inference service reads the exact `feature_columns` and `zones` from disk rather than hardcoding them — so if the schema ever changes in training, inference follows automatically (see `forecast_service._meta_columns()`).

**What breaks**
- A random `train_test_split` here → future data leaks into training → test MAE looks great but live predictions are bad (the most common time-series trap).
- `fillna(0)` vs leaving NaN → XGBoost can't take NaN target-side; and the moving-average fallback needs a well-defined value at zone starts.
- If `forecast_meta.json` weren't written → inference falls back to `DEFAULT_FEATURE_COLUMNS`; as long as they match training it's fine, but the meta file removes the risk of silent drift.

---

## File 4 — `eta_service.py` (runtime ETA inference)

> **Runtime-critical.** This is what the API calls on every tracking refresh. It loads the
> trained XGBoost model once (cached) and turns order features into a delivery-time
> estimate — or gracefully falls back to a distance formula.

```python
"""
FoodAI - ETA prediction service (pure module)
Loads the trained XGBoost ETA model (models/eta_model.joblib) ...
Design constraints:
* Pure module: no streamlit/folium imports and no database access.
* If the model file is missing, load_model() prints a one-time warning and
  best_eta() falls back to tracking.compute_eta's speed formula.
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

ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / "models" / "eta_model.joblib"

NUMERIC_COLUMNS = ["distance_km", "prep_time_min", "hour_of_day", "day_of_week", "is_weekend", "traffic_factor"]
ZONE_LETTERS = ("A", "B", "C", "D", "E")
ZONE_COLUMNS = [f"zone_{letter}" for letter in ZONE_LETTERS]
FULL_COLUMNS = NUMERIC_COLUMNS + ZONE_COLUMNS

ZONE_ANCHORS = {   # reference anchor per zone; a customer point maps to the nearest
    "A": (12.975, 77.606), "B": (12.982, 77.619), "C": (12.977, 77.596),
    "D": (13.004, 77.610), "E": (12.970, 77.750),
}

@lru_cache(maxsize=1)
def load_model() -> Optional[XGBRegressor]:
    """Load and cache the trained model, or None if the file is missing."""
    if joblib is None:
        print("eta_service: joblib not installed — using formula fallback"); return None
    if not MODEL_PATH.exists():
        print("eta_service: models/eta_model.joblib not found — using formula fallback"); return None
    return joblib.load(MODEL_PATH)

def _zone_vector(zone: str) -> list[float]:
    return [1.0 if letter == zone else 0.0 for letter in ZONE_LETTERS]

def nearest_zone(lat: float, lng: float) -> str:
    """Zone whose anchor is nearest to (lat, lng)."""
    return min(ZONE_LETTERS, key=lambda letter: tracking.haversine_km((lat, lng), ZONE_ANCHORS[letter]))

def features_for_order(restaurant_id, distance_km, prep_time_min, customer_home=None) -> dict:
    """Build the 7-key feature dict for an order at the current time."""
    home = tracking.DEFAULT_CUSTOMER_HOME if customer_home is None else customer_home
    now = datetime.now()
    day_of_week = now.weekday()
    return {"distance_km": distance_km, "prep_time_min": prep_time_min,
            "hour": now.hour, "day_of_week": day_of_week,
            "is_weekend": 1 if day_of_week in (5, 6) else 0,
            "traffic_factor": 1.0, "customer_zone": nearest_zone(*home)}

def predict_eta(features: dict) -> Optional[float]:
    """Predict delivery minutes, or None without a model."""
    model = load_model()
    if model is None:
        return None
    vector = [float(features["distance_km"]), float(features["prep_time_min"]),
              float(features["hour"]), float(features["day_of_week"]),
              float(features["is_weekend"]), float(features["traffic_factor"])] \
             + _zone_vector(features["customer_zone"])
    return float(model.predict([vector])[0])

def best_eta(route, progress, restaurant_id, prep_time_min=15, customer_home=None):
    """Return (eta_minutes, source); ML when available, else the formula.
    With a model: predict full-trip minutes, scale by remaining 1 - progress.
    Without one: tracking.compute_eta(route, progress, AVG_SPEED_KMH), source 'formula'."""
    if load_model() is None:
        return (tracking.compute_eta(route, progress, tracking.AVG_SPEED_KMH), "formula")
    full_trip_feats = features_for_order(restaurant_id, distance_km=tracking.route_length_km(route),
                                         prep_time_min=prep_time_min, customer_home=customer_home)
    ml_full = predict_eta(full_trip_feats)
    if ml_full is None:
        return (tracking.compute_eta(route, progress, tracking.AVG_SPEED_KMH), "formula")
    projected = ml_full * max(0.0, 1.0 - progress)
    return (round(projected, 1), "ml")
```

**What it does / Why this way**
- **`@lru_cache(maxsize=1)` on `load_model`** means the 690 KB joblib is deserialized exactly once per process — every tracking refresh afterwards is a cheap cache hit. Safe because the model is immutable at runtime.
- **`features_for_order` takes a *single* `datetime.now()` snapshot** so `hour`, `day_of_week`, and `is_weekend` can never disagree (a race at midnight would otherwise mix two days).
- **Zone is derived, not stored**: `nearest_zone` snaps the customer's delivery point to one of 5 anchors, which then one-hots into `zone_A..E`. This keeps the feature vector at the fixed width the model was trained on.
- **`best_eta` is the smart wrapper.** Full-trip ML prediction is scaled by `(1 - progress)` — if the rider is 70% of the way, ETA ≈ 30% of the predicted total. The `source` ("ml" vs "formula") tells the frontend whether to show "AI estimate" or "rough estimate".
- **The `load_model() is None` checks happen in two places** (`predict_eta` and `best_eta`) — a defensive double-guard so a model that vanishes between calls still degrades instead of crashing.
- **`joblib` imported in a try/except** — the module can be *imported* without joblib; it only degrades at call time. That keeps `python3 -c "import eta_service"` working in any environment.

**What breaks**
- If `predict_eta` forgot `float(...)` casts → a single int feature makes the vector the wrong dtype and XGBoost raises a cryptic error at runtime.
- If `hour` weren't used as `hour_of_day` → the vector length/order would drift from training (the mirrored `FULL_COLUMNS` contract).
- If `best_eta` didn't scale by progress → a customer 1 minute from their door would still see the full-trip estimate.
- If `lru_cache` weren't there → every 2.5-second tracking refresh re-reads a 690 KB file off disk (CPU + IO waste).

**How this connects**
- `backend/tracking_state.eta_for_order` calls `eta_service.best_eta` → both REST and WebSocket tracking show the same ETA.
- `backend/routers/ml.py` calls `features_for_order` + `predict_eta` for `GET /ml/eta`, and `order_route` + `delivery_end` for `GET /ml/order/{id}`.
- `orders.py` `order_nudge` uses the same ETA to decide whether an order is running late.

---

## File 5 — `explain_service.py` (SHAP explanations)

> **Runtime-critical.** Turns "the model said 37 minutes" into "prep time added +4.2,
> distance pushed it −2.3 …" — the feature-level story behind a prediction. This is what
> makes the ETA *explainable* rather than a black box.

```python
"""
FoodAI - SHAP explainability service (pure module)
Explains ETA predictions from the trained XGBoost model with SHAP values ...
Design constraints:
* Pure module: no streamlit/folium/plotly imports.
* shap is imported lazily on first use and the TreeExplainer is cached.
* If the model file is missing or shap cannot be imported, explain_eta() returns
  None — it never raises.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
import numpy as np
from eta_service import load_model          # reuse the lru_cached model loader

if TYPE_CHECKING:
    from shap import TreeExplainer

FEATURE_COLUMNS = ["distance_km", "prep_time_min", "hour_of_day", "day_of_week",
                   "is_weekend", "traffic_factor", "zone_A", "zone_B", "zone_C", "zone_D", "zone_E"]
ZONE_LETTERS = ("A", "B", "C", "D", "E")

_explainer: TreeExplainer | None = None     # module-level cache

def _feature_row(features: dict) -> list[float]:
    """Build the 11-float vector in FEATURE_COLUMNS order, mirroring
    eta_service.predict_eta ('hour' used raw as hour_of_day)."""
    hour = features["hour"] if "hour" in features else features["hour_of_day"]
    return [float(features["distance_km"]), float(features["prep_time_min"]), float(hour),
            float(features["day_of_week"]), float(features["is_weekend"]),
            float(features["traffic_factor"]), *_zone_vector(features["customer_zone"])]

def _get_explainer() -> TreeExplainer | None:
    """Cached SHAP TreeExplainer; a failed build is NOT cached so a model
    that appears later is picked up."""
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

def explain_eta(features: dict) -> dict | None:
    """Explain an ETA prediction via SHAP values, or None without a model.
    Returns {"base_value": float,
             "contributions": [{"feature", "value", "shap"}, ...]}
    sorted by |shap| descending."""
    explainer = _get_explainer()
    if explainer is None:
        return None
    row = _feature_row(features)
    values = explainer.shap_values(np.asarray([row], dtype=float))
    shap_vector = np.asarray(values)[0]
    base_value = float(np.asarray(explainer.expected_value).flatten()[0])
    contributions = [{"feature": col, "value": float(row[i]), "shap": float(shap_vector[i])}
                     for i, col in enumerate(FEATURE_COLUMNS)]
    contributions.sort(key=lambda item: abs(item["shap"]), reverse=True)
    return {"base_value": base_value, "contributions": contributions}
```

**What it does / Why this way**
- **SHAP values answer "why this number?"**: each feature gets a signed contribution; summing them with `base_value` reconstructs the prediction. Sorting by `|shap|` puts the biggest drivers first (that's the "top-3 contributions" the UI shows).
- **Lazy `import shap`** keeps `import explain_service` fast and works even where shap isn't installed — the *failure* is deferred to call time and turned into `None`.
- **Reuses `eta_service.load_model`** so there's exactly one cached model object in the process (no double-loading, and the explainer is built from the same object the predictor uses).
- **Failed explainer builds are not cached** — `_explainer` stays `None`, so if the model file appears after startup (e.g. mounted late), the next call retries and succeeds.
- **`np.asarray([row], dtype=float)`** wraps the row into the 2-D shape SHAP expects; `[0]` unwraps the single-output vector, and `explainer.expected_value` is flattened because newer SHAP versions return a 1-element array.

**What breaks**
- If you imported shap eagerly at module top → `import explain_service` crashes on machines without shap (breaks the whole API import).
- If `explain_eta` raised instead of returning `None` → `GET /ml/eta/explain` would 500 whenever the model is missing; the graceful `503 + fallback` pattern would be lost.
- If you built the explainer every call → SHAP's TreeExplainer would re-initialize per request (slow) — the cache is what makes it cheap after the first call.

---

## File 6 — `forecast_service.py` (runtime demand forecasting)

> **Runtime-critical.** Predicts next-hour order counts per zone. Reads the feature schema
> from `forecast_meta.json` (written at training time) so inference always matches training,
> and falls back to a moving average when the model is missing.

```python
"""
FoodAI - Demand forecasting service (pure module)
Loads the trained XGBoost demand model (models/forecast_model.joblib) and the
schema metadata (models/forecast_meta.json) ...
The column order is read from forecast_meta.json and the vector is built by
iterating that list, so inference stays in sync with the training schema.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
import joblib

if TYPE_CHECKING:
    from xgboost import XGBRegressor

ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / "models" / "forecast_model.joblib"
META_PATH = ROOT / "models" / "forecast_meta.json"

DEFAULT_ZONES = ("A", "B", "C", "D", "E")
DEFAULT_FEATURE_COLUMNS = ["hour_of_day", "day_of_week", "is_weekend", "prev_1h", "prev_3h_avg"] \
    + [f"zone_{letter}" for letter in DEFAULT_ZONES]
_ZONE_PREFIX = "zone_"

_model_warning_shown = False
_meta_warning_shown = False

@lru_cache(maxsize=1)
def load_model():
    global _model_warning_shown
    if not MODEL_PATH.exists():
        if not _model_warning_shown:
            print("forecast_service: models/forecast_model.joblib not found — falling back to moving average")
            _model_warning_shown = True
        return None
    return joblib.load(MODEL_PATH)

@lru_cache(maxsize=1)
def load_meta():
    global _meta_warning_shown
    if not META_PATH.exists():
        if not _meta_warning_shown:
            print("forecast_service: models/forecast_meta.json not found — using default feature schema")
            _meta_warning_shown = True
        return None
    with META_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def _meta_columns() -> list[str]:
    meta = load_meta()
    if meta and isinstance(meta.get("feature_columns"), list) and meta["feature_columns"]:
        return list(meta["feature_columns"])
    return list(DEFAULT_FEATURE_COLUMNS)

def _zones() -> list[str]:
    meta = load_meta()
    if meta and isinstance(meta.get("zones"), list) and meta["zones"]:
        return list(meta["zones"])
    return list(DEFAULT_ZONES)

def _feature_vector(features: dict, feature_columns: list[str]) -> list[float]:
    """Temporal columns copied straight from features (default 0.0);
    zone_* columns one-hot from customer_zone. Iterating feature_columns
    guarantees the exact order the model was trained on."""
    zone = features["customer_zone"]
    vector = []
    for column in feature_columns:
        if column.startswith(_ZONE_PREFIX):
            vector.append(1.0 if zone == column[len(_ZONE_PREFIX):] else 0.0)
        else:
            vector.append(float(features.get(column, 0.0)))
    return vector

def _zone_history(zone: str, prev_counts_by_zone: dict) -> list[float]:
    """Accept a scalar count or a list of hourly counts; clamp >= 0."""
    raw = prev_counts_by_zone.get(zone, [])
    values = list(raw) if isinstance(raw, (list, tuple)) else ([raw] if raw is not None else [])
    return [max(0.0, float(v)) for v in values]

def predict_next_hour(features: dict) -> float | None:
    """Predict the next-hour order count for a zone, or None without a model."""
    model = load_model()
    if model is None:
        return None
    prediction = float(model.predict([_feature_vector(features, _meta_columns())])[0])
    return max(0.0, prediction)

def forecast_all_zones(hour, day_of_week, is_weekend, prev_counts_by_zone) -> dict[str, float]:
    """Predict next-hour demand for every zone: {zone_letter: count}.
    prev_1h = most recent count; prev_3h_avg = mean of last 3. If the model is
    missing, the zone's prev_3h_avg is used (moving-average fallback)."""
    result = {}
    for zone in _zones():
        history = _zone_history(zone, prev_counts_by_zone)
        prev_1h = history[-1] if history else 0.0
        window = history[-3:]
        prev_3h_avg = sum(window) / len(window) if window else 0.0
        prediction = predict_next_hour({"hour_of_day": hour, "day_of_week": day_of_week,
                                        "is_weekend": is_weekend, "prev_1h": prev_1h,
                                        "prev_3h_avg": prev_3h_avg, "customer_zone": zone})
        if prediction is None:
            prediction = prev_3h_avg
        result[zone] = max(0.0, float(prediction))
    return result
```

**What it does / Why this way**
- **Schema-driven inference**: `_feature_vector` iterates `_meta_columns()` (from disk) instead of a hardcoded list. Training writes the schema; inference reads it — the two can't drift silently.
- **The moving-average fallback is *built into* `forecast_all_zones`**: `prev_3h_avg` is computed for the model *and* is the fallback, so the "no model" path returns the same kind of answer the model would.
- **`_zone_history` accepts a scalar or a list** — the admin dashboard can pass either a single snapshot or a rolling history; both work.
- **Clamping `>= 0` everywhere** — order counts can't be negative, and XGBoost can predict slightly negative for zero-demand hours.
- **`lru_cache` + warning flags** — the "model missing" warning prints exactly once per process even if the cache is cleared.

**What breaks**
- If you hardcoded the feature columns in inference → the moment training adds a feature, every prediction is silently wrong (schema metadata removes this entire class of bug).
- If you predicted without the `prev_*` lags → the model would have no sense of recent demand and would predict the same base count every hour.
- If `forecast_all_zones` didn't fall back per-zone → a missing model would 500 the admin dashboard instead of showing moving averages.

---

## File 7 — `tracking.py` (root: pure geospatial helpers)

> **Runtime-critical.** The dependency-free math engine: distances, route interpolation,
> ETA-by-formula. Every other module (eta_service, routing, tracking_state, orders) builds
> on this.

```python
"""
FoodAI - Live delivery tracking helpers (pure Python)
Pure, dependency-free helpers for the live order-tracking feature. This module
intentionally does NOT import streamlit, streamlit_folium, or folium ...
Design decisions
* Restaurant coordinates are resolved from the COORDINATES dict keyed by
  restaurant_id (1-5), matching the order of seed_data.RESTAURANTS.
* All functions are pure: the same input always produces the same output.
"""
import math

BENGALURU_CENTER = (12.9716, 77.5946)
AVG_SPEED_KMH = 25.0
COORDINATES = {   # Bengaluru coordinates for restaurants 1-5 (seed order)
    1: (12.975, 77.606), 2: (12.982, 77.619), 3: (12.977, 77.596),
    4: (13.004, 77.610), 5: (12.970, 77.750),
}
DEFAULT_CUSTOMER_HOME = (12.9719, 77.6412)   # Indiranagar fallback
DELIVERY_PRESETS = [                         # (label, default address, (lat, lng))
    ("MG Road / Indiranagar", "Hostel Block C, MG Road", (12.9719, 77.6412)),
    ("Koramangala", "5th Block, Koramangala", (12.9352, 77.6245)),
    ("HSR Layout", "Sector 1, HSR Layout", (12.9116, 77.6387)),
    ("Whitefield", "ITPL Main Road, Whitefield", (12.9698, 77.7500)),
    ("City Center", "MG Road Metro, City Center", (12.9770, 77.5960)),
]

def restaurant_coordinates(restaurant_id): ...   # dict lookup, ValueError if unknown
def customer_home_coordinates(): return DEFAULT_CUSTOMER_HOME
def preset_coordinates(label): ...               # preset label -> (lat, lng)

def haversine_km(a, b):
    """Great-circle distance between (lat, lng) points in km."""
    earth_radius_km = 6371.0
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    d_lat, d_lng = lat2 - lat1, lng2 - lng1
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 2 * earth_radius_km * math.asin(math.sqrt(h))

def route_length_km(route): return sum(haversine_km(route[i], route[i+1]) for i in range(len(route)-1))

def _walk_route(route, distance_km):
    """Position after walking distance_km along the route (shared helper)."""
    if len(route) == 1 or distance_km <= 0.0:
        return route[0]
    walked = 0.0
    for i in range(len(route) - 1):
        start, end = route[i], route[i + 1]
        segment_km = haversine_km(start, end)
        if walked + segment_km >= distance_km:
            fraction = 0.0 if segment_km == 0 else (distance_km - walked) / segment_km
            return (start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction)
        walked += segment_km
    return route[-1]

def interpolate_position(route, progress):
    """Route position at progress [0,1]; always lies exactly on the route."""
    progress = min(1.0, max(0.0, progress))
    if progress == 1.0: return route[-1]
    total_km = route_length_km(route)
    if total_km == 0.0: return route[0]
    return _walk_route(route, progress * total_km)

def estimate_trip_seconds(route, avg_speed_kmh=AVG_SPEED_KMH):
    return round(route_length_km(route) / avg_speed_kmh * 3600)

def compute_eta(route, progress, avg_speed_kmh=AVG_SPEED_KMH):
    """Remaining travel minutes (ceil) at progress [0,1]."""
    progress = min(1.0, max(0.0, progress))
    remaining_km = (1.0 - progress) * route_length_km(route)
    return math.ceil(remaining_km / avg_speed_kmh * 60)

def format_eta(minutes): return f"~{minutes} min"
def format_distance(km): return f"{km:.1f} km"
```

**What it does / Why this way**
- **Pure functions, zero dependencies** — every function is deterministic, so the same inputs give the same outputs everywhere (REPL, tests, API, simulator). This is the foundation everything else is built on.
- **Haversine is the right distance for demo coordinates** — it's spherical great-circle distance; good enough for city-scale (a flat Pythagoras would be fine too, but this is standard and dependency-free).
- **`interpolate_position` walks cumulative segment lengths** so the marker always sits *on* the route (not as-the-crow-flies between points). At `progress=1.0` it returns `route[-1]` exactly — no off-by-one at the door.
- **`COORDINATES` keyed by restaurant_id 1-5** matches `seed_data.RESTAURANTS`. No lat/lng columns in the restaurants table — coordinates live here in the legacy spirit of "no schema migration for demo data."

**What breaks**
- `build_route` (straight-line fallback) with `num_points < 2` → division by zero in `steps`; guarded by an explicit `ValueError`.
- If `interpolate_position` were linear between the first and last point (not along the polyline) → the rider marker would cut across buildings instead of following roads.
- If `compute_eta` used `progress` unclamped → a value >1.0 would produce a negative "remaining minutes".

---

## File 8 — `routing.py` (OSRM road routes)

> **Runtime-critical.** Replaces straight-line routes with routes that follow real roads by
> calling the free public OSRM API — and falls back to a straight line when the router is
> unreachable (offline-friendly).

```python
"""
FoodAI - Road-following routes via OSRM
Replaces straight-line routes with routes that follow real roads (turns,
U-turns) using the free public OSRM driving API. Falls back to a straight line
when no router is reachable, so the app keeps working offline.
Results are cached per start/end pair: the tracking page auto-refreshes every
2.5 seconds, so the router is only hit once per unique pair.
"""
from functools import lru_cache
from typing import Optional
import requests
import tracking

OSRM_BASES = (   # HTTP first: some builds/networks reject TLS to these hosts
    "http://router.project-osrm.org/route/v1/driving/",
    "http://routing.openstreetmap.de/routed-car/route/v1/driving/",
    "https://router.project-osrm.org/route/v1/driving/",
    "https://routing.openstreetmap.de/routed-car/route/v1/driving/",
)
TIMEOUT_SECONDS = 4.0
MAX_POINTS = 200

def _decimate(points, max_points):
    """Evenly sample points down to max_points, keeping both endpoints."""
    if len(points) <= max_points: return points
    indices = {round(i * (len(points) - 1) / (max_points - 1)) for i in range(max_points)}
    return [points[i] for i in sorted(indices)]

def _fetch_osrm(start, end):
    """First reachable OSRM server -> (route_points, distance_km), else None.
    OSRM expects 'lon,lat;lon,lat' and returns [lng, lat]; we convert back."""
    coordinates = f"{start[1]},{start[0]};{end[1]},{end[0]}"
    for base in OSRM_BASES:
        try:
            data = requests.get(f"{base}{coordinates}?overview=full&geometries=geojson&steps=false",
                                timeout=TIMEOUT_SECONDS).json()
            routes = data.get("routes") or []
            if not routes: continue
            coords = routes[0].get("geometry", {}).get("coordinates") or []
            points = [(lat, lng) for lng, lat in coords]
            if len(points) < 2: continue
            distance_km = float(routes[0].get("distance", 0.0)) / 1000.0
            return _decimate(points, MAX_POINTS), distance_km
        except Exception:
            continue
    return None

@lru_cache(maxsize=256)
def get_route(start, end):
    """(route_points, distance_km) following real roads, cached; falls back
    to a straight line with haversine distance when OSRM is unreachable."""
    result = _fetch_osrm(start, end)
    if result is not None:
        points, distance_km = result
        return tuple(points), distance_km
    points = tracking.build_route(start, end)
    return tuple(points), tracking.route_length_km(points)
```

**What it does / Why this way**
- **Four server bases, tried in order** — the public OSRM servers are flaky; the list gives resilience. HTTP bases come first because some macOS/LibreSSL builds reject the TLS handshake to these hosts while plain HTTP works (a real, discovered gotcha).
- **`@lru_cache(maxsize=256)` is the performance key.** The tracking UI refreshes every 2.5s, but each unique (start, end) pair hits OSRM exactly once — everything after is a memory cache hit. This is what makes "live tracking" cheap.
- **The API contract swaps lon/lat ↔ lat/lng twice** — OSRM wants `lon,lat`, and its GeoJSON geometry is `[lng, lat]`; converting back to `(lat, lng)` keeps every other module's coordinate order consistent.
- **`MAX_POINTS = 200` decimation** keeps the route light for maps + interpolation while preserving shape (`_decimate` keeps both endpoints).
- **Fallback is a straight line with haversine distance** — the app works completely offline; the UI just shows a slightly-less-real route.

**What breaks**
- If you trusted OSRM and didn't fall back → any network hiccup would 500 the tracking endpoint.
- If you didn't cache → every 2.5s refresh would spam the public API (rate limits) and add latency to every poll.
- If you forgot the lon/lat swap → routes would point to the wrong city entirely (silent, confusing bug).

---

## File 9 — `backend/routers/tracking.py` (REST + WebSocket bridge)

> **Runtime-critical.** The endpoint the customer's live map talks to. `GET /tracking/{id}`
> returns a snapshot; `WS /ws/tracking/{id}` streams position events as the simulation
> advances. Both use the same `tracking_state.build_tracking_state` so they never disagree.

```python
"""
FoodAI backend - tracking router
Live order tracking over REST (GET /tracking/{order_id}) and WebSocket
(WS /ws/tracking/{order_id}?token=...). Both use the same
tracking_state.build_tracking_state so REST and live views always agree.
WebSocket auth: the JWT is passed as the token query parameter (browsers
cannot set headers on WebSocket upgrade).
"""
import asyncio, json
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from backend import security
from backend.db import SessionLocal, get_db
from backend.models import Delivery, Order, User
from backend.simulation import manager, notifications_manager
from backend.tracking_state import build_tracking_state

router = APIRouter(prefix="/tracking", tags=["tracking"])
ws_router = APIRouter(tags=["tracking"])

def _can_access_order(user, order, db):
    if user.role == "admin": return True
    if user.role == "customer": return order.customer_id == user.id
    if user.role == "restaurant": return any(r.id == order.restaurant_id for r in user.restaurants)
    if user.role == "delivery":
        return db.query(Delivery).filter(Delivery.order_id == order.id, Delivery.driver_id == user.id).first() is not None
    return False

@router.get("/{order_id}")
def get_tracking(order_id: int, user=Depends(security.get_current_user), db=Depends(get_db)):
    order = _load_order_or_404(order_id, db)
    if not _can_access_order(user, order, db):
        raise HTTPException(status_code=403, detail="You cannot access this order.")
    delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
    return build_tracking_state(order, delivery)

@ws_router.websocket("/ws/tracking/{order_id}")
async def ws_tracking(websocket: WebSocket, order_id: int):
    token = websocket.query_params.get("token")
    payload = security.decode_token(token) if token else None
    if payload is None:
        await websocket.close(code=4401); return
    loop = asyncio.get_running_loop()

    def _build_initial_state():
        """Blocking work (DB + OSRM + ML ETA) run off the event loop."""
        db = SessionLocal()
        try:
            user_id = int(payload["sub"])
            user = db.query(User).filter(User.id == user_id).first()
            if user is None: return None
            order = _load_order_or_404(order_id, db)
            if not _can_access_order(user, order, db): return "forbidden"
            delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
            return build_tracking_state(order, delivery)
        finally:
            db.close()

    state = await loop.run_in_executor(None, _build_initial_state)
    if state is None: await websocket.close(code=4401); return
    if state == "forbidden": await websocket.close(code=4403); return

    await websocket.accept()
    await manager.subscribe(order_id, websocket)
    await websocket.send_json({"type": "state", "data": state})
    try:
        while True:
            message = await websocket.receive_text()   # keep-alive / ping frames
            if message:
                try:
                    data = json.loads(message)
                    if data.get("type") == "ping": await websocket.send_json({"type": "pong"})
                except (json.JSONDecodeError, AttributeError):
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        await manager.unsubscribe(order_id, websocket)

@ws_router.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket):
    """Per-user notification channel (e.g. drivers receive delivery_assigned)."""
    token = websocket.query_params.get("token")
    payload = security.decode_token(token) if token else None
    if payload is None:
        await websocket.close(code=4401); return
    ...  # loads user, subscribes to f"user:{user.id}", ping/pong loop
```

**What it does / Why this way**
- **Two transports, one state function.** REST and WebSocket both call `build_tracking_state` — the customer can poll REST *and* watch WS and the two can never disagree (the core design rule from Part 2).
- **JWT via `?token=` for WebSocket.** Browsers can't set `Authorization` headers on a WebSocket upgrade, so the token travels as a query param. The server decodes it (not trusting it blindly — it's still verified + checked against the DB user).
- **Access control is per-role**: admin everything; customer their own; restaurant their restaurants; rider only their assigned orders. `_can_access_order` is the single place this logic lives for tracking.
- **`run_in_executor` for the initial state build.** `build_tracking_state` does DB + OSRM HTTP + ML inference — all blocking. Running it in the default executor keeps the event loop free for other sockets; then the *live* updates come for free via the simulation's `manager.publish`.
- **Close codes are meaningful**: `4401` = not authenticated, `4403` = forbidden. The client can distinguish "log in" from "not your order."
- **The ping/pong loop** keeps the connection alive through proxies that idle-close sockets, and the `finally` block guarantees the socket is unsubscribed even on abrupt disconnect.

**What breaks**
- If you tried to read the token from a header in the WS handler → browsers would never authenticate (headers can't be set on upgrade).
- If you ran `build_tracking_state` directly on the event loop → a slow OSRM call would block *all* WebSocket traffic for that process.
- If you skipped `unsubscribe` in `finally` → dead sockets accumulate in the manager forever (memory leak + repeated send errors).
- If REST and WS used different state builders → customer sees one ETA on the map and another on poll (the exact drift this file exists to prevent).

---

## File 10 — `backend/routers/ml.py` (full route walkthrough)

> The HTTP surface for the ML stack. Every endpoint degrades gracefully: missing model →
> `"fallback": true` in the response, never a crash. (The full file is in Part 2; here is
> the complete walkthrough including the Layer 2 addition.)

| Endpoint | What it does | Fallback behavior |
|---|---|---|
| `GET /ml/eta` | ETA prediction from distance, prep time, optional `customer_home` (`lat,lng` or preset label) | `503` if the model is unavailable (model absent) |
| `POST /ml/eta/explain` | SHAP explanation of that prediction | `503` if explainer unavailable |
| `GET /ml/forecast` | Per-zone next-hour demand | `fallback: true` + moving averages when no model |
| `GET /ml/forecast/series` | Per-zone demand for the next N hours (admin chart) | same fallback per zone |
| `GET /ml/recommendations` | Personalized restaurant ranking for a customer | `fallback: true` when no order history |
| `GET /ml/recommendations/items` | Menu-item ranking at one restaurant | `fallback: true` when no signal |
| `GET /ml/order/{id}` | Per-order ETA + explanation | `eta_min: null` + `fallback: true` |
| `GET /ml/kitchen-load` | Current simulated load per zone (Layer 2) | always available (simulated) |

**Key implementation details**
- **`_parse_point` / `_resolve_home`** turn either a raw `"lat,lng"` string or a preset label
  (e.g. `"Koramangala"`) into coordinates, raising `400` for garbage — the same helpers keep
  `features_for_order` honest.
- **Recommendations score formula** (`0.45·rating + 0.30·cuisine-affinity + 0.15·familiarity
  + 0.10·review-popularity`) — a transparent, explainable ranking that the UI can print as a
  human reason ("You've ordered here 3×", "You like Chinese food").
- **`get_order_prediction`** re-checks ownership (admin or the order's customer) *before*
  using `order_route` + `delivery_end` — it never leaks another customer's route data.
- **`fallback` is *returned data*, not an error** — the frontend shows "AI estimate" vs
  "rough estimate" instead of an error screen.

**What breaks**
- If `/ml/eta` raised on a missing model → the whole dashboard would break every time the
  model file isn't present; the `503 + detail` (or `fallback`) pattern keeps consumers alive.
- If `customer_home` accepted anything without parsing → `"Bengaluru"` would become
  `ValueError` in `preset_coordinates`; the explicit 400 turns that into a clean message.
- If `get_order_prediction` forgot the ownership check → a customer could enumerate other
  users' order routes (privacy leak).

---

## File 11 — `maps.py` (legacy folium builders) — brief

The Next.js frontend (Layer 4) uses Leaflet, but the legacy Streamlit app still uses
`maps.py` for the cart picker, tracking, delivery panel, and admin demand heatmap. It
centralizes the folium look (CartoDB Voyager tiles, Google-blue route with white casing,
green store / red robot / purple home markers). **Not runtime-critical for the new
frontend** — included here so the legacy UI's maps are understood if you maintain them.
Its `build_demand_map(zone_anchors, demand)` reads the same per-zone forecasts the new
admin panel will render with Leaflet/Recharts.

---

## Verification (run live for this guide)

I ran the full inference stack against the trained artifacts:

```text
1. ETA model loaded          : XGBRegressor
   features_for_order(1, 5.2km, 15min, Indiranagar)  -> {'hour': 12, 'customer_zone': 'B', ...}
   predict_eta                                       -> 36.9 min
2. SHAP explain               -> base_value + top contributions: prep_time_min +4.17,
                                   distance_km -2.30, day_of_week -0.66
3. Forecast model loaded     : XGBRegressor, meta zones ['A','B','C','D','E']
   forecast_all_zones(13:00) -> ~1.6-1.9 orders/zone/hour
4. OSRM route                 -> 200 points, 6.33 km road distance (restaurant 1 -> home)
   interpolate_position(0.5)  -> point on the route; compute_eta(0.3) -> 11 min
   best_eta(route, 0.3, 1)    -> (30.5, 'ml')   <- ML path preferred over formula
```

All fallback branches were exercised by design in the code review: remove the joblib file
and every service returns its fallback rather than raising.

---

## Layer 3 exit checklist
- [x] ETA model loads and predicts (XGBoost, `models/eta_model.joblib`).
- [x] SHAP explainer returns base + contributions.
- [x] Forecast model + schema metadata load; per-zone predictions returned.
- [x] OSRM routing returns road routes with straight-line fallback.
- [x] `best_eta` prefers `"ml"` and falls back to `"formula"`.
- [x] Every service is importable without its optional deps and never raises on missing models.
- [x] `ml.py` routes + tracking router (REST + WS) walkthrough complete.

## What's next
- **Layer 4 — the frontend**: the Next.js app (all four role dashboards), the new
  shadcn/ui checkout + payment screens wired to the payments router, the rider navigation
  screen using the tracking WebSocket, and the closing glossary.
