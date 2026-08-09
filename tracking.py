"""
FoodAI - Live delivery tracking helpers (pure Python)
=====================================================

Pure, dependency-free helpers for the live order-tracking feature. This module
intentionally does NOT import streamlit, streamlit_folium, or folium, so every
function can be exercised from a plain ``python3`` REPL with no extra packages.

Design decisions
----------------
* Restaurant coordinates are resolved from the ``COORDINATES`` dict keyed by
  ``restaurant_id`` (1-5), matching the order of ``seed_data.RESTAURANTS``.
  The restaurants table has no lat/lng columns, so no schema migration is done.
* All functions are pure: the same input always produces the same output.

How to test (no third-party packages needed)
--------------------------------------------
    python3 -c "from tracking import restaurant_coordinates; print(restaurant_coordinates(1))"
    python3 -c "from tracking import build_route; print(build_route((12.97, 77.59), (12.97, 77.64)))"
    python3 check_tracking.py   # if present in the repo
"""

from __future__ import annotations

import math
from typing import Optional

# Bengaluru city center, used as a generic fallback / reference point.
BENGALURU_CENTER = (12.9716, 77.5946)

# Assumed average delivery-vehicle speed for ETA estimates (km/h).
AVG_SPEED_KMH = 25.0

# Plausible Bengaluru coordinates keyed by restaurant_id (1-5).
# Order matches seed_data.RESTAURANTS: 1=Spice Garden, 2=Dosa Plaza,
# 3=Wok This Way, 4=Pizza Junction, 5=Burger Barn. All points sit inside
# bbox lat ~12.80-13.10, lng ~77.40-77.80.
COORDINATES = {
    1: (12.975, 77.606),   # Spice Garden, MG Road
    2: (12.982, 77.619),   # Dosa Plaza, Lake View Road (Ulsoor)
    3: (12.977, 77.596),   # Wok This Way, City Center
    4: (13.004, 77.610),   # Pizza Junction, Main Street (Frazer Town)
    5: (12.970, 77.750),   # Burger Barn, Tech Park (Whitefield)
}

# Fixed customer delivery point near Indiranagar (fallback when an order has
# no stored delivery location).
DEFAULT_CUSTOMER_HOME = (12.9719, 77.6412)

# Preset delivery areas a customer can pick at checkout. Each entry is
# (label, default address, (lat, lng)); the coordinates sit inside the same
# Bengaluru bbox as the restaurant COORDINATES.
DELIVERY_PRESETS = [
    ("MG Road / Indiranagar", "Hostel Block C, MG Road", (12.9719, 77.6412)),
    ("Koramangala", "5th Block, Koramangala", (12.9352, 77.6245)),
    ("HSR Layout", "Sector 1, HSR Layout", (12.9116, 77.6387)),
    ("Whitefield", "ITPL Main Road, Whitefield", (12.9698, 77.7500)),
    ("City Center", "MG Road Metro, City Center", (12.9770, 77.5960)),
]


def restaurant_coordinates(restaurant_id: int) -> tuple[float, float]:
    """Return (lat, lng) for a restaurant_id, raising ValueError if unknown."""
    try:
        return COORDINATES[restaurant_id]
    except KeyError:
        raise ValueError(
            f"Unknown restaurant_id {restaurant_id!r}; expected one of {sorted(COORDINATES)}."
        ) from None


def customer_home_coordinates() -> tuple[float, float]:
    """Return the fallback customer home coordinates (near Indiranagar)."""
    return DEFAULT_CUSTOMER_HOME


def preset_coordinates(label: str) -> tuple[float, float]:
    """Return (lat, lng) for a DELIVERY_PRESETS label, raising ValueError if unknown."""
    for preset_label, _address, coords in DELIVERY_PRESETS:
        if preset_label == label:
            return coords
    raise ValueError(
        f"Unknown delivery preset {label!r}; expected one of {[p[0] for p in DELIVERY_PRESETS]}."
    )


