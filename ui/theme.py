"""FoodAI design system: CSS theme tokens + pure-function HTML renderers.

This module is the single source of truth for the FoodAI visual language:
an orange food-delivery brand (#FF5A1F family), Inter typography, rounded
cards, pill buttons, and semantic status colors.

Design rules
------------
* Importing this module has NO side effects — no ``st.*`` calls happen at
  import time. ``inject_css()`` imports Streamlit lazily and is the only
  function that touches ``st``.
* Renderers are pure functions: same input -> same output, no DB access,
  no global state, each under 50 lines.
* Python 3.9-compatible type hints (``Optional[...]``, never ``X | None``).
* No Bootstrap blue (#007bff). Status colors stay in the green/orange/
  blue/gray family per order state.
"""

from html import escape

# ---------------------------------------------------------------------------
# Design tokens + component styles (one <style> block, injected by inject_css)
# ---------------------------------------------------------------------------

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    /* Brand — food-delivery orange */
    --foodai-primary: #FF5A1F;
    --foodai-primary-dark: #E54A12;
    --foodai-primary-darker: #C43C0C;
    --foodai-primary-soft: #FFEDE5;
    --foodai-primary-softer: #FFF7F2;

    /* Surfaces */
    --foodai-bg: #FBF6F2;
    --foodai-surface: #FFFFFF;
    --foodai-text: #201A16;
    --foodai-text-muted: #6F6761;
    --foodai-border: rgba(32, 26, 22, 0.08);

    /* Status colors (green / orange / blue / gray family) */
    --foodai-green: #1E9E58;
    --foodai-green-soft: #E4F6EC;
    --foodai-orange: #E07A1B;
    --foodai-orange-soft: #FCF0DF;
    --foodai-blue: #2563EB;
    --foodai-blue-soft: #E9F0FE;
    --foodai-indigo: #4F46E5;
    --foodai-indigo-soft: #ECEAFD;
    --foodai-gray: #857E78;
    --foodai-gray-soft: #F0EEEC;

    /* Shape */
    --foodai-radius-lg: 22px;
    --foodai-radius-md: 14px;
    --foodai-radius-pill: 9999px;

    /* Elevation */
    --foodai-shadow-sm: 0 1px 2px rgba(32, 26, 22, 0.04), 0 2px 10px rgba(32, 26, 22, 0.05);
    --foodai-shadow-md: 0 6px 20px rgba(32, 26, 22, 0.08);
    --foodai-shadow-lg: 0 14px 40px rgba(32, 26, 22, 0.12);

    /* Type */
    --foodai-font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;

    /* Spacing scale (4px base) */
    --foodai-space-1: 0.25rem;
    --foodai-space-2: 0.5rem;
    --foodai-space-3: 0.75rem;
    --foodai-space-4: 1rem;
    --foodai-space-6: 1.5rem;
    --foodai-space-8: 2rem;
}

/* ---- Base app surface ------------------------------------------------- */
html, body, .stApp {
    font-family: var(--foodai-font);
    color: var(--foodai-text);
}
.stApp {
    background: var(--foodai-bg);
}

/* ---- Full-bleed: hide default chrome ---------------------------------- */
#MainMenu { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
div[data-testid="stToolbar"] { display: none !important; }
div[data-testid="stDecoration"] { display: none !important; }
footer { display: none !important; }
.stDeployButton { display: none !important; }
[data-testid="stStatusWidget"] { display: none !important; }

[data-testid="stSidebar"] {
    background: var(--foodai-surface);
    border-right: 1px solid var(--foodai-border);
}

