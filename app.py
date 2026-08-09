"""
FoodAI - Streamlit starter app (Person A, Weeks 0-4)
====================================================
Run with:  streamlit run app.py

What works today:
    - Login / register screen (demo users are pre-seeded)
    - Restaurant listing with cuisine filter
    - Restaurant menu page with add-to-cart (session state)
    - Cart page showing selected items
    - Delivery panel with live GPS tracking on a folium map

Next steps in your roadmap:
    - Checkout -> create order (database.create_order)
    - Restaurant panel -> accept orders (database.update_order_status)
    - Admin dashboard (Week 9)
"""

import hashlib
import time
from datetime import datetime, timezone
from typing import Optional

import eta_service
import explain_service
import folium
import forecast_service
import plotly.express as px
import pymysql
import streamlit as st
import tracking
from pymysql.err import IntegrityError
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium

st.set_page_config(
    page_title="FoodAI",
    page_icon="🍔",
    layout="wide",
    initial_sidebar_state="expanded",
)


from database import (
    Connection,
    get_connection,
    get_restaurants,
    get_menu,
    get_user_by_email,
    create_user,
    create_order,
    get_orders_for_customer,
    get_orders_for_restaurant,
    get_order_items,
    assign_delivery,
    get_assigned_delivery_for_order,
    get_available_delivery_drivers,
    get_deliveries_for_driver,
    get_latest_trip_position,
    mark_delivery_picked_up,
    log_trip_position,
    complete_delivery,
    update_order_status,
    get_revenue_totals,
    get_order_stats,
    get_orders_per_day,
    get_orders_per_restaurant,
    get_top_items,
    get_recent_orders,
    get_promo_codes,
    get_promo_by_code,
    apply_promo,
    increment_promo_usage,
)
from seed_data import seed_all
from ui import header_bar, inject_css, menu_row, page_header, restaurant_card, status_badge, status_stepper

# ---------- helpers ----------

def login(email: str, password: str) -> Optional[tuple]:
    """Return the user row (id, name, email, password_hash, role) or None if invalid."""
    conn = get_connection()
    user = get_user_by_email(conn, email)
    conn.close()
    if user and user[3] == hashlib.sha256(password.encode()).hexdigest():
        return user
    return None


def register_user(
    conn: Connection, name: str, email: str, password: str
) -> tuple[bool, str]:
    """Create a customer account. Returns (success, message).

    Validates non-empty fields, rejects duplicate emails, then inserts with a
    'customer' role. Password is hashed exactly as typed so the login flow
    (which hashes raw input) matches.
    """
    name = name.strip()
    email = email.strip()
    if not name or not email or not password.strip():
        return False, "Please fill in all fields."
    if get_user_by_email(conn, email) is not None:
        return False, "An account with this email already exists."
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    try:
        create_user(conn, name, email, password_hash, "customer")
    except IntegrityError:
        return False, "An account with this email already exists."
    return True, "Account created! Please log in."


def add_to_cart(menu_item_id: int, name: str, price: float) -> None:
    """Add one item to the in-memory cart (session state)."""
    cart = st.session_state["cart"]
    if menu_item_id in cart:
        cart[menu_item_id]["quantity"] += 1
    else:
        cart[menu_item_id] = {"name": name, "price": price, "quantity": 1}


def cart_total(cart: dict) -> float:
    """Return the total price of all cart items."""
    return sum(item["price"] * item["quantity"] for item in cart.values())


def _advance_order_status(
    conn: Connection, order_id: int, next_status: str
) -> bool:
    """Advance an order's status; returns whether the advance happened.

    Advancing to OUT_FOR_DELIVERY also assigns the first available delivery
    driver so a deliveries row exists. Returns False (order unchanged) when
    no delivery partners are available.
    """
    if next_status == "OUT_FOR_DELIVERY":
        drivers = get_available_delivery_drivers(conn)
        if not drivers:
            return False
        update_order_status(conn, order_id, "OUT_FOR_DELIVERY")
        assign_delivery(conn, order_id, drivers[0][0])
        return True
    update_order_status(conn, order_id, next_status)
    return True


def _assigned_driver_name(conn: Connection, order_id: int) -> Optional[str]:
    """Return the delivery driver's name for an order, or None if unassigned."""
    delivery = get_assigned_delivery_for_order(conn, order_id)
    if delivery is None:
        return None
    cur = conn.execute("SELECT name FROM users WHERE id = %s", (delivery[1],))
    row = cur.fetchone()
    return row[0] if row is not None else None


# ---------- pages ----------

