"""
FoodAI - Streamlit starter app (Person A, Weeks 0-4)
====================================================
Run with:  streamlit run app.py

What works today:
    - Login / register screen (demo users are pre-seeded)
    - Restaurant listing with cuisine filter
    - Restaurant menu page with add-to-cart (session state)
    - Cart page showing selected items

Next steps in your roadmap:
    - Checkout -> create order (database.create_order)
    - Restaurant panel -> accept orders (database.update_order_status)
    - Live tracking (Week 6)
"""

import hashlib

import streamlit as st

from database import (
    get_connection,
    get_restaurants,
    get_menu,
    get_user_by_email,
    create_order,
    get_orders_for_customer,
    get_orders_for_restaurant,
    get_order_items,
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

            current_index = status_flow.index(status)
            if current_index < len(status_flow) - 1:
                next_status = status_flow[current_index + 1]
                if st.button(f"Advance to {next_status}", key=f"adv_{order_id}"):
                    conn = get_connection()
                    update_order_status(conn, order_id, next_status)
                    conn.close()
                    st.rerun()


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
    else:
        page = st.sidebar.radio("Navigate", ["Restaurants", "Cart", "My Orders", "Logout"])

        if page == "Restaurants":
            show_restaurant_listing()
        elif page == "Cart":
            show_cart_page(user)
        elif page == "My Orders":
            show_order_history(user)
        else:
            st.session_state.pop("user", None)
            st.rerun()


if __name__ == "__main__":
    main()