/* ---- Branded top bar -------------------------------------------------- */
.foodai-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--foodai-space-3);
    background: var(--foodai-surface);
    border: 1px solid var(--foodai-border);
    border-radius: var(--foodai-radius-lg);
    padding: var(--foodai-space-3) 1.25rem;
    box-shadow: var(--foodai-shadow-sm);
    margin-bottom: var(--foodai-space-6);
}
.foodai-logo {
    display: inline-flex;
    align-items: center;
    gap: var(--foodai-space-2);
    font-size: 1.35rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: var(--foodai-primary);
}
.user-chip {
    display: inline-flex;
    align-items: center;
    gap: var(--foodai-space-2);
    background: var(--foodai-primary-soft);
    color: var(--foodai-primary-darker);
    padding: 0.4rem 1rem;
    border-radius: var(--foodai-radius-pill);
    font-size: 0.875rem;
    font-weight: 600;
}
.cart-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.5rem;
    height: 1.5rem;
    padding: 0 0.4rem;
    border-radius: var(--foodai-radius-pill);
    background: var(--foodai-primary);
    color: #ffffff;
    font-size: 0.75rem;
    font-weight: 700;
}

/* ---- Page header ------------------------------------------------------ */
.page-header {
    padding: 0.25rem 0 1rem;
    margin-bottom: 1.25rem;
}
.page-header h1 {
    margin: 0;
    color: var(--foodai-text);
    font-size: 2.2rem;
    line-height: 1.15;
    font-weight: 800;
    letter-spacing: -0.02em;
}
.page-header p {
    margin: 0.5rem 0 0;
    color: var(--foodai-text-muted);
    font-size: 1rem;
}

/* ---- Cards ------------------------------------------------------------ */
.restaurant-card, .order-card {
    box-sizing: border-box;
    width: 100%;
    background: var(--foodai-surface);
    border: 1px solid var(--foodai-border);
    border-radius: var(--foodai-radius-lg);
    padding: 1.25rem;
    box-shadow: var(--foodai-shadow-sm);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.restaurant-card:hover, .order-card:hover {
    transform: translateY(-3px);
    box-shadow: var(--foodai-shadow-lg);
}
.restaurant-card h3, .order-card h3 {
    margin: 0 0 0.5rem;
    color: var(--foodai-text);
    font-size: 1.15rem;
    font-weight: 700;
}
.restaurant-meta {
    margin-bottom: 0.9rem;
    color: var(--foodai-text-muted);
    font-size: 0.95rem;
}
.restaurant-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.3rem 0.75rem;
    border-radius: var(--foodai-radius-pill);
    background: var(--foodai-primary-soft);
    color: var(--foodai-primary-darker);
    font-weight: 700;
    font-size: 0.85rem;
}

/* ---- Menu row --------------------------------------------------------- */
.menu-item-row {
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--foodai-space-4);
    padding: 0.8rem 0;
    border-bottom: 1px solid var(--foodai-border);
}
.menu-item-row:last-child { border-bottom: none; }
.menu-item-row__name { font-weight: 600; color: var(--foodai-text); }
.menu-item-row__meta { color: var(--foodai-text-muted); font-size: 0.9rem; white-space: nowrap; }

/* ---- Status badge ----------------------------------------------------- */
.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.3rem 0.8rem;
    border-radius: var(--foodai-radius-pill);
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    text-transform: uppercase;
}
.badge-placed { background: var(--foodai-gray-soft); color: var(--foodai-gray); }
.badge-confirmed { background: var(--foodai-blue-soft); color: var(--foodai-blue); }
.badge-preparing { background: var(--foodai-orange-soft); color: var(--foodai-orange); }
.badge-out { background: var(--foodai-indigo-soft); color: var(--foodai-indigo); }
.badge-delivered { background: var(--foodai-green-soft); color: var(--foodai-green); }

/* ---- Status stepper --------------------------------------------------- */
.status-stepper {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin: 1rem 0 0.25rem;
    padding: 0.5rem 0.25rem;
}
.stepper-step {
    position: relative;
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.4rem;
    text-align: center;
}
.stepper-step:not(:first-child)::before {
    content: "";
    position: absolute;
    top: 13px;
    left: calc(-50% + 16px);
    right: calc(50% + 16px);
    height: 3px;
    border-radius: 2px;
    background: var(--foodai-gray-soft);
}
.stepper-step.is-complete:not(:first-child)::before,
.stepper-step.is-current:not(:first-child)::before {
    background: var(--foodai-primary);
}
.stepper-dot {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: var(--foodai-gray-soft);
    color: var(--foodai-gray);
    font-size: 0.75rem;
    font-weight: 700;
    transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}
