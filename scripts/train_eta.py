"""
FoodAI - ETA Model Training Pipeline

Trains regression models that predict delivery time (delivery_min) from
order features in data/orders.csv:

    baseline       : simulator formula (5 + distance_km * 4 + prep_time_min)
    linear         : LinearRegression
    random_forest  : RandomForestRegressor
    xgboost        : XGBRegressor (champion, persisted to models/)

Deterministic (random_state=42 everywhere) and rerunnable: every run
overwrites the model, metrics, and charts with identical values.

Outputs:
    models/eta_model.joblib
    outputs/metrics_eta.json
    outputs/charts/eta_metrics_comparison.png
    outputs/charts/eta_actual_vs_predicted.png
    outputs/charts/eta_feature_importance.png

Run from the foodai/ directory:
    python scripts/train_eta.py
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
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor

# --- Paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "orders.csv"
MODEL_PATH = ROOT / "models" / "eta_model.joblib"
METRICS_PATH = ROOT / "outputs" / "metrics_eta.json"
CHARTS_DIR = ROOT / "outputs" / "charts"
COMPARISON_CHART_PATH = CHARTS_DIR / "eta_metrics_comparison.png"
ACTUAL_VS_PREDICTED_CHART_PATH = CHARTS_DIR / "eta_actual_vs_predicted.png"
FEATURE_IMPORTANCE_CHART_PATH = CHARTS_DIR / "eta_feature_importance.png"

# --- Feature schema ------------------------------------------------------
NUMERIC_COLUMNS = [
    "distance_km",
    "prep_time_min",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "traffic_factor",
]
ZONE_COLUMNS = [f"zone_{letter}" for letter in ("A", "B", "C", "D", "E")]
FULL_COLUMNS = NUMERIC_COLUMNS + ZONE_COLUMNS

MODEL_DISPLAY_NAMES = {
    "baseline": "Baseline",
    "linear": "Linear",
    "random_forest": "Random Forest",
    "xgboost": "XGBoost",
}

RANDOM_STATE = 42
TEST_SIZE = 0.2


# --- Feature engineering -------------------------------------------------

def make_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build the fixed-width feature matrix from a raw orders frame.

    Numeric features are selected as-is (hour renamed to hour_of_day) and
    customer_zone is one-hot encoded. reindex(columns=FULL_COLUMNS) with
    fill_value=0 guarantees all five zone columns exist in the exact fixed
    order, so train/test/inference always share the same shape and dtype
    even when a subset lacks a rare zone.
    """
    numeric = pd.DataFrame(
        {
            "distance_km": df["distance_km"],
            "prep_time_min": df["prep_time_min"],
            "hour_of_day": df["hour"],
            "day_of_week": df["day_of_week"],
            "is_weekend": df["is_weekend"],
            "traffic_factor": df["traffic_factor"],
        }
    )
    zones = pd.get_dummies(df["customer_zone"], prefix="zone")
    features = pd.concat([numeric, zones], axis=1)
    return features.reindex(columns=FULL_COLUMNS, fill_value=0).astype(float)


# --- Evaluation ----------------------------------------------------------

def baseline_predictions(features: pd.DataFrame) -> np.ndarray:
    """Mirror the simulator formula: pickup fee + drive time + prep time."""
    return 5.0 + features["distance_km"] * 4.0 + features["prep_time_min"]


def evaluate(y_true: pd.Series, y_pred: np.ndarray) -> tuple[float, float]:
    """Return (mae, rmse) for a prediction vector."""
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    return mae, rmse


# --- Modeling ------------------------------------------------------------

def train_models(X_train: pd.DataFrame, y_train: pd.Series) -> dict:
    """Fit the three learned models on the training split only."""
    linear = LinearRegression()
    linear.fit(X_train, y_train)

    forest = RandomForestRegressor(n_estimators=200, random_state=RANDOM_STATE)
    forest.fit(X_train, y_train)

    xgb = XGBRegressor(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=RANDOM_STATE,
    )
    xgb.fit(X_train, y_train)

    return {"linear": linear, "random_forest": forest, "xgboost": xgb}


def collect_metrics(
    y_test: pd.Series, X_test: pd.DataFrame, models: dict
) -> dict:
    """Compute MAE/RMSE for baseline and every learned model on the test split."""
    metrics = {}
    baseline_mae, baseline_rmse = evaluate(y_test, baseline_predictions(X_test))
    metrics["baseline"] = {"mae": baseline_mae, "rmse": baseline_rmse}
    for name, model in models.items():
        mae, rmse = evaluate(y_test, model.predict(X_test))
        metrics[name] = {"mae": mae, "rmse": rmse}
    return metrics


# --- Charts --------------------------------------------------------------

