"""
FoodAI - Database layer
=======================
Creates and queries the SQLite database.

How to use (Person A):
    from database import init_db, get_restaurants

    init_db()                       # create tables once
    conn = get_connection()
    restaurants = get_restaurants(conn)
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# One database file lives next to this file.
DB_PATH = Path(__file__).parent / "foodai.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('customer', 'restaurant', 'delivery', 'admin'))
);

CREATE TABLE IF NOT EXISTS restaurants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    cuisine TEXT NOT NULL,
    rating REAL DEFAULT 0.0,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS menu_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    prep_time_min INTEGER NOT NULL,
    FOREIGN KEY (restaurant_id) REFERENCES restaurants (id)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    restaurant_id INTEGER NOT NULL,
    delivery_id INTEGER,
    status TEXT NOT NULL DEFAULT 'PLACED',
    total REAL NOT NULL DEFAULT 0.0,
    coupon_code TEXT,
    discount_amount REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (customer_id) REFERENCES users (id),
    FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
    FOREIGN KEY (delivery_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    menu_item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders (id),
    FOREIGN KEY (menu_item_id) REFERENCES menu_items (id)
);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    driver_id INTEGER NOT NULL,
    pickup_time TEXT,
    delivered_time TEXT,
    FOREIGN KEY (order_id) REFERENCES orders (id),
    FOREIGN KEY (driver_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS trip_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id INTEGER NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (delivery_id) REFERENCES deliveries (id)
);

CREATE TABLE IF NOT EXISTS promo_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    description TEXT,
    discount_type TEXT NOT NULL DEFAULT 'percent' CHECK (discount_type IN ('percent', 'flat')),
    discount_value REAL NOT NULL,
    min_order_value REAL NOT NULL DEFAULT 0,
    max_discount REAL,
    valid_until TEXT,
    usage_limit INTEGER,
    times_used INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def get_connection() -> sqlite3.Connection:
    """Open (and return) a connection to the FoodAI database."""
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Create all tables. Safe to call multiple times.

    Also upgrades existing databases by adding columns that were introduced
    after the original schema (see _ensure_column), so an old foodai.db
    works with the new helpers. Rerun-safe.
    """
    conn = get_connection()
    conn.executescript(SCHEMA)
    _ensure_column(conn, "orders", "coupon_code", "coupon_code TEXT")
    _ensure_column(
        conn,
        "orders",
        "discount_amount",
        "discount_amount REAL NOT NULL DEFAULT 0",
    )
    conn.commit()
    conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Add a column to an existing table if it does not exist (SQLite has no IF NOT EXISTS for ALTER).

    `table` and `ddl` are internal constants from this module, never user input.
    """
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


# ---- Query helpers (pure functions: same input -> same output) ----

def get_restaurants(conn: sqlite3.Connection) -> list[tuple]:
    """Return all restaurants as rows: (id, name, cuisine, rating, address)."""
    cur = conn.execute(
        "SELECT id, name, cuisine, rating, address FROM restaurants ORDER BY rating DESC"
    )
    return cur.fetchall()


def get_menu(conn: sqlite3.Connection, restaurant_id: int) -> list[tuple]:
    """Return menu items for one restaurant: (id, name, price, prep_time_min)."""
    cur = conn.execute(
        "SELECT id, name, price, prep_time_min FROM menu_items WHERE restaurant_id = ?",
        (restaurant_id,),
    )
    return cur.fetchall()


def get_user_by_email(conn: sqlite3.Connection, email: str) -> tuple | None:
    """Return one user row (id, name, email, password_hash, role) or None."""
    cur = conn.execute(
        "SELECT id, name, email, password_hash, role FROM users WHERE email = ?",
        (email,),
    )
    return cur.fetchone()


def create_user(
    conn: sqlite3.Connection,
    name: str,
    email: str,
    password_hash: str,
    role: str,
) -> int:
    """Create a user row and return its new id."""
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (name, email, password_hash, role),
    )
    conn.commit()
    return cur.lastrowid


def create_order(
    conn: sqlite3.Connection,
    customer_id: int,
    restaurant_id: int,
    items: list[tuple[int, int, float]],  # [(menu_item_id, quantity, price)]
    coupon_code: str | None = None,
    discount_amount: float = 0.0,
) -> int:
    """Create an order with its items. Returns the new order id.

    The stored `total` is the FINAL PAID amount: item subtotal minus any
    promo discount (discount_amount), floored at 0. Backward-compatible —
    with no coupon, total is exactly the item subtotal and the new columns
    are stored as NULL / 0.0.
    """
    subtotal = sum(quantity * price for _, quantity, price in items)
    total = max(0.0, subtotal - discount_amount)
    cur = conn.execute(
        "INSERT INTO orders (customer_id, restaurant_id, total, coupon_code, discount_amount) "
        "VALUES (?, ?, ?, ?, ?)",
        (customer_id, restaurant_id, total, coupon_code, discount_amount),
    )
    order_id = cur.lastrowid
    for menu_item_id, quantity, price in items:
        conn.execute(
            "INSERT INTO order_items (order_id, menu_item_id, quantity, price) VALUES (?, ?, ?, ?)",
            (order_id, menu_item_id, quantity, price),
        )
    conn.commit()
    return order_id


def update_order_status(conn: sqlite3.Connection, order_id: int, status: str) -> None:
    """Update an order's status (e.g. PLACED -> CONFIRMED)."""
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()


