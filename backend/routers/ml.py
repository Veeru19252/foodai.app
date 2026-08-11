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
from sqlalchemy import func
from sqlalchemy.orm import Session

import eta_service
import explain_service
import forecast_service
import tracking

from backend.db import get_db
from backend.models import MenuItem, Order, OrderItem, Restaurant, Review, User
from backend import security, simulation
from backend.tracking_state import delivery_end, order_route

router = APIRouter(prefix="/ml", tags=["ml"])


@router.get("/kitchen-load")
def get_kitchen_load(
    hour: Optional[int] = Query(None),
    user: User = Depends(security.get_current_user),
):
    """Simulated per-zone kitchen load for an hour (Poisson arrivals).

    Feeds the restaurant/admin dashboards with a realistic "how busy is each
    kitchen zone right now" number. The underlying distribution comes from
    backend.simulation.kitchen_load(); the ML forecast endpoint is separate
    and predicts demand hours ahead — this one is the current snapshot.
    """
    return simulation.kitchen_load(hour)


@router.post("/forecast/retrain")
def retrain_forecast(
    user: User = Depends(security.require_roles("admin")),
):
    """Retrain the demand-forecast model from historical data + live orders.

    Admin-only. Runs the same pipeline as ``scripts/train_forecast.py``
    (reused, not copied) and rewrites the model + schema metadata that every
    forecast endpoint reads, so a retrain takes effect immediately.
    """
    from backend import ml_train

    try:
        result = ml_train.retrain_forecast()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # The forecast endpoints read the model through lru_cached loaders; drop
    # the cached copies so the freshly-written joblib actually takes effect
    # (otherwise "Retrain" silently keeps serving the old model).
    forecast_service.load_model.cache_clear()
    forecast_service.load_meta.cache_clear()
    return result


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


@router.get("/forecast/series")
def get_forecast_series(
    hours: int = Query(6, ge=1, le=24),
    user: User = Depends(security.get_current_user),
):
    """Per-zone demand forecast for the next ``hours`` hours (admin dashboard)."""
    from datetime import datetime, timedelta

    now = datetime.now()
    prev_counts = {zone: 1 for zone in "ABCDE"}
    series = []
    for offset in range(hours):
        ts = now + timedelta(hours=offset)
        zones = forecast_service.forecast_all_zones(
            hour=ts.hour,
            day_of_week=ts.weekday(),
            is_weekend=1 if ts.weekday() in (5, 6) else 0,
            prev_counts_by_zone=prev_counts,
        )
        series.append(
            {
                "hour": ts.hour,
                "label": f"{ts.hour:02d}:00",
                "zones": {zone: round(count, 1) for zone, count in zones.items()},
            }
        )
    return {"series": series, "fallback": forecast_service.load_model() is None}


