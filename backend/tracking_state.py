"""
FoodAI backend - shared tracking state
=======================================
Pure-ish helpers that compute a live tracking state for an order using the
existing ML/route modules (tracking.py, routing.py, eta_service.py). Used by
both the REST tracking endpoint and the WebSocket simulation so the two views
can never drift apart.
"""

import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import eta_service
import routing
import tracking

from backend.models import Delivery, Order


def delivery_end(order: Order) -> Tuple[float, float]:
    """Return the order's stored delivery point, else the default home."""
    if order.delivery_lat is not None and order.delivery_lng is not None:
        return (order.delivery_lat, order.delivery_lng)
    return tracking.DEFAULT_CUSTOMER_HOME


def order_route(order: Order):
    """Return (route, distance_km) along real roads for an order.

    route is a tuple of (lat, lng) points; distance_km is the OSRM road
    distance (or haversine fallback). Cached per start/end pair. Restaurants
    created at runtime (no legacy coordinate) fall back to the demo home.
    """
    try:
        start = tracking.restaurant_coordinates(order.restaurant_id)
    except ValueError:
        start = tracking.DEFAULT_CUSTOMER_HOME
    end = delivery_end(order)
    return routing.get_route(start, end)


def rider_progress(
    order: Order, delivery: Optional[Delivery]
) -> Tuple[float, Tuple[float, float]]:
    """Return (progress 0..1, rider position) for a delivery.

    Before pickup the rider sits at the restaurant (progress 0). Afterwards
    progress is elapsed time over the trip estimate, walking the road route so
    the marker makes real turns.
    """
    start = tracking.restaurant_coordinates(order.restaurant_id)
    if delivery is None or delivery.pickup_time is None:
        return 0.0, start
    route, _ = order_route(order)
    pickup_epoch = _to_epoch_utc(delivery.pickup_time)
    elapsed = time.time() - pickup_epoch
    total_seconds = tracking.estimate_trip_seconds(list(route), tracking.AVG_SPEED_KMH)
    progress = min(1.0, max(0.0, elapsed / total_seconds)) if total_seconds > 0 else 1.0
    rider_pos = tracking.interpolate_position(list(route), progress)
    return progress, rider_pos


def eta_for_order(order: Order, progress: float) -> Tuple[Optional[float], str]:
    """Return (eta_min, source) using the existing ML pipeline (fallback-safe)."""
    route, _ = order_route(order)
    return eta_service.best_eta(
        list(route),
        progress,
        order.restaurant_id,
        prep_time_min=15,
        customer_home=delivery_end(order),
    )


def build_tracking_state(order: Order, delivery: Optional[Delivery]) -> dict:
    """Return the TrackingState dict for an order."""
    route, distance_km = order_route(order)
    progress, rider_pos = rider_progress(order, delivery)
    eta_min, eta_source = eta_for_order(order, progress)
    return {
        "order_id": order.id,
        "status": order.status,
        "restaurant_id": order.restaurant_id,
        "restaurant_name": order.restaurant.name if order.restaurant else "",
        "customer_name": order.customer.name if order.customer else "",
        "delivery_address": order.delivery_address,
        "route": [[lat, lng] for lat, lng in route],
        "route_distance_km": round(distance_km, 2),
        "rider_lat": round(rider_pos[0], 6),
        "rider_lng": round(rider_pos[1], 6),
        "progress": round(progress, 4),
        "eta_min": eta_min,
        "eta_source": eta_source,
    }


def _to_epoch_utc(value: datetime) -> float:
    """Convert a (possibly naive-UTC) datetime to an epoch float."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()