def get_orders_for_customer(conn: sqlite3.Connection, customer_id: int) -> list[tuple]:
    """Return a customer's orders with restaurant name:
    (order_id, restaurant_name, status, total, created_at)."""
    cur = conn.execute(
        """
        SELECT o.id, r.name, o.status, o.total, o.created_at
        FROM orders o
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE o.customer_id = ?
        ORDER BY o.id DESC
        """,
        (customer_id,),
    )
    return cur.fetchall()


def get_orders_for_restaurant(conn: sqlite3.Connection, restaurant_user_id: int) -> list[tuple]:
    """Return orders for one restaurant owner:
    (order_id, customer_name, status, total, created_at)."""
    cur = conn.execute(
        """
        SELECT o.id, u.name, o.status, o.total, o.created_at
        FROM orders o
        JOIN restaurants r ON r.id = o.restaurant_id
        JOIN users u ON u.id = o.customer_id
        WHERE r.user_id = ?
        ORDER BY o.id DESC
        """,
        (restaurant_user_id,),
    )
    return cur.fetchall()


def get_order_items(conn: sqlite3.Connection, order_id: int) -> list[tuple]:
    """Return item lines for one order: (item_name, quantity, price)."""
    cur = conn.execute(
        """
        SELECT mi.name, oi.quantity, oi.price
        FROM order_items oi
        JOIN menu_items mi ON mi.id = oi.menu_item_id
        WHERE oi.order_id = ?
        """,
        (order_id,),
    )
    return cur.fetchall()


# ---- Delivery workflow helpers ----

def assign_delivery(conn: sqlite3.Connection, order_id: int, driver_id: int) -> int:
    """Assign a driver to an order; returns the delivery id.

    If the order already has a delivery row, returns its existing id
    instead of creating a duplicate assignment.
    """
    cur = conn.execute(
        "SELECT id FROM deliveries WHERE order_id = ?",
        (order_id,),
    )
    existing = cur.fetchone()
    if existing is not None:
        return existing[0]
    cur = conn.execute(
        "INSERT INTO deliveries (order_id, driver_id) VALUES (?, ?)",
        (order_id, driver_id),
    )
    conn.commit()
    return cur.lastrowid


def get_assigned_delivery_for_order(conn: sqlite3.Connection, order_id: int) -> tuple | None:
    """Return the delivery row for an order:
    (id, driver_id, pickup_time, delivered_time) or None."""
    cur = conn.execute(
        """
        SELECT id, driver_id, pickup_time, delivered_time
        FROM deliveries
        WHERE order_id = ?
        """,
        (order_id,),
    )
    return cur.fetchone()


def log_trip_position(
    conn: sqlite3.Connection, delivery_id: int, lat: float, lng: float
) -> None:
    """Log one GPS position for a delivery."""
    conn.execute(
        "INSERT INTO trip_logs (delivery_id, lat, lng) VALUES (?, ?, ?)",
        (delivery_id, lat, lng),
    )
    conn.commit()


