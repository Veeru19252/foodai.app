"""
FoodAI - Shared Google-Maps-style folium builders
==================================================
One consistent look for every map in the app (cart location picker, customer
tracking, delivery panel, admin demand heatmap): light Voyager tiles, a blue
route line with white casing, and icon markers:

    🏪 green store   -> restaurant (origin)
    🤖 red robot     -> delivery bot (rider)
    🏠 purple home   -> receiver / customer (destination)

This module owns the folium UI details so app.py just asks for the map it
needs. It imports folium + tracking, but NOT streamlit / streamlit_folium.
"""

from __future__ import annotations

from typing import Optional, Sequence

import folium

import tracking

# Clean, light tiles that read like Google Maps.
TILES = "CartoDB Voyager"
DEFAULT_ZOOM = 13

# Google Maps route blue, with a white casing to stand out on any base.
ROUTE_COLOR = "#1a73e8"
ROUTE_CASING = "#ffffff"
ROUTE_WEIGHT = 5
ROUTE_CASING_WEIGHT = 8


def styled_map(
    location=tracking.BENGALURU_CENTER, zoom_start: int = DEFAULT_ZOOM
) -> folium.Map:
    """Return a base folium map with the app-wide tile style applied."""
    return folium.Map(location=location, zoom_start=zoom_start, tiles=TILES)


def add_marker(
    m: folium.Map,
    coords: tuple[float, float],
    label: str,
    kind: str,
    tooltip: Optional[str] = None,
) -> None:
    """Add a labeled marker with a per-kind icon + color.

    kind selects the icon: 'restaurant' (green store), 'rider' (red robot),
    or 'receiver' (purple home). Markers need the Font Awesome prefix so the
    glyph actually renders (folium's default glyphicon set lacks these).
    """
    if kind == "restaurant":
        icon = folium.Icon(prefix="fa", icon="store", color="green")
    elif kind == "rider":
        icon = folium.Icon(prefix="fa", icon="robot", color="red")
    else:
        icon = folium.Icon(prefix="fa", icon="home", color="purple")
    folium.Marker(
        coords,
        popup=label,
        tooltip=tooltip or label,
        icon=icon,
    ).add_to(m)


def route_layer(m: folium.Map, route: list) -> None:
    """Draw a route as a Google-blue line with a white casing."""
    folium.PolyLine(
        route, color=ROUTE_CASING, weight=ROUTE_CASING_WEIGHT, opacity=0.9
    ).add_to(m)
    folium.PolyLine(route, color=ROUTE_COLOR, weight=ROUTE_WEIGHT, opacity=0.9).add_to(m)


def fit_route(m: folium.Map, route: list) -> None:
    """Zoom the map to fit the full route with padding."""
    lats = [point[0] for point in route]
    lngs = [point[1] for point in route]
    m.fit_bounds(
        [[min(lats), min(lngs)], [max(lats), max(lngs)]], padding=(30, 30)
    )


def build_delivery_map(
    start: tuple[float, float],
    end: tuple[float, float],
    restaurant_name: str,
    receiver_name: str,
    rider_pos: Optional[tuple[float, float]] = None,
    route: Optional[Sequence] = None,
) -> folium.Map:
    """Return the shared restaurant -> customer tracking map with icon markers.

    The route always runs start (restaurant) to end (receiver/customer). Pass
    ``route`` to draw a road-following route (e.g. from routing.get_route);
    otherwise a straight line is drawn as a fallback. ``rider_pos`` is the
    delivery bot's current position (defaults to the restaurant until pickup
    is logged).
    """
    route = route if route is not None else tracking.build_route(start, end)
    rider_pos = rider_pos if rider_pos is not None else start
    m = styled_map(location=start)
    route_layer(m, route)
    add_marker(m, start, restaurant_name, "restaurant", tooltip="Restaurant")
    add_marker(m, rider_pos, "Delivery bot", "rider", tooltip="Delivery bot")
    add_marker(m, end, receiver_name, "receiver", tooltip="Receiver")
    fit_route(m, route)
    return m


def build_picker_map(
    center: tuple[float, float],
    route: Optional[list] = None,
) -> folium.Map:
    """Return the cart location-picker map.

    Centered on the current delivery point with a receiver pin; when a route
    preview is provided (restaurant -> chosen point) it is drawn Google-Maps
    style and the map zooms to fit it.
    """
    m = styled_map(location=center, zoom_start=14)
    if route is not None:
        route_layer(m, route)
    add_marker(m, center, "Delivery point", "receiver", tooltip="Delivery point")
    if route is not None:
        fit_route(m, route)
    return m


def build_demand_map(zone_anchors: dict, demand: dict) -> folium.Map:
    """Return the admin demand heatmap with the shared tile style.

    zone_anchors maps a zone letter to its (lat, lng); demand maps the zone
    letter to its predicted next-hour order count.
    """
    m = styled_map()
    for zone, anchor in zone_anchors.items():
        value = demand.get(zone, 0.0)
        folium.CircleMarker(
            location=anchor,
            radius=14,
            popup=f"Zone {zone}: {value:.1f} predicted orders",
            tooltip=f"Zone {zone}",
            fill=True,
            fill_color=_demand_color(value),
            fill_opacity=0.75,
            color="black",
            weight=1,
        ).add_to(m)
    return m


def _demand_color(value: float) -> str:
    """Return a heat color for a predicted demand value (green -> red)."""
    if value < 2.0:
        return "green"
    if value < 4.0:
        return "yellow"
    if value < 6.0:
        return "orange"
    return "red"
