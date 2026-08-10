"""
FoodAI backend - shared tracking state
=======================================
Pure-ish helpers that compute a live tracking state for an order using the
existing ML/route modules (tracking.py, routing.py, eta_service.py). Used by
both the REST tracking endpoint and the WebSocket simulation so the two views
can never drift apart.
"""

import math
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


LIVE_POSITION_TTL_SECONDS = 60.0


def live_driver_position(order: Order) -> Optional[Tuple[float, float]]:
    """Return the driver's live GPS fix when it is fresh enough to trust.

    A fix older than LIVE_POSITION_TTL_SECONDS is treated as stale and the
    simulated rider is used instead, so a driver whose phone loses signal
    degrades gracefully instead of freezing the marker.
    """
    if (
        order.driver_lat is None
        or order.driver_lng is None
        or order.driver_updated_at is None
    ):
        return None
    age = time.time() - _to_epoch_utc(order.driver_updated_at)
    if age > LIVE_POSITION_TTL_SECONDS:
        return None
    return (order.driver_lat, order.driver_lng)


def progress_at_position(order: Order, lat: float, lng: float) -> float:
    """Estimate 0..1 progress from a live GPS fix against the road route.

    Projects the fix onto the nearest route *segment* (not just the nearest
    vertex), so successive GPS fixes move the progress smoothly and the ETA
    never jumps between vertices. Falls back to 0.0 when the route has no
    length (e.g. the rider has not left the pickup yet).
    """
    route, _ = order_route(order)
    if not route or len(route) < 2:
        return 0.0
    point = (lat, lng)

    cumulative = [0.0]
    acc = 0.0
    for i in range(1, len(route)):
        acc += tracking.haversine_km(route[i - 1], route[i])
        cumulative.append(acc)
    total = acc
    if total == 0.0:
        return 0.0

    best_seg_dist = float("inf")
    best_cum = 0.0
    for i in range(len(route) - 1):
        a, b = route[i], route[i + 1]
        ab = tracking.haversine_km(a, b)
        if ab == 0.0:
            continue
        ap = tracking.haversine_km(a, point)
        bp = tracking.haversine_km(point, b)
        # Projection parameter of P onto segment AB (law of cosines).
        t = (ap * ap - bp * bp + ab * ab) / (2.0 * ab * ab)
        t = min(1.0, max(0.0, t))
        if 0.0 < t < 1.0:
            height_sq = ap * ap - (t * ab) * (t * ab)
            seg_dist = math.sqrt(max(0.0, height_sq))
        else:
            seg_dist = min(ap, bp)
        if seg_dist < best_seg_dist:
            best_seg_dist = seg_dist
            best_cum = cumulative[i] + t * ab

    return min(1.0, max(0.0, best_cum / total))


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
    live = live_driver_position(order)
    position_source = "simulated"
    if live is not None:
        rider_pos = live
        progress = progress_at_position(order, live[0], live[1])
        position_source = "live"
    eta_min, eta_source = eta_for_order(order, progress)
    return {
        "order_id": order.id,
        "status": order.status,
        "restaurant_id": order.restaurant_id,
        "restaurant_name": order.restaurant.name if order.restaurant else "",
        "customer_name": order.customer.name if order.customer else "",
        "delivery_address": order.delivery_address,
        "created_at": order.created_at,
        "pickup_time": delivery.pickup_time if delivery else None,
        "delivered_time": delivery.delivered_time if delivery else None,
        "route": [[lat, lng] for lat, lng in route],
        "route_distance_km": round(distance_km, 2),
        "rider_lat": round(rider_pos[0], 6),
        "rider_lng": round(rider_pos[1], 6),
        "progress": round(progress, 4),
        "eta_min": eta_min,
        "eta_source": eta_source,
        "position_source": position_source,
    }


def _to_epoch_utc(value: datetime) -> float:
    """Convert a (possibly naive-UTC) datetime to an epoch float."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()
