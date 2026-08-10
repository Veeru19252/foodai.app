"""
FoodAI - Live delivery tracking helpers (pure Python)
=====================================================

Pure, dependency-free helpers for the live order-tracking feature. This module
intentionally does NOT import streamlit, streamlit_folium, or folium, so every
function can be exercised from a plain ``python3`` REPL with no extra packages.

Design decisions
----------------
* Restaurant coordinates are resolved from the ``COORDINATES`` dict keyed by
  ``restaurant_id`` (1-15), matching the order of ``backend/seed.py
  RESTAURANTS``. The restaurants table also carries lat/lng columns (migration
  ``e7d4a6f2b8c1``); ``backend/tracking_state.restaurant_start`` prefers those
  and falls back to this dict, so this module stays pure and runnable without
  the database.
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

# Pan-India reference: used as a generic fallback / reference point.
BENGALURU_CENTER = (12.9716, 77.5946)

# Assumed average delivery-vehicle speed for ETA estimates (km/h).
AVG_SPEED_KMH = 25.0

# Plausible coordinates keyed by restaurant_id (1-15) — one branch per major
# Indian city so the demo is pan-India. Order matches backend/seed.py
# RESTAURANTS: 1=Spice Garden, 2=Dosa Plaza, 3=Wok This Way, 4=Pizza Junction,
# 5=Burger Barn (Bengaluru), 6=Delhi 6, 7=Karim's (New Delhi), 8=Bombay
# Canteen, 9=Bademiya (Mumbai), 10=Paradise Biryani (Hyderabad),
# 11=Saravana Bhavan (Chennai), 12=Peter Cat (Kolkata), 13=Vaishali (Pune),
# 14=Chokhi Dhani (Jaipur), 15=Rajwadu (Ahmedabad).
COORDINATES = {
    1: (12.975, 77.606),   # Spice Garden, MG Road, Bengaluru
    2: (12.982, 77.619),   # Dosa Plaza, Lake View Road (Ulsoor), Bengaluru
    3: (12.977, 77.596),   # Wok This Way, City Center, Bengaluru
    4: (13.004, 77.610),   # Pizza Junction, Main Street (Frazer Town), Bengaluru
    5: (12.970, 77.750),   # Burger Barn, Tech Park (Whitefield), Bengaluru
    6: (28.6315, 77.2167), # Delhi 6, Connaught Place, New Delhi
    7: (28.6505, 77.2332), # Karim's, Jama Masjid, New Delhi
    8: (19.0126, 72.8360), # Bombay Canteen, Lower Parel, Mumbai
    9: (18.9169, 72.8265), # Bademiya, Colaba, Mumbai
    10: (17.4435, 78.4977), # Paradise Biryani, Paradise Circle, Hyderabad
    11: (13.0418, 80.2341), # Saravana Bhavan, T. Nagar, Chennai
    12: (22.5528, 88.3522), # Peter Cat, Park Street, Kolkata
    13: (18.5314, 73.8446), # Vaishali, FC Road, Pune
    14: (26.8439, 75.8105), # Chokhi Dhani, Tonk Road, Jaipur
    15: (22.9904, 72.5005), # Rajwadu, Sarkhej, Ahmedabad
}

# Fixed customer delivery point (fallback when an order has no stored
# delivery location).
DEFAULT_CUSTOMER_HOME = (12.9719, 77.6412)

# Preset delivery areas a customer can pick at checkout — pan-India. Each
# entry is (label, city, default address, (lat, lng)); coordinates sit inside
# the same city as the restaurants listed in COORDINATES.
DELIVERY_PRESETS = [
    # Bengaluru
    ("MG Road / Indiranagar", "Bengaluru", "Hostel Block C, MG Road", (12.9719, 77.6412)),
    ("Koramangala", "Bengaluru", "5th Block, Koramangala", (12.9352, 77.6245)),
    ("HSR Layout", "Bengaluru", "Sector 1, HSR Layout", (12.9116, 77.6387)),
    ("Whitefield", "Bengaluru", "ITPL Main Road, Whitefield", (12.9698, 77.7500)),
    ("City Center", "Bengaluru", "MG Road Metro, City Center", (12.9770, 77.5960)),
    # New Delhi
    ("Connaught Place", "New Delhi", "Barakhamba Road, Connaught Place", (28.6315, 77.2167)),
    ("Karol Bagh", "New Delhi", "Ajmal Khan Road, Karol Bagh", (28.6519, 77.1909)),
    ("Saket", "New Delhi", "District Centre, Saket", (28.5245, 77.2066)),
    ("Dwarka", "New Delhi", "Sector 12, Dwarka", (28.5857, 77.0424)),
    # Mumbai
    ("Bandra West", "Mumbai", "Linking Road, Bandra West", (19.0596, 72.8295)),
    ("Andheri West", "Mumbai", "Lokhandwala, Andheri West", (19.1364, 72.8263)),
    ("Colaba", "Mumbai", "Shahid Bhagat Singh Road, Colaba", (18.9169, 72.8265)),
    ("Powai", "Mumbai", "Hiranandani Gardens, Powai", (19.1176, 72.9060)),
    # Hyderabad
    ("Banjara Hills", "Hyderabad", "Road No 12, Banjara Hills", (17.4156, 78.4347)),
    ("Gachibowli", "Hyderabad", "Financial District, Gachibowli", (17.4401, 78.3489)),
    ("Madhapur", "Hyderabad", "Hitech City Road, Madhapur", (17.4483, 78.3915)),
    # Chennai
    ("T. Nagar", "Chennai", "Usman Road, T. Nagar", (13.0418, 80.2341)),
    ("Anna Nagar", "Chennai", "2nd Avenue, Anna Nagar", (13.0850, 80.2101)),
    ("Velachery", "Chennai", "100 Feet Road, Velachery", (12.9791, 80.2208)),
    # Kolkata
    ("Park Street", "Kolkata", "Park Street Area", (22.5528, 88.3522)),
    ("Salt Lake", "Kolkata", "Sector V, Salt Lake", (22.5806, 88.4175)),
    ("Howrah", "Kolkata", "Grand Trunk Road, Howrah", (22.5958, 88.2636)),
    # Pune
    ("Koregaon Park", "Pune", "North Main Road, Koregaon Park", (18.5362, 73.8940)),
    ("Hinjewadi", "Pune", "Phase 1, Hinjewadi", (18.5913, 73.7389)),
    ("Viman Nagar", "Pune", "Clover Park, Viman Nagar", (18.5679, 73.9143)),
    # Jaipur
    ("Malviya Nagar", "Jaipur", "Tonk Road, Malviya Nagar", (26.8551, 75.8099)),
    ("C-Scheme", "Jaipur", "Ashok Marg, C-Scheme", (26.9060, 75.7856)),
    ("Vaishali Nagar", "Jaipur", "Amrapali Marg, Vaishali Nagar", (26.9169, 75.7402)),
    # Ahmedabad
    ("Satellite", "Ahmedabad", "Jodhpur Cross Road, Satellite", (23.0333, 72.5086)),
    ("Maninagar", "Ahmedabad", "Jawaharlal Nehru Road, Maninagar", (23.0120, 72.5914)),
    ("Bodakdev", "Ahmedabad", "Sindhu Bhavan Road, Bodakdev", (23.0452, 72.5100)),
]

# City centre anchors used by the checkout map when a city is selected.
CITY_CENTERS = {
    "Bengaluru": (12.9716, 77.5946),
    "New Delhi": (28.6139, 77.2090),
    "Mumbai": (19.0760, 72.8777),
    "Hyderabad": (17.3850, 78.4867),
    "Chennai": (13.0827, 80.2707),
    "Kolkata": (22.5726, 88.3639),
    "Pune": (18.5204, 73.8567),
    "Jaipur": (26.9124, 75.7873),
    "Ahmedabad": (23.0225, 72.5714),
}


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
    for preset_label, _city, _address, coords in DELIVERY_PRESETS:
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
        preset_address for l, _city, preset_address, _coords in DELIVERY_PRESETS if l == label
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
