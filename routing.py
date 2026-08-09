"""
FoodAI - Road-following routes via OSRM
========================================
Replaces straight-line routes with routes that follow real roads (turns,
U-turns) using the free public OSRM driving API. Falls back to a straight line
when no router is reachable, so the app keeps working offline.

    from routing import get_route
    route, distance_km = get_route((12.975, 77.606), (12.9719, 77.6412))

    route       : tuple of (lat, lng) points along roads (decimated to MAX_POINTS)
    distance_km : road distance in km from OSRM (haversine on fallback)

Results are cached per start/end pair: the tracking page auto-refreshes every
2.5 seconds, so the router is only hit once per unique pair. Route points use
the same (lat, lng) format as tracking.build_route, so interpolation and ETA
helpers keep working unchanged.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

import requests

import tracking

# Public OSRM servers, HTTP first: some builds/networks (e.g. LibreSSL on
# macOS) reject the TLS handshake to these hosts while plain HTTP works.
OSRM_BASES = (
    "http://router.project-osrm.org/route/v1/driving/",
    "http://routing.openstreetmap.de/routed-car/route/v1/driving/",
    "https://router.project-osrm.org/route/v1/driving/",
    "https://routing.openstreetmap.de/routed-car/route/v1/driving/",
)
TIMEOUT_SECONDS = 4.0
MAX_POINTS = 200  # decimate long polylines for fast maps + interpolation


def _decimate(points: list, max_points: int) -> list:
    """Evenly sample points down to max_points, keeping both endpoints."""
    if len(points) <= max_points:
        return points
    indices = {
        round(i * (len(points) - 1) / (max_points - 1)) for i in range(max_points)
    }
    return [points[i] for i in sorted(indices)]


def _fetch_osrm(
    start: tuple[float, float], end: tuple[float, float]
) -> Optional[tuple[list, float]]:
    """Return (route_points, distance_km) from the first reachable OSRM server.

    The OSRM driving API expects "lon,lat;lon,lat" and returns GeoJSON
    LineString coordinates as [lng, lat]; we convert back to (lat, lng) to
    match the rest of the app. Returns None when every server fails or yields
    no route.
    """
    coordinates = f"{start[1]},{start[0]};{end[1]},{end[0]}"
    for base in OSRM_BASES:
        try:
            data = requests.get(
                f"{base}{coordinates}?overview=full&geometries=geojson&steps=false",
                timeout=TIMEOUT_SECONDS,
            ).json()
            routes = data.get("routes") or []
            if not routes:
                continue
            coords = routes[0].get("geometry", {}).get("coordinates") or []
            points = [(lat, lng) for lng, lat in coords]
            if len(points) < 2:
                continue
            distance_km = float(routes[0].get("distance", 0.0)) / 1000.0
            return _decimate(points, MAX_POINTS), distance_km
        except Exception:
            continue
    return None


@lru_cache(maxsize=256)
def get_route(
    start: tuple[float, float], end: tuple[float, float]
) -> tuple[tuple[tuple[float, float], ...], float]:
    """Return (route_points, distance_km) following real roads, cached.

    Falls back to a straight-line route with haversine distance when every
    OSRM server is unreachable, so the result is always a valid route.
    """
    result = _fetch_osrm(start, end)
    if result is not None:
        points, distance_km = result
        return tuple(points), distance_km
    points = tracking.build_route(start, end)
    return tuple(points), tracking.route_length_km(points)