def show_login_page() -> None:
    """Branded login: hero section, demo quick-login buttons, manual form."""
    st.markdown(
        page_header("FoodAI", "Fast, friendly food delivery with real-time tracking."),
        unsafe_allow_html=True,
    )

    hero_col, login_col = st.columns([3, 2], gap="large")

    with hero_col:
        st.markdown(
            '<div class="menu-card">'
            '<div class="restaurant-badge">🍔</div>'
            "<h3>Order food. Track the rider. Eat happy.</h3>"
            "<p>Fresh meals from Bengaluru's favorite restaurants with live GPS "
            "tracking and AI-predicted delivery times.</p>"
            "</div>",
            unsafe_allow_html=True,
        )

    with login_col:
        tab_login, tab_register = st.tabs(["Login", "Register"])

        with tab_login:
            st.markdown('<div class="order-card">', unsafe_allow_html=True)
            st.markdown("<h3>Welcome back</h3>", unsafe_allow_html=True)

            demo_accounts = [
                ("quick_customer", "Demo Customer", "customer@foodai.com"),
                ("quick_spice", "Spice Garden Owner", "spice@foodai.com"),
                ("quick_rider", "Rider Ram", "rider@foodai.com"),
            ]
            for key, label, email in demo_accounts:
                if st.button(f"👤 {label} — {email}", key=key):
                    user = login(email, "password123")
                    if user:
                        st.session_state["user"] = user
                        st.rerun()
                    else:
                        st.error(f"Could not sign in as {label}. Please try again.")

            st.divider()
            st.markdown("<h3>Sign in with email</h3>", unsafe_allow_html=True)
            # Defaults read the registration prefill (set after a successful sign-up).
            email = st.text_input(
                "Email",
                key="login_email",
                value=st.session_state.get("reg_email", "customer@foodai.com"),
            )
            password = st.text_input(
                "Password",
                type="password",
                key="login_password",
                value=st.session_state.get("reg_password", ""),
            )
            if st.button("Login"):
                user = login(email, password)
                if user:
                    st.session_state["user"] = user
                    st.rerun()
                else:
                    st.error(
                        "Invalid email or password. Try customer@foodai.com / password123"
                    )
            st.markdown('</div>', unsafe_allow_html=True)

        with tab_register:
            reg_name = st.text_input("Name", key="register_name")
            reg_email = st.text_input("Email", key="register_email")
            reg_password = st.text_input("Password", type="password", key="register_password")
            if st.button("Register"):
                conn = get_connection()
                ok, message = register_user(conn, reg_name, reg_email, reg_password)
                conn.close()
                if ok:
                    st.session_state["reg_email"] = reg_email
                    st.session_state["reg_password"] = reg_password
                    st.success(message)
                else:
                    st.error(message)


def show_restaurant_listing() -> None:
    """Customer page: browse restaurants by cuisine and add meals to the cart."""
    st.markdown(
        page_header(
            "Restaurants",
            "Browse nearby favorites and add meals to your cart.",
        ),
        unsafe_allow_html=True,
    )

    conn = get_connection()
    restaurants = get_restaurants(conn)
    conn.close()

    cuisines = sorted({r[2] for r in restaurants})
    chosen = st.selectbox("Filter by cuisine", ["All"] + cuisines)
    filtered = [r for r in restaurants if chosen == "All" or r[2] == chosen]

    # Responsive card grid (styled by .foodai-card-grid): 1 column on mobile,
    # 2 on tablet, 3 on desktop. Each restaurant lives in its own container so
    # it becomes one grid cell with the card + menu + add buttons inside.
    st.markdown('<div class="foodai-card-grid">', unsafe_allow_html=True)
    for rest_id, name, cuisine, rating, address in filtered:
        with st.container():
            st.markdown(
                restaurant_card(name, cuisine, rating, address),
                unsafe_allow_html=True,
            )

            conn = get_connection()
            menu = get_menu(conn, rest_id)
            conn.close()

            for item_id, item_name, price, prep in menu:
                st.markdown(
                    menu_row(item_name, price, prep),
                    unsafe_allow_html=True,
                )
                if st.button("Add to cart", key=f"add_{item_id}"):
                    add_to_cart(item_id, item_name, price)
                    st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