.stepper-step.is-complete .stepper-dot { background: var(--foodai-primary); color: #ffffff; }
.stepper-step.is-current .stepper-dot {
    background: var(--foodai-surface);
    color: var(--foodai-primary);
    border: 3px solid var(--foodai-primary);
}
.stepper-label {
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--foodai-text-muted);
    max-width: 90px;
}
.stepper-step.is-current .stepper-label {
    color: var(--foodai-primary-darker);
    font-weight: 700;
}

/* ---- Pill nav (horizontal radio-as-pills) ----------------------------- */
[data-testid="stRadioGroup"] [role="radiogroup"] {
    display: flex;
    flex-wrap: wrap;
    gap: var(--foodai-space-2);
}
[data-testid="stRadioGroup"] label {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.55rem 1.15rem;
    margin: 0;
    background: var(--foodai-surface);
    border: 1px solid var(--foodai-border);
    border-radius: var(--foodai-radius-pill);
    color: var(--foodai-text-muted);
    font-weight: 600;
    font-size: 0.9rem;
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}
[data-testid="stRadioGroup"] label:hover {
    border-color: var(--foodai-primary);
    color: var(--foodai-primary);
}
[data-testid="stRadioGroup"] label:has(input:checked) {
    background: var(--foodai-primary);
    border-color: var(--foodai-primary);
    color: #ffffff;
}
[data-testid="stRadioGroup"] input {
    position: absolute !important;
    width: 1px !important;
    height: 1px !important;
    opacity: 0 !important;
    overflow: hidden !important;
}
[data-testid="stRadioGroup"] label > div:first-child {
    display: none !important;
}

/* ---- Buttons ---------------------------------------------------------- */
[data-testid="stButton"] button {
    border-radius: var(--foodai-radius-pill);
    font-weight: 600;
    padding: 0.6rem 1.4rem;
    transition: transform 0.15s ease, box-shadow 0.15s ease, background-color 0.15s ease;
}
[data-testid="stButton"] button:hover {
    transform: translateY(-1px);
    box-shadow: var(--foodai-shadow-md);
}
[data-testid="stBaseButton-primary"],
[data-testid="stButton"] button[kind="primary"] {
    background-color: var(--foodai-primary);
    color: #ffffff;
    border: 1px solid var(--foodai-primary);
}
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stButton"] button[kind="primary"]:hover {
    background-color: var(--foodai-primary-dark);
}

/* ---- Metrics ---------------------------------------------------------- */
[data-testid="stMetric"] {
    background: var(--foodai-surface);
    border: 1px solid var(--foodai-border);
    border-radius: var(--foodai-radius-lg);
    padding: 1rem 1.25rem;
    box-shadow: var(--foodai-shadow-sm);
}
[data-testid="stMetricLabel"] { color: var(--foodai-text-muted); font-weight: 500; }
[data-testid="stMetricValue"] { color: var(--foodai-text); font-weight: 700; }
[data-testid="stMetricDelta"] { color: var(--foodai-primary); }