def get_latest_trip_position(conn: sqlite3.Connection, delivery_id: int) -> tuple | None:
    """Return the most recent trip position for a delivery:
    (lat, lng, timestamp) or None."""
    cur = conn.execute(
        """
        SELECT lat, lng, timestamp
        FROM trip_logs
        WHERE delivery_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (delivery_id,),
    )
    return cur.fetchone()


def get_available_delivery_drivers(conn: sqlite3.Connection) -> list[tuple]:
    """Return all delivery drivers: (id, name, email)."""
    cur = conn.execute(
        "SELECT id, name, email FROM users WHERE role = 'delivery' ORDER BY name"
    )
    return cur.fetchall()


def get_deliveries_for_driver(conn: sqlite3.Connection, driver_id: int) -> list[tuple]:
    """Return a driver's deliveries with order and party details:
    (delivery_id, order_id, restaurant_name, customer_name, order_status,
    pickup_time, delivered_time), newest first."""
    cur = conn.execute(
        """
        SELECT d.id, d.order_id, r.name, u.name, o.status, d.pickup_time, d.delivered_time
        FROM deliveries d
        JOIN orders o ON o.id = d.order_id
        JOIN restaurants r ON r.id = o.restaurant_id
        JOIN users u ON u.id = o.customer_id
        WHERE d.driver_id = ?
        ORDER BY d.id DESC
        """,
        (driver_id,),
    )
    return cur.fetchall()


def mark_delivery_picked_up(conn: sqlite3.Connection, delivery_id: int) -> None:
    """Record the pickup time for a delivery."""
    conn.execute(
        "UPDATE deliveries SET pickup_time = datetime('now') WHERE id = ?",
        (delivery_id,),
    )
    conn.commit()


def complete_delivery(conn: sqlite3.Connection, delivery_id: int) -> None:
    """Record the delivered time for a delivery."""
    conn.execute(
        "UPDATE deliveries SET delivered_time = datetime('now') WHERE id = ?",
        (delivery_id,),
    )
    conn.commit()


def find_active_delivery_for_order(conn: sqlite3.Connection, order_id: int) -> tuple | None:
    """Return the active (not yet delivered) delivery row for an order:
    (id, order_id, driver_id, pickup_time, delivered_time) or None."""
    cur = conn.execute(
        """
        SELECT id, order_id, driver_id, pickup_time, delivered_time
        FROM deliveries
        WHERE order_id = ? AND delivered_time IS NULL
        """,
        (order_id,),
    )
    return cur.fetchone()


# ---- Admin analytics helpers ----

def get_revenue_totals(conn: sqlite3.Connection) -> dict:
    """Return revenue from DELIVERED orders:
    {"today": float, "total": float}; today = UTC calendar day.
    Empty DB -> {"today": 0.0, "total": 0.0}."""
    cur = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(CASE WHEN date(created_at) = date('now') THEN total END),
                0.0
            ) AS today_revenue,
            COALESCE(SUM(total), 0.0) AS total_revenue
        FROM orders
        WHERE status = 'DELIVERED'
        """
    )
    row = cur.fetchone()
    return {"today": row[0], "total": row[1]}


def get_order_stats(conn: sqlite3.Connection) -> dict:
    """Return order counts by lifecycle bucket:
    {"total_orders": int, "delivered": int, "active": int, "cancelled": int}.
    Empty DB -> all 0."""
    cur = conn.execute(
        """
        SELECT
            COUNT(*) AS total_orders,
            COALESCE(SUM(CASE WHEN status = 'DELIVERED' THEN 1 END), 0) AS delivered,
            COALESCE(
                SUM(CASE WHEN status IN ('PLACED', 'CONFIRMED', 'PREPARING', 'OUT_FOR_DELIVERY') THEN 1 END),
                0
            ) AS active,
            COALESCE(SUM(CASE WHEN status = 'CANCELLED' THEN 1 END), 0) AS cancelled
        FROM orders
        """
    )
    row = cur.fetchone()
    return {
        "total_orders": row[0],
        "delivered": row[1],
        "active": row[2],
        "cancelled": row[3],
    }


def get_orders_per_day(conn: sqlite3.Connection, limit_days: int = 7) -> list[dict]:
    """Return order volume for the last limit_days (UTC):
    [{"day": str, "count": int, "revenue": float}] oldest first;
    count = orders placed that day, revenue = DELIVERED total that day.
    Empty DB -> []."""
    cur = conn.execute(
        """
        SELECT
            date(created_at) AS day,
            COUNT(*) AS count,
            COALESCE(
                SUM(CASE WHEN status = 'DELIVERED' THEN total END),
                0.0
            ) AS revenue
        FROM orders
        WHERE created_at >= datetime('now', '-' || ? || ' days')
        GROUP BY date(created_at)
        ORDER BY day ASC
        """,
        (limit_days,),
    )
    return [
        {"day": row[0], "count": row[1], "revenue": row[2]}
        for row in cur.fetchall()
    ]


def get_orders_per_restaurant(conn: sqlite3.Connection) -> list[dict]:
    """Return order volume per restaurant (restaurants with no orders are omitted):
    [{"restaurant_name": str, "count": int, "revenue": float}]
    ordered by revenue DESC, count DESC, name ASC. Empty DB -> []."""
    cur = conn.execute(
        """
        SELECT
            r.name AS restaurant_name,
            COUNT(o.id) AS count,
            COALESCE(
                SUM(CASE WHEN o.status = 'DELIVERED' THEN o.total END),
                0.0
            ) AS revenue
        FROM restaurants r
        JOIN orders o ON o.restaurant_id = r.id
        GROUP BY r.id, r.name
        ORDER BY revenue DESC, count DESC, restaurant_name ASC
        """
    )
    return [
        {"restaurant_name": row[0], "count": row[1], "revenue": row[2]}
        for row in cur.fetchall()
    ]