def show_cart_page(user) -> None:
    st.markdown(
        page_header(
            "Cart",
            "Your selected meals are ready to go. Confirm the address and place your order.",
        ),
        unsafe_allow_html=True,
    )

    cart = st.session_state["cart"]
    if not cart:
        st.info("Cart is empty. Add items from the Restaurant page.")
        return

    with st.container():
        st.markdown('<div class="order-card">', unsafe_allow_html=True)
        for item_id, item in cart.items():
            cols = st.columns([3, 1, 1])
            cols[0].write(f"**{item['name']} × {item['quantity']}**")
            cols[1].write(f"₹{item['price'] * item['quantity']:.0f}")
            if cols[2].button("Remove", key=f"rm_{item_id}"):
                del st.session_state["cart"][item_id]
                st.rerun()

        # Bill summary: per-item subtotals + order total in a styled block.
        # Local import keeps the change scoped to this page (see task constraints).
        from html import escape

        subtotal_rows = "".join(
            (
                '<div style="display:flex;justify-content:space-between;'
                'align-items:center;padding:0.35rem 0;color:var(--foodai-text);">'
                f'<span style="font-weight:600;">{escape(item["name"])} × {item["quantity"]}</span>'
                f'<span>₹{item["price"] * item["quantity"]:.0f}</span>'
                "</div>"
            )
            for item in cart.values()
        )
        st.markdown(
            (
                '<div style="background:var(--foodai-primary-softer);'
                'border:1px solid var(--foodai-border);'
                'border-radius:var(--foodai-radius-md);'
                'padding:1rem 1.25rem;margin-top:1.25rem;">'
                '<div style="font-weight:700;color:var(--foodai-text);margin-bottom:0.4rem;">'
                "Bill Summary</div>"
                + subtotal_rows
                + '<div style="display:flex;justify-content:space-between;align-items:center;'
                'border-top:1px solid var(--foodai-border);margin-top:0.4rem;padding-top:0.7rem;'
                'font-weight:800;color:var(--foodai-primary-dark);font-size:1.1rem;">'
                f'<span>Total</span><span>₹{cart_total(cart):.0f}</span></div>'
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        st.divider()

        subtotal = cart_total(cart)
        promo = st.session_state.get("promo")
        # Recompute the discount against the current subtotal so a stale session
        # value can never exceed the subtotal (e.g. the cart changed after the
        # promo was applied). calculate_discount enforces this in database.py;
        # we clamp defensively here too.
        discount = min(float(promo["discount"]), subtotal) if promo else 0.0

        st.write(f"**Subtotal: ₹{subtotal:.0f}**")

        if promo is None:
            with st.expander("Apply promo code"):
                promo_code = st.text_input("Promo code", key="promo_input")
                if st.button("Apply", key="apply_promo_btn"):
                    code = promo_code.strip()
                    conn = get_connection()
                    ok, message, new_discount = apply_promo(conn, code, subtotal)
                    if ok:
                        promo_row = get_promo_by_code(conn, code)
                        conn.close()
                        clamped = min(new_discount, subtotal)
                        st.session_state["promo"] = {
                            "code": code,
                            "discount": clamped,
                            "promo_id": promo_row["id"] if promo_row else None,
                        }
                        st.success(f"{message} You save ₹{clamped:.2f}!")
                        st.rerun()
                    else:
                        conn.close()
                        st.session_state.pop("promo", None)
                        st.error(message)
        else:
            st.write(f"**Promo discount ({promo['code']}): -₹{discount:.0f}**")
            st.write(f"**Final total: ₹{subtotal - discount:.0f}**")
            if st.button("Remove promo", key="remove_promo_btn"):
                st.session_state.pop("promo", None)
                st.rerun()

        st.subheader("Delivery address")
        address = st.text_input("Address", value="Hostel Block C, MG Road")

        if st.button("Place Order"):
            # Find this customer's restaurant (all items belong to one cart, so we
            # use the first item's restaurant). For a starter, we look it up by
            # finding the menu item's restaurant.
            restaurant_id = _find_cart_restaurant(cart)
            if restaurant_id is None:
                st.error("Could not identify restaurant for cart items.")
                return

            items = [
                (item_id, item["quantity"], item["price"])
                for item_id, item in cart.items()
            ]
            conn = get_connection()
            if promo is not None:
                # Clamp the stored discount against the current subtotal so it can
                # never exceed what the customer actually pays.
                order_discount = min(float(promo["discount"]), cart_total(cart))
                order_id = create_order(
                    conn,
                    user[0],
                    restaurant_id,
                    items,
                    coupon_code=promo["code"],
                    discount_amount=order_discount,
                )
                # Usage is counted only after the order is actually created.
                if promo.get("promo_id") is not None:
                    increment_promo_usage(conn, promo["promo_id"])
            else:
                order_id = create_order(conn, user[0], restaurant_id, items)
            conn.close()

            st.success(f"✅ Order #{order_id} placed! Status: PLACED")
            st.session_state["cart"] = {}
            st.session_state.pop("promo", None)
            st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)


def _find_cart_restaurant(cart: dict) -> Optional[int]:
    """Find the restaurant id for the first cart item (simple starter logic)."""
    conn = get_connection()
    first_item_id = next(iter(cart), None)
    if first_item_id is None:
        conn.close()
        return None
    cur = conn.execute(
        "SELECT restaurant_id FROM menu_items WHERE id = %s", (first_item_id,)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def show_order_history(user) -> None:
    """Customer page: list past orders with their items."""
    st.markdown(
        page_header(
            "Order History",
            "Review past deliveries and order details in a clean activity feed.",
        ),
        unsafe_allow_html=True,
    )

    conn = get_connection()
    orders = get_orders_for_customer(conn, user[0])
    conn.close()

    if not orders:
        st.info("No orders yet. Order something from the Restaurant page!")
        return

    for order_id, restaurant_name, status, total, created_at in orders:
        st.markdown('<div class="order-card">', unsafe_allow_html=True)
        st.write(f"### Order #{order_id} — {restaurant_name}")
        st.markdown(status_badge(status), unsafe_allow_html=True)
        st.write(f"**Placed:** {created_at}")
        conn = get_connection()
        items = get_order_items(conn, order_id)
        conn.close()
        for name, quantity, price in items:
            st.write(f"- {name} × {quantity} — ₹{price * quantity:.0f}")
        st.write(f"**Total: ₹{total:.0f}**")
        st.markdown('</div>', unsafe_allow_html=True)


def show_restaurant_panel(user) -> None:
    """Restaurant owner page: see incoming orders and update their status."""
    st.markdown(
        page_header(
            "Restaurant Panel",
            "Manage incoming orders, update status, and keep customers informed.",
        ),
        unsafe_allow_html=True,
    )

    conn = get_connection()
    orders = get_orders_for_restaurant(conn, user[0])
    conn.close()

    if not orders:
        st.info("No orders yet for your restaurant.")
        return

    status_flow = ["PLACED", "CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"]

    for order_id, customer_name, status, total, created_at in orders:
        st.markdown('<div class="order-card">', unsafe_allow_html=True)
        st.write(f"### Order #{order_id} — {customer_name}")
        st.write(f"**Status:** {status}")
        st.write(f"**Placed:** {created_at}")
        st.write(f"**Total:** ₹{total:.0f}")
        conn = get_connection()
        items = get_order_items(conn, order_id)
        conn.close()
        for name, quantity, price in items:
            st.write(f"- {name} × {quantity} — ₹{price * quantity:.0f}")

        st.markdown(status_stepper(status_flow, status), unsafe_allow_html=True)

        if status in ("OUT_FOR_DELIVERY", "DELIVERED"):
            conn = get_connection()
            driver_name = _assigned_driver_name(conn, order_id)
            conn.close()
            if driver_name is not None:
                st.write(f"👤 Driver: {driver_name}")

        current_index = status_flow.index(status)
        if current_index < len(status_flow) - 1:
            next_status = status_flow[current_index + 1]
            if st.button(f"Advance to {next_status}", key=f"adv_{order_id}"):
                conn = get_connection()
                advanced = _advance_order_status(conn, order_id, next_status)
                conn.close()
                if not advanced:
                    st.warning("No delivery partners available right now.")
                else:
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


def show_delivery_panel(user) -> None:
    """Delivery partner page: pick up, track, and complete assigned deliveries."""
    st.markdown(
        page_header(
            "Delivery Partner",
            "Track your current route, start pickups, and complete orders with clear ETA feedback.",
        ),
        unsafe_allow_html=True,
    )

    # Auto-refresh every 2.5s so the map + ETA move without user interaction.
    # Must be called at most once per page — it lives only on this panel.
    st_autorefresh(interval=2500, key="delivery_panel_autorefresh")

    conn = get_connection()
    deliveries = get_deliveries_for_driver(conn, user[0])
    conn.close()

    if not deliveries:
        st.info("No deliveries assigned yet.")
        return

    # Prefer an order already out for delivery; otherwise show the newest row.
    active = next((d for d in deliveries if d[4] == "OUT_FOR_DELIVERY"), None)
    delivery = active if active is not None else deliveries[0]
    (
        delivery_id,
        order_id,
        restaurant_name,
        customer_name,
        _order_status,
        pickup_time,
        delivered_time,
    ) = delivery

    # Resolve the restaurant id for route coordinates.
    conn = get_connection()
    cur = conn.execute("SELECT restaurant_id FROM orders WHERE id = %s", (order_id,))
    rest_row = cur.fetchone()
    conn.close()
    if rest_row is None:
        st.error(f"Order #{order_id} not found.")
        return

    restaurant_id = rest_row[0]
    start = tracking.restaurant_coordinates(restaurant_id)
    end = tracking.customer_home_coordinates()
    route = tracking.build_route(start, end)

    # Route card: restaurant -> customer, wrapping the live delivery flow.
    st.markdown('<div class="order-card">', unsafe_allow_html=True)
    st.write(f"**{restaurant_name}** → **{customer_name}**")

    # Not picked up yet: show the start button and stop.
    if pickup_time is None:
        st.write("Delivery ready for pickup at the restaurant.")
        if st.button("Start Delivery", key=f"start_delivery_{delivery_id}"):
            conn = get_connection()
            mark_delivery_picked_up(conn, delivery_id)
            log_trip_position(conn, delivery_id, *start)
            conn.close()
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        return

    # Picked up: progress is elapsed time over the full trip estimate.
    # SQLite datetime('now') is UTC in 'YYYY-MM-DD HH:MM:SS'; parse as UTC so
    # the epoch is directly comparable to time.time().
    pickup_ts = datetime.strptime(pickup_time, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    ).timestamp()
    elapsed_seconds = time.time() - pickup_ts
    total_seconds = tracking.estimate_trip_seconds(route, tracking.AVG_SPEED_KMH)
    progress = (
        min(1.0, max(0.0, elapsed_seconds / total_seconds))
        if total_seconds > 0
        else 1.0
    )
    rider_position = tracking.interpolate_position(route, progress)

    if progress >= 1.0:
        # Complete once (guarded by delivered_time) so the DB isn't rewritten
        # on every autorefresh tick; stop logging and show the final state.
        if delivered_time is None:
            conn = get_connection()
            complete_delivery(conn, delivery_id)
            update_order_status(conn, order_id, "DELIVERED")
            conn.close()
        st.success("Order delivered! 🎉")
        rider_position = end
    else:
        # Accumulate the simulated GPS trail on every tick.
        conn = get_connection()
        log_trip_position(conn, delivery_id, *rider_position)
        conn.close()

    eta_min, eta_source = eta_service.best_eta(route, progress, restaurant_id)
    st.metric("Estimated arrival", tracking.format_eta(eta_min))
    st.caption("AI-predicted ETA" if eta_source == "ml" else "Estimated ETA")

    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="menu-card">', unsafe_allow_html=True)
    m = folium.Map(location=start, zoom_start=13)
    folium.PolyLine(route, color="blue", weight=3).add_to(m)
    folium.Marker(
        start,
        popup=restaurant_name,
        tooltip="Restaurant",
        icon=folium.Icon(color="green"),
    ).add_to(m)
    folium.Marker(
        rider_position,
        popup="Rider",
        tooltip="Rider",
        icon=folium.Icon(color="red", icon="motorcycle"),
    ).add_to(m)
    folium.Marker(
        end,
        popup=customer_name,
        tooltip="Customer",
        icon=folium.Icon(color="purple"),
    ).add_to(m)

    lats = [point[0] for point in route]
    lngs = [point[1] for point in route]
    m.fit_bounds([[min(lats), min(lngs)], [max(lats), max(lngs)]], padding=(20, 20))
    # returned_objects=[] keeps the map read-only (no click-driven reruns).
    st_folium(
        m,
        key=f"delivery_map_{delivery_id}",
        use_container_width=True,
        height=450,
        returned_objects=[],
    )
    st.markdown('</div>', unsafe_allow_html=True)


def show_customer_tracking(user) -> None:
    """Customer page: live map + ETA for the most recent out-for-delivery order."""
    st.markdown(
        page_header(
            "Track Delivery",
            "See your order’s progress on the map and get an updated ETA without refreshing.",
        ),
        unsafe_allow_html=True,
    )

    conn = get_connection()
    orders = get_orders_for_customer(conn, user[0])
    order = next(
        (o for o in orders if o[2] == "OUT_FOR_DELIVERY"),
        next(
            (o for o in orders if o[2] in ("PLACED", "CONFIRMED", "PREPARING")),
            next((o for o in orders if o[2] == "DELIVERED"), None),
        ),
    )
    if order is None:
        conn.close()
        st.info(
            "No active delivery to track yet. Place an order and the restaurant "
            "will assign a delivery partner."
        )
        return
    order_id, restaurant_name, status, _total, _created_at = order

    delivery = get_assigned_delivery_for_order(conn, order_id)
    conn.close()
    delivery_id = delivery[0] if delivery is not None else None
    pickup_time = delivery[2] if delivery is not None else None
    delivered_time = delivery[3] if delivery is not None else None

    # Auto-refresh every 2.5s so the map + ETA move without user interaction.
    # Must be called at most once per page — it lives only on this page, with a
    # key distinct from the delivery panel's.
    st_autorefresh(interval=2500, key="customer_tracking_autorefresh")

    # Resolve the restaurant id for route coordinates.
    conn = get_connection()
    cur = conn.execute("SELECT restaurant_id FROM orders WHERE id = %s", (order_id,))
    rest_row = cur.fetchone()
    conn.close()
    if rest_row is None:
        st.error(f"Order #{order_id} not found.")
        return

    restaurant_id = rest_row[0]
    start = tracking.restaurant_coordinates(restaurant_id)
    end = tracking.customer_home_coordinates()
    route = tracking.build_route(start, end)

    # Rider position: use the latest logged GPS point, else the restaurant.
    conn = get_connection()
    latest = (
        get_latest_trip_position(conn, delivery_id)
        if delivery_id is not None
        else None
    )
    conn.close()
    rider_pos = (latest[0], latest[1]) if latest is not None else start

    st.write(f"**{restaurant_name}** — Status: **{status}**")

    # Order progress timeline: PLACED -> CONFIRMED -> PREPARING -> OUT_FOR_DELIVERY -> DELIVERED.
    status_flow = ["PLACED", "CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"]
    st.markdown(status_stepper(status_flow, status), unsafe_allow_html=True)

    m = folium.Map(location=tracking.BENGALURU_CENTER, zoom_start=13)
    folium.PolyLine(route, color="blue", weight=3).add_to(m)
    folium.Marker(
        start,
        popup=restaurant_name,
        tooltip="Restaurant",
        icon=folium.Icon(color="green"),
    ).add_to(m)
    folium.Marker(
        rider_pos,
        popup="Delivery partner",
        tooltip="Rider",
        icon=folium.Icon(color="red", icon="motorcycle"),
    ).add_to(m)
    folium.Marker(
        end,
        popup="You",
        tooltip="Your location",
        icon=folium.Icon(color="purple"),
    ).add_to(m)

    lats = [point[0] for point in route]
    lngs = [point[1] for point in route]
    m.fit_bounds([[min(lats), min(lngs)], [max(lats), max(lngs)]], padding=(20, 20))
    # returned_objects=[] keeps the map read-only (no click-driven reruns).
    st.markdown('<div class="menu-card">', unsafe_allow_html=True)
    st_folium(
        m,
        key=f"customer_tracking_map_{order_id}",
        use_container_width=True,
        height=450,
        returned_objects=[],
    )
    st.markdown('</div>', unsafe_allow_html=True)

    if status == "DELIVERED":
        st.success("Your order was delivered! 🎉")
        if delivered_time:
            st.write(f"Delivered at {delivered_time}")
        return

    # ETA: while the rider is en route, progress is elapsed time over the full
    # trip estimate. SQLite datetime('now') is UTC in 'YYYY-MM-DD HH:MM:SS';
    # parse as UTC so the epoch is directly comparable to time.time().
    # Before pickup (no pickup_time yet) we still show the AI prediction for
    # the full trip from the restaurant, so an ordered customer always sees an
    # expected delivery time.
    if pickup_time:
        pickup_ts = datetime.strptime(pickup_time, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        ).timestamp()
        elapsed_seconds = time.time() - pickup_ts
        total_seconds = tracking.estimate_trip_seconds(route, tracking.AVG_SPEED_KMH)
        progress = (
            min(1.0, max(0.0, elapsed_seconds / total_seconds))
            if total_seconds > 0
            else 1.0
        )
    else:
        progress = 0.0

    eta_min, eta_source = eta_service.best_eta(route, progress, restaurant_id)
    st.metric("Estimated arrival", tracking.format_eta(eta_min))
    st.caption("AI-predicted ETA" if eta_source == "ml" else "Estimated ETA")

    with st.expander("Why this ETA?"):
        explanation = explain_service.explain_eta(
            eta_service.features_for_order(
                restaurant_id,
                distance_km=tracking.route_length_km(route),
                prep_time_min=15,
            )
        )
        if explanation is None:
            st.caption("Model explanation unavailable.")
        else:
            top = explanation["contributions"][:8]
            import pandas as pd
            df = pd.DataFrame(top)
            df["color"] = df["shap"].apply(lambda v: "green" if v >= 0 else "red")
            fig = px.bar(
                df,
                x="shap",
                y="feature",
                orientation="h",
                color="color",
                color_discrete_map={"green": "#2E7D32", "red": "#C62828"},
                title="Feature contributions to the ETA",
                labels={"shap": "Minutes contribution", "feature": ""},
            )
            fig.update_layout(showlegend=False, height=320)
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"Base prediction: {explanation['base_value']:.1f} min")


# ---------- admin dashboard ----------

def _demand_bucket_color(demand: float) -> str:
    """Return the heatmap fill color for a predicted order count.

    Buckets: <2 green, 2-4 yellow, 4-6 orange, >6 red.
    """
    if demand < 2:
        return "green"
    if demand < 4:
        return "yellow"
    if demand < 6:
        return "orange"
    return "red"


def _today_orders_per_zone(conn: Connection) -> dict[str, list[int]]:
    """Return today's order counts per zone, bucketed by hour.

    orders table has no zone column; derive zone from restaurant coordinates.
    Each value is a dense hourly list for hours 0..current (oldest first), so
    the final element is the most recent hour count; hours without orders are
    filled with 0. No orders today -> {} (forecast_service handles the empty
    case with its moving-average defaults).
    """
    rows = conn.execute(
        """
        SELECT restaurant_id, created_at
        FROM orders
        WHERE DATE(created_at) = CURDATE()
        """
    ).fetchall()
    if not rows:
        return {}

    zone_hourly: dict[str, dict[int, int]] = {}
    for restaurant_id, created_at in rows:
        coords = tracking.COORDINATES.get(restaurant_id)
        if coords is None:
            continue
        zone = eta_service.nearest_zone(*coords)
        hour = int(created_at[11:13])  # "YYYY-MM-DD HH:MM:SS" (UTC) -> hour
        zone_hourly.setdefault(zone, {}).setdefault(hour, 0)
        zone_hourly[zone][hour] += 1

    current_hour = datetime.now().hour
    return {
        zone: [counts.get(hour, 0) for hour in range(current_hour + 1)]
        for zone, counts in zone_hourly.items()
    }


def show_admin_dashboard() -> None:
    """Admin page: KPIs, analytics charts, demand heatmap, recent orders."""
    st.title("📊 Admin Dashboard")
    st.caption("Live overview of revenue, order volume, and zone-level demand.")

    # --- KPI cards ---
    conn = get_connection()
    revenue_totals = get_revenue_totals(conn)
    conn.close()
    conn = get_connection()
    order_stats = get_order_stats(conn)
    conn.close()

    avg_order_value = (
        revenue_totals["total"] / order_stats["delivered"]
        if order_stats["delivered"] > 0
        else 0.0
    )
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Today Revenue", f"₹{revenue_totals['today']:.0f}")
    col2.metric("Total Orders", f"{order_stats['total_orders']}")
    col3.metric("Active Orders", f"{order_stats['active']}")
    col4.metric("Avg Order Value", f"₹{avg_order_value:.0f}")

    # --- Orders per day + revenue trend (same source: get_orders_per_day) ---
    conn = get_connection()
    orders_per_day = get_orders_per_day(conn)
    conn.close()
    if orders_per_day:
        fig_day = px.bar(orders_per_day, x="day", y="count", title="Orders per day")
        st.plotly_chart(fig_day, use_container_width=True)
        fig_rev = px.line(
            orders_per_day, x="day", y="revenue", title="Revenue trend (last 7 days)"
        )
        st.plotly_chart(fig_rev, use_container_width=True)
    else:
        st.info("No order data available yet to chart.")

    # --- Orders per restaurant ---
    conn = get_connection()
    orders_per_restaurant = get_orders_per_restaurant(conn)
    conn.close()
    if orders_per_restaurant:
        fig_rest = px.bar(
            orders_per_restaurant,
            x="restaurant_name",
            y="count",
            title="Orders per restaurant",
        )
        st.plotly_chart(fig_rest, use_container_width=True)
    else:
        st.info("No restaurant order data available yet.")

    # --- Top items ---
    conn = get_connection()
    top_items = get_top_items(conn)
    conn.close()
    if top_items:
        fig_items = px.bar(
            top_items,
            x="quantity",
            y="item_name",
            orientation="h",
            title="Top items by quantity",
        )
        st.plotly_chart(fig_items, use_container_width=True)
    else:
        st.info("No item sales data available yet.")

    # --- Demand heatmap (next-hour forecast per zone) ---
    st.subheader("Demand heatmap (next-hour forecast per zone)")
    conn = get_connection()
    prev_counts_by_zone = _today_orders_per_zone(conn)
    conn.close()
    now = datetime.now()
    predicted = forecast_service.forecast_all_zones(
        now.hour,
        now.weekday(),
        1 if now.weekday() in (5, 6) else 0,
        prev_counts_by_zone,
    )

    m = folium.Map(location=tracking.BENGALURU_CENTER, zoom_start=13)
    for zone, anchor in eta_service.ZONE_ANCHORS.items():
        demand = predicted.get(zone, 0.0)
        folium.CircleMarker(
            location=anchor,
            radius=14,
            popup=f"Zone {zone}: {demand:.1f} predicted orders",
            tooltip=f"Zone {zone}",
            fill=True,
            fill_color=_demand_bucket_color(demand),
            fill_opacity=0.75,
            color="black",
            weight=1,
        ).add_to(m)

    legend_html = """
    <div style="position: fixed; bottom: 30px; left: 30px; z-index: 9999;
                background: white; padding: 8px 12px; border-radius: 6px;
                border: 1px solid #ccc; font-family: sans-serif; font-size: 12px;">
      <b>Predicted demand</b><br>
      <span style="display:inline-block; width:10px; height:10px;
                   background: green; border-radius:50%;"></span> &lt;2 orders<br>
      <span style="display:inline-block; width:10px; height:10px;
                   background: yellow; border-radius:50%;"></span> 2-4 orders<br>
      <span style="display:inline-block; width:10px; height:10px;
                   background: orange; border-radius:50%;"></span> 4-6 orders<br>
      <span style="display:inline-block; width:10px; height:10px;
                   background: red; border-radius:50%;"></span> &gt;6 orders
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    # returned_objects=[] keeps the map read-only (no click-driven reruns).
    st_folium(
        m,
        key="admin_demand_map",
        use_container_width=True,
        height=450,
        returned_objects=[],
    )

    # --- Recent orders ---
    st.subheader("Recent orders")
    conn = get_connection()
    recent_orders = get_recent_orders(conn, 10)
    conn.close()
    if recent_orders:
        st.dataframe(recent_orders, use_container_width=True)
    else:
        st.info("No orders placed yet.")

    # --- Promo codes ---
    st.subheader("Promo codes")
    conn = get_connection()
    promos = get_promo_codes(conn)
    conn.close()
    if promos:
        promo_columns = (
            "code",
            "discount_type",
            "discount_value",
            "min_order_value",
            "max_discount",
            "times_used",
            "active",
        )
        st.dataframe(
            [{col: row[col] for col in promo_columns} for row in promos],
            use_container_width=True,
        )
    else:
        st.info("No promo codes yet.")


# ---------- main ----------

_NAV_OPTIONS = {
    "restaurant": ["Restaurant Panel", "Logout"],
    "delivery": ["Delivery Panel", "Logout"],
    "customer": ["Restaurants", "Cart", "Track Delivery", "My Orders", "Logout"],
    "admin": ["Admin Dashboard", "Logout"],
}


def _nav_options_for_role(role: str) -> list:
    """Return the navigation options for a user role (customer is the default)."""
    return _NAV_OPTIONS.get(role, _NAV_OPTIONS["customer"])


def _render_header_bar(user: tuple) -> None:
    """Render the branded top bar with the user chip and cart count."""
    st.markdown(
        header_bar(
            logo_text="🍔 FoodAI",
            user_name=user[1],
            role=user[4],
            cart_count=len(st.session_state.get("cart", {})),
        ),
        unsafe_allow_html=True,
    )


def main() -> None:
    # One-time setup: create tables + seed demo data on first run.
    if "initialized" not in st.session_state:
        from database import init_db
        init_db()
        seed_all()
        st.session_state["initialized"] = True

    # In-memory cart (lost on refresh - that's fine for the starter).
    if "cart" not in st.session_state:
        st.session_state["cart"] = {}

    # One-time CSS injection (design system from ui.theme).
    if "css_injected" not in st.session_state:
        inject_css()
        st.session_state["css_injected"] = True

    # Login gate.
    if "user" not in st.session_state:
        show_login_page()
        return

    user = st.session_state["user"]
    _render_header_bar(user)

    # Role-based navigation: horizontal pill radio in the main area.
    page = st.radio(
        "Navigate",
        _nav_options_for_role(user[4]),
        horizontal=True,
        label_visibility="collapsed",
        key="main_nav_" + user[4],
    )

    if user[4] == "restaurant":
        if page == "Restaurant Panel":
            show_restaurant_panel(user)
        else:
            st.session_state.pop("user", None)
            st.rerun()
    elif user[4] == "delivery":
        if page == "Delivery Panel":
            show_delivery_panel(user)
        else:
            st.session_state.pop("user", None)
            st.rerun()
    elif user[4] == "admin":
        if page == "Admin Dashboard":
            show_admin_dashboard()
        else:
            st.session_state.pop("user", None)
            st.rerun()
    else:
        if page == "Restaurants":
            show_restaurant_listing()
        elif page == "Cart":
            show_cart_page(user)
        elif page == "Track Delivery":
            show_customer_tracking(user)
        elif page == "My Orders":
            show_order_history(user)
        else:
            st.session_state.pop("user", None)
            st.rerun()


if __name__ == "__main__":
    main()
