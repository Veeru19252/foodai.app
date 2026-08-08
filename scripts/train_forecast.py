"""
FoodAI - Demand Forecasting Training Pipeline

Builds a per-zone hourly demand series from data/orders.csv and trains a
model that predicts how many orders a zone receives in a given hour:

    moving_average : baseline; prediction is the mean count of the previous
                     3 hours in the same zone (prev_3h_avg)
    xgboost        : XGBRegressor on lag + calendar + zone features
                     (champion, persisted to models/)

Deterministic (random_state=42 everywhere) and rerunnable: every run
overwrites the model, meta, metrics, and charts with identical values.

Outputs:
    models/forecast_model.joblib
    models/forecast_meta.json
    outputs/metrics_forecast.json
    outputs/charts/forecast_metrics_comparison.png
    outputs/charts/forecast_actual_vs_predicted.png
    outputs/charts/forecast_zone_demand.png

Run from the foodai/ directory:
    python scripts/train_forecast.py
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")  # headless backend; must be set before pyplot import

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor

# --- Paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "orders.csv"
MODEL_PATH = ROOT / "models" / "forecast_model.joblib"
META_PATH = ROOT / "models" / "forecast_meta.json"
METRICS_PATH = ROOT / "outputs" / "metrics_forecast.json"
CHARTS_DIR = ROOT / "outputs" / "charts"
COMPARISON_CHART_PATH = CHARTS_DIR / "forecast_metrics_comparison.png"
ACTUAL_VS_PREDICTED_CHART_PATH = CHARTS_DIR / "forecast_actual_vs_predicted.png"
ZONE_DEMAND_CHART_PATH = CHARTS_DIR / "forecast_zone_demand.png"

# --- Feature schema ------------------------------------------------------
ZONES = ("A", "B", "C", "D", "E")
ZONE_COLUMNS = [f"zone_{letter}" for letter in ZONES]
FEATURE_COLUMNS = [
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "prev_1h",
    "prev_3h_avg",
] + ZONE_COLUMNS

MODEL_DISPLAY_NAMES = {
    "moving_average": "Moving Avg",
    "xgboost": "XGBoost",
}

RANDOM_STATE = 42
TEST_SIZE = 0.2


# --- Feature engineering -------------------------------------------------

def build_demand_series(orders: pd.DataFrame) -> pd.DataFrame:
    """Aggregate raw orders into a per-zone hourly demand series.

    Each row is one (customer_zone, hour_of_day, day_of_week, is_weekend)
    bucket holding the number of orders placed in it (order_count, an
    integer). Rows are sorted chronologically within each zone so lag
    features have a well-defined "previous hour".
    """
    demand = (
        orders.rename(columns={"hour": "hour_of_day"})
        .groupby(["customer_zone", "hour_of_day", "day_of_week", "is_weekend"])
        .size()
        .rename("order_count")
        .reset_index()
    )
    return demand.sort_values(
        ["customer_zone", "day_of_week", "hour_of_day"]
    ).reset_index(drop=True)


def add_lag_features(demand: pd.DataFrame) -> pd.DataFrame:
    """Add backward-looking lag features, computed per zone.

    prev_1h     : order count one hour earlier in the same zone (shift 1).
    prev_3h_avg : mean order count over the previous 3 hours in the same
                  zone (shift(1).rolling(3).mean()).

    IMPORTANT (lag leakage): these features are computed on the full series
    BEFORE the train/test split, but they only ever look BACKWARD within
    each zone (a one-row shift plus a trailing rolling window). Because the
    split is time-ordered and every window only contains past values, no
    future information leaks into the features. This is standard practice
    for time series.

    The rolling window must also be per-zone: a plain .rolling(3) on the
    shifted column would mix the last rows of one zone with the first rows
    of the next. Group by zone, roll, then restore the frame index.

    The first few rows of each zone have no 3-hour history, so rolling
    yields NaN there. We fill with 0 (chosen over averaging the fewer
    available hours) so the moving-average baseline is well defined at zone
    starts.
    """
    prev_1h = demand.groupby("customer_zone")["order_count"].shift(1)
    prev_3h_avg = (
        prev_1h.groupby(demand["customer_zone"])
        .rolling(3)
        .mean()
        .reset_index(level=0, drop=True)
    )
    return demand.assign(
        prev_1h=prev_1h.fillna(0).astype(float),
        prev_3h_avg=prev_3h_avg.fillna(0).astype(float),
    )


def make_features(demand: pd.DataFrame) -> pd.DataFrame:
    """Build the fixed-width feature matrix from a demand frame.

    Calendar + lag features are selected as-is and customer_zone is one-hot
    encoded. reindex(columns=FEATURE_COLUMNS) with fill_value=0 guarantees
    all five zone columns exist in the exact fixed order, so train/test
    always share the same shape and dtype even when a subset lacks a rare
    zone.
    """
    numeric = pd.DataFrame(
        {
            "hour_of_day": demand["hour_of_day"],
            "day_of_week": demand["day_of_week"],
            "is_weekend": demand["is_weekend"],
            "prev_1h": demand["prev_1h"],
            "prev_3h_avg": demand["prev_3h_avg"],
        }
    )
    zones = pd.get_dummies(demand["customer_zone"], prefix="zone")
    features = pd.concat([numeric, zones], axis=1)
    return features.reindex(columns=FEATURE_COLUMNS, fill_value=0).astype(float)


def time_ordered_split(
    demand: pd.DataFrame, test_size: float = TEST_SIZE
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Time-ordered 80/20 split using a synthetic chronological hour index.

    hour_index = day_of_week * 24 + hour_of_day sorts the rows
    chronologically across the week. The first 80% become train and the
    last 20% become test. No random shuffle is used, so test rows are never
    seen during fit.
    """
    ordered = demand.assign(
        hour_index=demand["day_of_week"] * 24 + demand["hour_of_day"]
    ).sort_values(["hour_index", "customer_zone"])
    ordered = ordered.drop(columns=["hour_index"])
    split_at = int(len(ordered) * (1.0 - test_size))
    return ordered.iloc[:split_at].copy(), ordered.iloc[split_at:].copy()