def save_metrics_comparison(metrics: dict, path: Path) -> None:
    """Grouped bar chart of MAE and RMSE per model with value labels."""
    names = list(metrics.keys())
    positions = np.arange(len(names))
    width = 0.35
    mae_values = [metrics[name]["mae"] for name in names]
    rmse_values = [metrics[name]["rmse"] for name in names]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(positions - width / 2, mae_values, width, label="MAE")
    ax.bar(positions + width / 2, rmse_values, width, label="RMSE")

    for pos, value in zip(positions - width / 2, mae_values):
        ax.text(pos, value, f"{value:.2f}", ha="center", va="bottom")
    for pos, value in zip(positions + width / 2, rmse_values):
        ax.text(pos, value, f"{value:.2f}", ha="center", va="bottom")

    ax.set_xticks(positions)
    ax.set_xticklabels([MODEL_DISPLAY_NAMES[name] for name in names])
    ax.set_ylabel("Minutes")
    ax.set_title("ETA Model Comparison (Test Set)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_actual_vs_predicted(
    y_test: pd.Series, y_pred: np.ndarray, path: Path
) -> None:
    """Scatter of actual vs XGBoost predicted delivery time with a y=x line."""
    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    ax.scatter(y_test, y_pred, s=18, alpha=0.6)
    low = min(float(y_test.min()), float(y_pred.min()))
    high = max(float(y_test.max()), float(y_pred.max()))
    ax.plot([low, high], [low, high], color="tab:red", linestyle="--", label="y = x")
    ax.set_xlabel("Actual delivery_min")
    ax.set_ylabel("Predicted delivery_min (XGBoost)")
    ax.set_title("XGBoost: Actual vs Predicted (Test Set)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_feature_importance(
    model: XGBRegressor, feature_names: list[str], path: Path
) -> None:
    """Horizontal bar chart of XGBoost feature importances, descending."""
    importances = model.feature_importances_
    order = np.argsort(importances)[::-1]  # most important first
    sorted_names = [feature_names[i] for i in order]
    sorted_values = importances[order]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(range(len(sorted_names)), sorted_values, tick_label=sorted_names)
    ax.invert_yaxis()  # show the most important feature at the top
    for i, value in enumerate(sorted_values):
        ax.text(value, i, f"{value:.4f}", va="center")
    ax.set_xlabel("Feature importance (gain)")
    ax.set_title("XGBoost Feature Importance")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# --- Reporting -----------------------------------------------------------

def print_results(metrics: dict) -> None:
    """Print the model comparison table and the baseline improvement note."""
    names = list(metrics.keys())
    best_name = min(names, key=lambda name: metrics[name]["mae"])

    header = f"{'Model':<14} | {'MAE':>7} | {'RMSE':>7}"
    print(header)
    print("-" * len(header))
    for name in names:
        label = MODEL_DISPLAY_NAMES[name]
        if name == best_name:
            label += " (best)"
        print(
            f"{label:<14} | {metrics[name]['mae']:>7.2f} | "
            f"{metrics[name]['rmse']:>7.2f}"
        )

    improvement = (1 - metrics[best_name]["mae"] / metrics["baseline"]["mae"]) * 100
    print(
        f"\n{MODEL_DISPLAY_NAMES[best_name]} MAE improvement vs baseline: "
        f"{improvement:.1f}%"
    )


# --- Pipeline ------------------------------------------------------------

def main() -> None:
    """Run the full ETA training pipeline end to end."""
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Missing {DATA_PATH}. Run scripts/simulate_orders.py first."
        )

    for directory in (MODEL_PATH.parent, METRICS_PATH.parent, CHARTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    orders = pd.read_csv(DATA_PATH)

    features = make_features(orders)
    target = orders["delivery_min"].astype(float)

    # Stratify on the raw zone series BEFORE one-hot encoding.
    X_train, X_test, y_train, y_test = train_test_split(
        features,
        target,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=orders["customer_zone"],
    )

    models = train_models(X_train, y_train)
    metrics = collect_metrics(y_test, X_test, models)

    joblib.dump(models["xgboost"], MODEL_PATH)
    with METRICS_PATH.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
        f.write("\n")

    save_metrics_comparison(metrics, COMPARISON_CHART_PATH)
    save_actual_vs_predicted(
        y_test, models["xgboost"].predict(X_test), ACTUAL_VS_PREDICTED_CHART_PATH
    )
    save_feature_importance(models["xgboost"], FULL_COLUMNS, FEATURE_IMPORTANCE_CHART_PATH)

    print_results(metrics)
    print(f"\nSaved model  : {MODEL_PATH}")
    print(f"Saved metrics: {METRICS_PATH}")
    print(f"Saved charts : {CHARTS_DIR}")


if __name__ == "__main__":
    main()