def resolve_delivery_location(
    preset_label: Optional[str],
    map_click: Optional[dict],
    address_input: Optional[str],
) -> dict:
    """Resolve the customer's chosen delivery point into a location dict.

    Returns {"address": str, "lat": float, "lng": float}. A map click overrides
    the preset; when neither is available it falls back to the first preset's
    coordinates. The address comes from the text input, or the preset's default
    address / a generic label for custom clicks.
    """
    if (
        map_click is not None
        and map_click.get("lat") is not None
        and map_click.get("lng") is not None
    ):
        address = (address_input or "").strip() or "Custom delivery point"
        return {
            "address": address,
            "lat": float(map_click["lat"]),
            "lng": float(map_click["lng"]),
        }
    label = preset_label or DELIVERY_PRESETS[0][0]
    lat, lng = preset_coordinates(label)
    address = (address_input or "").strip() or next(
        preset_address for l, preset_address, _coords in DELIVERY_PRESETS if l == label
    )
    return {"address": address, "lat": lat, "lng": lng}


def build_route(
    start: tuple[float, float],
    end: tuple[float, float],
    num_points: int = 5,
) -> list[tuple[float, float]]:
    """Return a straight-line route from start to end with num_points points.

    Points are evenly spaced; route[0] == start and route[-1] == end.
    Deterministic: same inputs always produce the same route.
    """
    if num_points < 2:
        raise ValueError(f"num_points must be >= 2, got {num_points}")
    steps = num_points - 1
    lat_delta = end[0] - start[0]
    lng_delta = end[1] - start[1]
    return [
        (start[0] + lat_delta * i / steps, start[1] + lng_delta * i / steps)
        for i in range(num_points)
    ]


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return the great-circle distance between (lat, lng) points in km."""
    earth_radius_km = 6371.0
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    d_lat = lat2 - lat1
    d_lng = lng2 - lng1
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    )
    return 2 * earth_radius_km * math.asin(math.sqrt(h))


def route_length_km(route: list) -> float:
    """Return the total distance of a route as the sum of its segments in km."""
    return sum(
        haversine_km(route[i], route[i + 1]) for i in range(len(route) - 1)
    )


def _walk_route(
    route: list, distance_km: float
) -> tuple[float, float]:
    """Return the position after walking distance_km along the route.

    Private helper shared by ``interpolate_position`` and ``compute_eta`` so the
    covered-distance bookkeeping lives in exactly one place. The result always
    lies exactly on the route (on the straight segment currently being walked).
    """
    if len(route) == 1 or distance_km <= 0.0:
        return route[0]
    walked = 0.0
    for i in range(len(route) - 1):
        start, end = route[i], route[i + 1]
        segment_km = haversine_km(start, end)
        if walked + segment_km >= distance_km:
            fraction = 0.0 if segment_km == 0 else (distance_km - walked) / segment_km
            return (
                start[0] + (end[0] - start[0]) * fraction,
                start[1] + (end[1] - start[1]) * fraction,
            )
        walked += segment_km
    return route[-1]


def interpolate_position(route: list, progress: float) -> tuple[float, float]:
    """Return the route position at progress in [0.0, 1.0] (clamped).

    Walks cumulative segment lengths, so the result always lies exactly on the
    route: progress 0.0 -> route[0], progress 1.0 -> route[-1].
    """
    if not route:
        raise ValueError("route must contain at least one point")
    progress = min(1.0, max(0.0, progress))
    if progress == 1.0:
        return route[-1]
    total_km = route_length_km(route)
    if total_km == 0.0:
        return route[0]
    return _walk_route(route, progress * total_km)


def estimate_trip_seconds(
    route: list, avg_speed_kmh: float = AVG_SPEED_KMH
) -> int:
    """Return the total travel seconds for the full route, rounded."""
    return round(route_length_km(route) / avg_speed_kmh * 3600)


def compute_eta(
    route: list, progress: float, avg_speed_kmh: float = AVG_SPEED_KMH
) -> int:
    """Return remaining travel minutes (ceil) at progress in [0.0, 1.0].

    Remaining distance is (1 - progress) * route length, consistent with
    ``interpolate_position``. Returns the full-trip minutes at 0.0 and 0 at 1.0.
    """
    progress = min(1.0, max(0.0, progress))
    remaining_km = (1.0 - progress) * route_length_km(route)
    return math.ceil(remaining_km / avg_speed_kmh * 60)


def format_eta(minutes: int) -> str:
    """Format an ETA in minutes as '~N min'."""
    return f"~{minutes} min"


def format_distance(km: float) -> str:
    """Format a distance in km with one decimal place, e.g. '3.4 km'."""
    return f"{km:.1f} km"