# --- Evaluation ----------------------------------------------------------

def evaluate(y_true: pd.Series, y_pred: np.ndarray) -> tuple[float, float]:
    """Return (mae, rmse) for a prediction vector."""
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    return mae, rmse


def mape(y_true: pd.Series, y_pred: np.ndarray) -> float:
    """Mean absolute percentage error.

    The denominator is max(actual, 1) instead of plain actual so sparse
    hourly buckets with zero orders do not divide by zero; a zero-order
    bucket simply contributes |actual - pred| / 1.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs(y_true - y_pred) / np.maximum(y_true, 1.0)))


# --- Modeling ------------------------------------------------------------

def train_xgboost(X_train: pd.DataFrame, y_train: pd.Series) -> XGBRegressor:
    """Fit the XGBoost demand model on the training split only."""
    model = XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=RANDOM_STATE,
    )
    model.fit(X_train, y_train)
    return model


def collect_metrics(
    y_test: pd.Series, X_test: pd.DataFrame, test: pd.DataFrame, model: XGBRegressor
) -> dict:
    """Compute MAE/RMSE/MAPE for the moving-average baseline and XGBoost.

    The moving-average baseline predicts each test row's prev_3h_avg
    directly (the mean count of the previous 3 hours in that zone).
    """
    baseline_pred = test["prev_3h_avg"].to_numpy(dtype=float)
    xgb_pred = model.predict(X_test)

    metrics = {}
    for name, pred in (
        ("moving_average", baseline_pred),
        ("xgboost", xgb_pred),
    ):
        mae, rmse = evaluate(y_test, pred)
        metrics[name] = {"mae": mae, "rmse": rmse, "mape": mape(y_test, pred)}
    return metrics


# --- Charts --------------------------------------------------------------

def save_metrics_comparison(metrics: dict, path: Path) -> None:
    """Grouped bar chart of MAE/RMSE/MAPE per model with value labels."""
    names = list(metrics.keys())
    labels = [MODEL_DISPLAY_NAMES[name] for name in names]
    metric_keys = ["mae", "rmse", "mape"]
    positions = np.arange(len(metric_keys))
    width = 0.35

    fig, ax = plt.subplots(figsize=(9, 5))
    for i, (name, label) in enumerate(zip(names, labels)):
        values = [metrics[name][key] for key in metric_keys]
        offset = (i - (len(names) - 1) / 2) * width
        bars = ax.bar(positions + offset, values, width, label=label)
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{value:.2f}",
                ha="center",
                va="bottom",
            )

    ax.set_xticks(positions)
    ax.set_xticklabels(["MAE", "RMSE", "MAPE"])
    ax.set_ylabel("Error (orders/hour)")
    ax.set_title("Demand Forecast Model Comparison (Test Set)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_actual_vs_predicted(
    y_test: pd.Series, y_pred: np.ndarray, path: Path
) -> None:
    """Scatter of actual vs XGBoost predicted counts with a y=x line."""
    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    ax.scatter(y_test, y_pred, s=18, alpha=0.6)
    low = min(float(y_test.min()), float(y_pred.min()))
    high = max(float(y_test.max()), float(y_pred.max()))
    ax.plot([low, high], [low, high], color="tab:red", linestyle="--", label="y = x")
    ax.set_xlabel("Actual order_count")
    ax.set_ylabel("Predicted order_count (XGBoost)")
    ax.set_title("XGBoost: Actual vs Predicted Hourly Demand (Test Set)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_zone_demand(test: pd.DataFrame, path: Path) -> None:
    """Bar chart of total test-set demand per zone with value labels."""
    zone_totals = (
        test.groupby("customer_zone")["order_count"].sum().reindex(ZONES).fillna(0)
    )

    fig, ax = plt.subplots(figsize=(7, 5))
    bars = ax.bar(zone_totals.index, zone_totals.values)
    for bar, value in zip(bars, zone_totals.values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{value:.0f}",
            ha="center",
            va="bottom",
        )

    ax.set_xlabel("Customer zone")
    ax.set_ylabel("Total orders (test set)")
    ax.set_title("Total Demand per Zone (Test Set)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# --- Reporting -----------------------------------------------------------

def print_results(metrics: dict) -> None:
    """Print the model comparison table."""
    header = f"{'Model':<16} | {'MAE':>7} | {'RMSE':>7} | {'MAPE':>8}"
    print(header)
    print("-" * len(header))
    for name in metrics:
        label = MODEL_DISPLAY_NAMES[name]
        print(
            f"{label:<16} | {metrics[name]['mae']:>7.2f} | "
            f"{metrics[name]['rmse']:>7.2f} | {metrics[name]['mape']:>8.3f}"
        )


# --- Pipeline ------------------------------------------------------------

def main() -> None:
    """Run the full demand-forecast training pipeline end to end."""
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Missing {DATA_PATH}. Run scripts/simulate_orders.py first."
        )

    for directory in (MODEL_PATH.parent, METRICS_PATH.parent, CHARTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    orders = pd.read_csv(DATA_PATH)

    demand = build_demand_series(orders)
    demand = add_lag_features(demand)

    train, test = time_ordered_split(demand, TEST_SIZE)

    X_train = make_features(train)
    y_train = train["order_count"].astype(float)
    X_test = make_features(test)
    y_test = test["order_count"].astype(float)

    model = train_xgboost(X_train, y_train)
    metrics = collect_metrics(y_test, X_test, test, model)

    joblib.dump(model, MODEL_PATH)
    meta = {
        "feature_columns": FEATURE_COLUMNS,
        "zones": list(ZONES),
    }
    with META_PATH.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    with METRICS_PATH.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
        f.write("\n")

    save_metrics_comparison(metrics, COMPARISON_CHART_PATH)
    save_actual_vs_predicted(y_test, model.predict(X_test), ACTUAL_VS_PREDICTED_CHART_PATH)
    save_zone_demand(test, ZONE_DEMAND_CHART_PATH)

    print_results(metrics)
    print(f"\nSaved model  : {MODEL_PATH}")
    print(f"Saved meta   : {META_PATH}")
    print(f"Saved metrics: {METRICS_PATH}")
    print(f"Saved charts : {CHARTS_DIR}")


if __name__ == "__main__":
    main()
