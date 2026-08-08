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
import sqlite3
import time
from datetime import datetime, timezone

import folium
import streamlit as st
import tracking
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium

from database import (
    get_connection,
    get_restaurants,
    get_menu,
    get_user_by_email,
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
)
from seed_data import seed_all

# ---------- helpers ----------

def login(email: str, password: str) -> tuple | None:
    """Return the user row (id, name, email, password_hash, role) or None if invalid."""
    conn = get_connection()
    user = get_user_by_email(conn, email)
    conn.close()
    if user and user[3] == hashlib.sha256(password.encode()).hexdigest():
        return user
    return None


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
    conn: sqlite3.Connection, order_id: int, next_status: str
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


def _assigned_driver_name(conn: sqlite3.Connection, order_id: int) -> str | None:
    """Return the delivery driver's name for an order, or None if unassigned."""
    delivery = get_assigned_delivery_for_order(conn, order_id)
    if delivery is None:
        return None
    cur = conn.execute("SELECT name FROM users WHERE id = ?", (delivery[1],))
    row = cur.fetchone()
    return row[0] if row is not None else None


# ---------- pages ----------

def show_login_page() -> None:
    st.title("🍔 FoodAI")
    st.subheader("Login to continue")

    email = st.text_input("Email", value="customer@foodai.com")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        user = login(email, password)
        if user:
            st.session_state["user"] = user
            st.rerun()
        else:
            st.error("Invalid email or password. Try customer@foodai.com / password123")


def show_restaurant_listing() -> None:
    st.title("🍔 Restaurants near you")

    conn = get_connection()
    restaurants = get_restaurants(conn)
    conn.close()

    cuisines = sorted({r[2] for r in restaurants})
    chosen = st.selectbox("Filter by cuisine", ["All"] + cuisines)
    filtered = [r for r in restaurants if chosen == "All" or r[2] == chosen]

    for rest_id, name, cuisine, rating, address in filtered:
        with st.expander(f"{name} ⭐ {rating} — {cuisine}"):
            st.write(f"📍 {address}")

            conn = get_connection()
            menu = get_menu(conn, rest_id)
            conn.close()

            cols = st.columns([3, 1, 1, 1])
            for item_id, item_name, price, prep in menu:
                cols[0].write(f"**{item_name}** — ₹{price:.0f} (prep {prep} min)")
                if cols[3].button("➕", key=f"add_{item_id}"):
                    add_to_cart(item_id, item_name, price)
                    st.rerun()


def show_cart_page(user) -> None:
    st.title("🛒 Your Cart")

    cart = st.session_state["cart"]
    if not cart:
        st.info("Cart is empty. Add items from the Restaurant page.")
        return

    for item_id, item in cart.items():
        cols = st.columns([3, 1, 1])
        cols[0].write(f"{item['name']} × {item['quantity']}")
        cols[1].write(f"₹{item['price'] * item['quantity']:.0f}")
        if cols[2].button("Remove", key=f"rm_{item_id}"):
            del st.session_state["cart"][item_id]
            st.rerun()

    st.divider()
    st.write(f"**Total: ₹{cart_total(cart):.0f}**")

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
        order_id = create_order(conn, user[0], restaurant_id, items)
        conn.close()

        st.success(f"✅ Order #{order_id} placed! Status: PLACED")
        st.session_state["cart"] = {}
        st.rerun()