@router.get("/recommendations")
def get_recommendations(
    user: User = Depends(security.require_roles("customer")),
    db: Session = Depends(get_db),
):
    """Personalized restaurant recommendations from the customer's order history.

    Scores every restaurant by: base rating (45%), cuisine affinity from past
    orders (30%), familiarity (15%) and review popularity (10%). Returns the
    top 4 with a human-readable reason. ``fallback`` is true when the customer
    has no order history (frontend hides the row).
    """
    from collections import Counter

    orders = db.query(Order).filter(Order.customer_id == user.id).all()
    restaurants = db.query(Restaurant).all()
    if not restaurants:
        return {"recommendations": [], "fallback": True}

    ordered = Counter(o.restaurant_id for o in orders if o.restaurant_id)
    cuisine_orders = Counter(
        r.cuisine for o in orders for r in restaurants if r.id == o.restaurant_id
    )
    total_orders = max(1, len(orders))

    review_rows = (
        db.query(
            Review.restaurant_id, func.avg(Review.rating), func.count(Review.id)
        )
        .group_by(Review.restaurant_id)
        .all()
    )
    review_map = {
        rid: (round(avg or 0.0, 1), count) for rid, avg, count in review_rows
    }

    scored = []
    for r in restaurants:
        order_count = ordered.get(r.id, 0)
        cuisine_match = cuisine_orders.get(r.cuisine, 0) / total_orders
        base = (r.rating or 0.0) / 5.0
        reviews_rating, review_count = review_map.get(r.id, (0.0, 0))
        popularity = (reviews_rating / 5.0) * 0.5 if review_count else 0.0
        familiarity = min(1.0, order_count / 2.0)
        score = (
            0.45 * base + 0.30 * cuisine_match + 0.15 * familiarity + 0.10 * popularity
        )

        if order_count > 0:
            reason = f"You've ordered here {order_count}×"
        elif cuisine_match > 0.2:
            reason = f"You like {r.cuisine} food"
        elif review_count > 0:
            reason = f"{review_count} customer review{'s' if review_count != 1 else ''}"
        else:
            reason = "Popular in your area"

        scored.append(
            {
                "restaurant_id": r.id,
                "name": r.name,
                "cuisine": r.cuisine,
                "address": r.address,
                "rating": round(r.rating or 0.0, 2),
                "reviews_rating": reviews_rating,
                "review_count": review_count,
                "score": round(score, 3),
                "reason": reason,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return {"recommendations": scored[:4], "fallback": len(orders) == 0}


@router.get("/recommendations/items")
def get_item_recommendations(
    restaurant_id: int = Query(...),
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    """Menu-item recommendations for one restaurant ("People also order").

    Scores each item from platform popularity (delivered orders), co-occurrence
    inside the customer's own past orders at this restaurant, and their
    personal order frequency. ``fallback`` is true when there is no signal yet.
    """
    from collections import Counter, defaultdict

    menu = db.query(MenuItem).filter(MenuItem.restaurant_id == restaurant_id).all()
    if not menu:
        return {"items": [], "fallback": True}
    ids = {m.id: m for m in menu}

    # Platform popularity (delivered orders only)
    pop_rows = (
        db.query(OrderItem.menu_item_id, func.count(OrderItem.id))
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            Order.restaurant_id == restaurant_id,
            Order.status == "DELIVERED",
        )
        .group_by(OrderItem.menu_item_id)
        .all()
    )
    popularity = dict(pop_rows)

    # Personal history: order counts + co-occurrence with what they ordered.
    my_order_ids = [
        row[0]
        for row in db.query(Order.id)
        .filter(Order.customer_id == user.id, Order.restaurant_id == restaurant_id)
        .all()
    ]
    my_counts: Counter = Counter()
    cooccur: Counter = Counter()
    if my_order_ids:
        my_lines = (
            db.query(OrderItem).filter(OrderItem.order_id.in_(my_order_ids)).all()
        )
        order_to_items: dict = defaultdict(set)
        for line in my_lines:
            my_counts[line.menu_item_id] += line.quantity
            order_to_items[line.order_id].add(line.menu_item_id)
        for items in order_to_items.values():
            for mid in items:
                cooccur[mid] += 1
                for other in items:
                    if other != mid:
                        cooccur[other] += 1

    max_pop = max(popularity.values()) if popularity else 0
    scored = []
    for m in menu:
        pop_norm = popularity.get(m.id, 0) / max_pop if max_pop else 0.0
        my_norm = min(1.0, my_counts.get(m.id, 0) / 2.0)
        co_norm = min(1.0, cooccur.get(m.id, 0) / 3.0)
        score = 0.5 * pop_norm + 0.3 * co_norm + 0.2 * my_norm

        if my_counts.get(m.id):
            reason = "You order this often"
        elif co_norm > 0.3:
            reason = "People order this together"
        elif pop_norm > 0:
            reason = "Popular at this restaurant"
        else:
            reason = "Fresh on the menu"

        scored.append(
            {
                "menu_item_id": m.id,
                "name": m.name,
                "price": round(m.price, 2),
                "prep_time_min": m.prep_time_min,
                "score": round(score, 3),
                "reason": reason,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return {"items": scored[:5], "fallback": max_pop == 0 and not my_order_ids}


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
