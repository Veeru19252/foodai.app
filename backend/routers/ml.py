"""
FoodAI backend - ML router
===========================
Exposes the existing XGBoost ETA + forecast pipeline (and its SHAP
explainer) behind small JSON endpoints. Every endpoint degrades gracefully:
if a model file is missing the response carries ``"fallback": true`` instead
of erroring — the same pattern the legacy app already uses.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import eta_service
import explain_service
import forecast_service
import tracking

from backend.db import get_db
from backend.models import Order, User
from backend import security
from backend.tracking_state import delivery_end, order_route

router = APIRouter(prefix="/ml", tags=["ml"])


def _parse_point(value: Optional[str]) -> Optional[tuple[float, float]]:
    if not value:
        return None
    try:
        lat, lng = (float(p) for p in value.split(","))
        return (lat, lng)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lat,lng format.")


def _resolve_home(customer_home: Optional[str]) -> Optional[tuple[float, float]]:
    """Parse a 'lat,lng' point or delivery preset label; None when absent."""
    if not customer_home:
        return None
    point = _parse_point(customer_home)
    if point is not None:
        return point
    try:
        return tracking.preset_coordinates(customer_home)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="customer_home must be 'lat,lng' or a known delivery preset label.",
        )


@router.get("/eta")
def get_eta(
    restaurant_id: int = Query(...),
    distance_km: float = Query(15.0, ge=0.0),
    prep_time_min: float = Query(15.0, ge=0.0),
    customer_home: Optional[str] = Query(None, description="'lat,lng' or preset label"),
    user: User = Depends(security.get_current_user),
):
    home = _resolve_home(customer_home)
    features = eta_service.features_for_order(
        restaurant_id,
        distance_km=distance_km,
        prep_time_min=prep_time_min,
        customer_home=home,
    )
    predicted = eta_service.predict_eta(features)
    if predicted is None:
        raise HTTPException(status_code=503, detail="ETA model unavailable.")
    return {"eta_min": round(predicted, 1), "features": features, "fallback": False}


@router.post("/eta/explain")
def explain_eta(
    restaurant_id: int = Query(...),
    distance_km: float = Query(15.0, ge=0.0),
    prep_time_min: float = Query(15.0, ge=0.0),
    customer_home: Optional[str] = Query(None),
    user: User = Depends(security.get_current_user),
):
    home = _parse_point(customer_home)
    features = eta_service.features_for_order(
        restaurant_id,
        distance_km=distance_km,
        prep_time_min=prep_time_min,
        customer_home=home,
    )
    explanation = explain_service.explain_eta(features)
    if explanation is None:
        raise HTTPException(status_code=503, detail="SHAP explainer unavailable.")
    return {"explanation": explanation, "fallback": False}


@router.get("/forecast")
def get_forecast(
    hour: Optional[int] = Query(None),
    user: User = Depends(security.get_current_user),
):
    from datetime import datetime

    now = datetime.now()
    hour = now.hour if hour is None else hour
    prev_counts = {zone: 1 for zone in "ABCDE"}
    zones = forecast_service.forecast_all_zones(
        hour=hour,
        day_of_week=now.weekday(),
        is_weekend=1 if now.weekday() in (5, 6) else 0,
        prev_counts_by_zone=prev_counts,
    )
    return {
        "hour": hour,
        "zones": zones,
        "fallback": forecast_service.load_model() is None,
    }


@router.get("/order/{order_id}")
def get_order_prediction(
    order_id: int,
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if not (user.role == "admin" or order.customer_id == user.id):
        raise HTTPException(status_code=403, detail="Not your order.")
    route, distance_km = order_route(order)
    features = eta_service.features_for_order(
        order.restaurant_id,
        distance_km=distance_km,
        prep_time_min=15,
        customer_home=delivery_end(order),
    )
    predicted = eta_service.predict_eta(features)
    explanation = explain_service.explain_eta(features)
    return {
        "order_id": order.id,
        "restaurant_id": order.restaurant_id,
        "eta_min": round(predicted, 1) if predicted is not None else None,
        "fallback": predicted is None,
        "features": features,
        "explanation": explanation,
    }
