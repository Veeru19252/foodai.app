"""FoodAI UI package: shared design-system renderers for the Streamlit app.

Public API (re-exported from ``ui.theme``):
    inject_css          - inject the one-time <style> design system block
    page_header         - branded page title + subtitle
    restaurant_card     - restaurant listing card
    menu_row            - single menu item line
    status_badge        - colored pill for an order status
    status_stepper      - horizontal order-progress stepper
    header_bar          - branded top bar with user chip + cart count
"""

from .theme import (
    header_bar,
    inject_css,
    menu_row,
    page_header,
    restaurant_card,
    status_badge,
    status_stepper,
)

__all__ = [
    "header_bar",
    "inject_css",
    "menu_row",
    "page_header",
    "restaurant_card",
    "status_badge",
    "status_stepper",
]