/* ---- Responsive card grid --------------------------------------------- */
.foodai-card-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--foodai-space-4);
}
@media (min-width: 768px) {
    .foodai-card-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (min-width: 1024px) {
    .foodai-card-grid { grid-template-columns: repeat(3, 1fr); }
}

/* ---- Accessible focus states ------------------------------------------ */
[data-testid="stButton"] button:focus-visible,
[data-testid="stRadioGroup"] label:focus-visible {
    outline: 2px solid var(--foodai-primary);
    outline-offset: 2px;
}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inject_css() -> None:
    """Inject the FoodAI design system as one <style> block.

    Call once per page, after ``st.set_page_config``. Streamlit is imported
    lazily here so importing this module has no side effects.
    """
    import streamlit as st  # local import: keeps module import side-effect free

    st.markdown("<style>" + _CSS + "</style>", unsafe_allow_html=True)


def page_header(title: str, subtitle: str) -> str:
    """Return the branded page header (title + subtitle) as an HTML string."""
    return (
        '<div class="page-header">'
        + "<h1>" + _esc(title) + "</h1>"
        + "<p>" + _esc(subtitle) + "</p>"
        + "</div>"
    )


def restaurant_card(name: str, cuisine: str, rating: float, address: str) -> str:
    """Return a restaurant listing card as an HTML string."""
    return (
        '<div class="restaurant-card">'
        + '<h3 class="restaurant-card__name">' + _esc(name) + "</h3>"
        + '<div class="restaurant-meta">' + _esc(cuisine) + " · " + _esc(address) + "</div>"
        + '<div class="restaurant-badge">⭐ ' + "{:.1f}".format(rating) + "</div>"
        + "</div>"
    )


def menu_row(item_name: str, price: float, prep_min: int) -> str:
    """Return a menu item line (name + price + prep time) as an HTML string."""
    return (
        '<div class="menu-item-row">'
        + '<span class="menu-item-row__name">' + _esc(item_name) + "</span>"
        + '<span class="menu-item-row__meta">₹'
        + "{:.0f}".format(price)
        + " · Prep "
        + str(int(prep_min))
        + " min</span>"
        + "</div>"
    )


_STATUS_BADGE_CLASSES = {
    "PLACED": "badge-placed",
    "CONFIRMED": "badge-confirmed",
    "PREPARING": "badge-preparing",
    "OUT_FOR_DELIVERY": "badge-out",
    "DELIVERED": "badge-delivered",
}


def status_badge(status: str) -> str:
    """Return a colored status pill as an HTML string.

    Maps PLACED/CONFIRMED/PREPARING/OUT_FOR_DELIVERY/DELIVERED onto the
    .badge-* variant classes; unknown statuses fall back to gray "placed".
    """
    badge_class = _STATUS_BADGE_CLASSES.get(status.upper(), "badge-placed")
    label = _humanize_label(status)
    return (
        '<span class="status-badge ' + badge_class + '" title="' + _esc(status) + '">'
        + _esc(label)
        + "</span>"
    )


def status_stepper(status_flow: list[str], current_status: str) -> str:
    """Return a horizontal order-progress stepper as an HTML string.

    Completed steps show a filled orange dot (✓), the current step shows an
    orange ring, and pending steps stay gray.
    """
    flow = [status.upper() for status in status_flow]
    current = current_status.upper()
    current_index = flow.index(current) if current in flow else -1

    steps = []
    for index, status in enumerate(flow):
        if 0 <= current_index and index < current_index:
            state_class = "is-complete"
        elif index == current_index:
            state_class = "is-current"
        else:
            state_class = ""
        dot = "✓" if state_class == "is-complete" else str(index + 1)
        label = _esc(_humanize_label(status))
        steps.append(
            '<div class="stepper-step ' + state_class + '">'
            + '<span class="stepper-dot">' + dot + "</span>"
            + '<span class="stepper-label">' + label + "</span>"
            + "</div>"
        )
    return (
        '<div class="status-stepper" role="list" aria-label="Order progress">'
        + "".join(steps)
        + "</div>"
    )


def header_bar(logo_text: str, user_name: str, role: str, cart_count: int = 0) -> str:
    """Return the branded top bar (logo + user chip + optional cart) as HTML."""
    chip = (
        "👤 "
        + _esc(user_name)
        + " · "
        + _esc(_humanize_label(role))
    )
    if cart_count > 0:
        chip += (
            ' <span class="cart-count" aria-label="'
            + str(cart_count)
            + ' items in cart">'
            + str(cart_count)
            + "</span>"
        )
    return (
        '<div class="foodai-header">'
        + '<div class="foodai-logo">' + _esc(logo_text) + "</div>"
        + '<span class="user-chip">' + chip + "</span>"
        + "</div>"
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _esc(value: object) -> str:
    """HTML-escape a value for safe inline rendering."""
    return escape(str(value))


def _humanize_label(value: str) -> str:
    """Turn 'OUT_FOR_DELIVERY' into 'Out For Delivery'."""
    return value.replace("_", " ").strip().title()