def get_top_items(conn: sqlite3.Connection, limit: int = 5) -> list[dict]:
    """Return the most-ordered menu items across all restaurants:
    [{"item_name": str, "restaurant_name": str, "quantity": int}]
    ordered by quantity DESC, item_name ASC. Empty DB -> []."""
    cur = conn.execute(
        """
        SELECT
            mi.name AS item_name,
            r.name AS restaurant_name,
            SUM(oi.quantity) AS quantity
        FROM order_items oi
        JOIN menu_items mi ON mi.id = oi.menu_item_id
        JOIN restaurants r ON r.id = mi.restaurant_id
        GROUP BY mi.id, mi.name, r.name
        ORDER BY quantity DESC, item_name ASC
        LIMIT ?
        """,
        (limit,),
    )
    return [
        {"item_name": row[0], "restaurant_name": row[1], "quantity": row[2]}
        for row in cur.fetchall()
    ]


def get_recent_orders(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Return the most recent orders with customer and restaurant names:
    [{"order_id": int, "customer": str, "restaurant": str, "total": float,
    "status": str, "placed_at": str}] newest first. Empty DB -> []."""
    cur = conn.execute(
        """
        SELECT
            o.id AS order_id,
            u.name AS customer,
            r.name AS restaurant,
            o.total AS total,
            o.status AS status,
            o.created_at AS placed_at
        FROM orders o
        JOIN users u ON u.id = o.customer_id
        JOIN restaurants r ON r.id = o.restaurant_id
        ORDER BY o.created_at DESC, o.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [
        {
            "order_id": row[0],
            "customer": row[1],
            "restaurant": row[2],
            "total": row[3],
            "status": row[4],
            "placed_at": row[5],
        }
        for row in cur.fetchall()
    ]


# ---- Promo code helpers ----

def get_promo_codes(conn: sqlite3.Connection) -> list[dict]:
    """Return all promo codes, oldest first:
    [{"id": int, "code": str, "discount_type": str, ...}] keyed by column name."""
    cur = conn.execute("SELECT * FROM promo_codes ORDER BY id")
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_promo_by_code(conn: sqlite3.Connection, code: str) -> dict | None:
    """Return one promo code (case-insensitive match) keyed by column name, or None."""
    cur = conn.execute(
        "SELECT * FROM promo_codes WHERE code = ? COLLATE NOCASE",
        (code,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cur.description]
    return dict(zip(columns, row))


def validate_promo_code(
    conn: sqlite3.Connection, code: str, order_total: float
) -> tuple[bool, str, dict | None]:
    """Validate a promo code for an order total.

    Checks in order: exists, active, not expired, meets minimum order,
    under usage limit. Returns (True, "Promo code applied!", promo) on
    success; otherwise (False, reason, None). Does not mutate usage counts.
    """
    promo = get_promo_by_code(conn, code)
    if promo is None:
        return False, "Invalid promo code.", None
    if promo["active"] != 1:
        return False, "This promo code is no longer active.", None
    if promo["valid_until"] is not None:
        today_utc = datetime.now(timezone.utc).date().isoformat()
        if promo["valid_until"][:10] < today_utc:
            return False, "This promo code has expired.", None
    if order_total < promo["min_order_value"]:
        return (
            False,
            f"This promo requires a minimum order of ₹{promo['min_order_value']:.0f}.",
            None,
        )
    if promo["usage_limit"] is not None and promo["times_used"] >= promo["usage_limit"]:
        return False, "This promo code has reached its usage limit.", None
    return True, "Promo code applied!", promo


def calculate_discount(promo: dict, order_total: float) -> float:
    """Return the discount amount for a promo applied to an order total.

    percent → min(order_total * discount_value/100, max_discount or order_total);
    flat → min(discount_value, order_total). Rounded to 2 decimals; never
    negative and never exceeds order_total.
    """
    if promo["discount_type"] == "flat":
        discount = min(promo["discount_value"], order_total)
    else:  # percent
        raw = order_total * promo["discount_value"] / 100
        cap = promo["max_discount"] if promo["max_discount"] is not None else order_total
        discount = min(raw, cap)
    return round(max(0.0, min(discount, order_total)), 2)


def apply_promo(
    conn: sqlite3.Connection, code: str, order_total: float
) -> tuple[bool, str, float]:
    """Validate a promo code and return (ok, message, discount_amount).

    Does NOT increment times_used — that happens only on order placement.
    """
    ok, message, promo = validate_promo_code(conn, code, order_total)
    if not ok:
        return False, message, 0.0
    return True, message, calculate_discount(promo, order_total)


def increment_promo_usage(conn: sqlite3.Connection, promo_id: int) -> None:
    """Increment a promo code's times_used counter (called on order placement)."""
    conn.execute(
        "UPDATE promo_codes SET times_used = times_used + 1 WHERE id = ?",
        (promo_id,),
    )
    conn.commit()