def _find_cart_restaurant(cart: dict) -> int | None:
    """Find the restaurant id for the first cart item (simple starter logic)."""
    conn = get_connection()
    first_item_id = next(iter(cart), None)
    if first_item_id is None:
        conn.close()
        return None
    cur = conn.execute(
        "SELECT restaurant_id FROM menu_items WHERE id = ?", (first_item_id,)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def show_order_history(user) -> None:
    """Customer page: list past orders with their items."""
    st.title("🧾 My Orders")

    conn = get_connection()
    orders = get_orders_for_customer(conn, user[0])
    conn.close()

    if not orders:
        st.info("No orders yet. Order something from the Restaurant page!")
        return

    for order_id, restaurant_name, status, total, created_at in orders:
        with st.expander(f"Order #{order_id} — {restaurant_name} ({created_at})"):
            st.write(f"**Status:** {status}")
            conn = get_connection()
            items = get_order_items(conn, order_id)
            conn.close()
            for name, quantity, price in items:
                st.write(f"- {name} × {quantity} — ₹{price * quantity:.0f}")
            st.write(f"**Total: ₹{total:.0f}**")


def show_restaurant_panel(user) -> None:
    """Restaurant owner page: see incoming orders and update their status."""
    st.title("🏪 Restaurant Panel")

    conn = get_connection()
    orders = get_orders_for_restaurant(conn, user[0])
    conn.close()

    if not orders:
        st.info("No orders yet for your restaurant.")
        return

    status_flow = ["PLACED", "CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"]

    for order_id, customer_name, status, total, created_at in orders:
        with st.expander(f"Order #{order_id} — {customer_name} (₹{total:.0f})"):
            st.write(f"**Status:** {status}")
            conn = get_connection()
            items = get_order_items(conn, order_id)
            conn.close()
            for name, quantity, price in items:
                st.write(f"- {name} × {quantity} — ₹{price * quantity:.0f}")

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


def show_delivery_panel(user) -> None:
    """Delivery partner page: pick up, track, and complete assigned deliveries."""
    st.title("🛵 Delivery Panel")

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
    cur = conn.execute("SELECT restaurant_id FROM orders WHERE id = ?", (order_id,))
    rest_row = cur.fetchone()
    conn.close()
    if rest_row is None:
        st.error(f"Order #{order_id} not found.")
        return

    start = tracking.restaurant_coordinates(rest_row[0])
    end = tracking.customer_home_coordinates()
    route = tracking.build_route(start, end)

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

    eta_min = tracking.compute_eta(route, progress, tracking.AVG_SPEED_KMH)
    st.metric("Estimated arrival", tracking.format_eta(eta_min))

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


def show_customer_tracking(user) -> None:
    """Customer page: live map + ETA for the most recent out-for-delivery order."""
    st.title("🛵 Track Delivery")

    conn = get_connection()
    orders = get_orders_for_customer(conn, user[0])
    order = next(
        (o for o in orders if o[2] == "OUT_FOR_DELIVERY"),
        next((o for o in orders if o[2] == "DELIVERED"), None),
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
    if delivery is None or delivery[0] is None:
        st.info("Your order is being processed — a delivery partner will be assigned soon.")
        return

    # Auto-refresh every 2.5s so the map + ETA move without user interaction.
    # Must be called at most once per page — it lives only on this page, with a
    # key distinct from the delivery panel's.
    st_autorefresh(interval=2500, key="customer_tracking_autorefresh")

    delivery_id, _driver_id, pickup_time, delivered_time = delivery

    # Resolve the restaurant id for route coordinates.
    conn = get_connection()
    cur = conn.execute("SELECT restaurant_id FROM orders WHERE id = ?", (order_id,))
    rest_row = cur.fetchone()
    conn.close()
    if rest_row is None:
        st.error(f"Order #{order_id} not found.")
        return

    start = tracking.restaurant_coordinates(rest_row[0])
    end = tracking.customer_home_coordinates()
    route = tracking.build_route(start, end)

    # Rider position: use the latest logged GPS point, else the restaurant.
    conn = get_connection()
    latest = get_latest_trip_position(conn, delivery_id)
    conn.close()
    rider_pos = (latest[0], latest[1]) if latest is not None else start

    st.write(f"**{restaurant_name}** — Status: **{status}**")

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
    st_folium(
        m,
        key=f"customer_tracking_map_{order_id}",
        use_container_width=True,
        height=450,
        returned_objects=[],
    )

    if status == "DELIVERED":
        st.success("Your order was delivered! 🎉")
        if delivered_time:
            st.write(f"Delivered at {delivered_time}")
        return

    # Live trip: progress is elapsed time over the full trip estimate. SQLite
    # datetime('now') is UTC in 'YYYY-MM-DD HH:MM:SS'; parse as UTC so the
    # epoch is directly comparable to time.time().
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
        eta_min = tracking.compute_eta(route, progress, tracking.AVG_SPEED_KMH)
        st.metric("Estimated arrival", tracking.format_eta(eta_min))


# ---------- main ----------

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

    # Login gate.
    if "user" not in st.session_state:
        show_login_page()
        return

    user = st.session_state["user"]
    st.sidebar.write(f"👤 {user[1]} ({user[4]})")

    # Role-based navigation.
    if user[4] == "restaurant":
        page = st.sidebar.radio("Navigate", ["Restaurant Panel", "Logout"])
        if page == "Restaurant Panel":
            show_restaurant_panel(user)
        else:
            st.session_state.pop("user", None)
            st.rerun()
    elif user[4] == "delivery":
        page = st.sidebar.radio("Navigate", ["Delivery Panel", "Logout"])
        if page == "Delivery Panel":
            show_delivery_panel(user)
        else:
            st.session_state.pop("user", None)
            st.rerun()
    else:
        page = st.sidebar.radio("Navigate", ["Restaurants", "Cart", "Track Delivery", "My Orders", "Logout"])

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
