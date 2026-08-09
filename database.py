"""
FoodAI - Database layer
=======================
Creates and queries the MySQL database (local server, see config.py).

How to use (Person A):
    from database import init_db, get_restaurants

    init_db()                       # create tables once
    conn = get_connection()
    restaurants = get_restaurants(conn)

The app previously used SQLite. To keep every call site unchanged, a thin
`Connection` adapter mimics the sqlite3 API (Connection.execute /
executescript, cursor .lastrowid / .description) on top of pymysql.
"""

from datetime import datetime, timezone
from typing import Optional

import pymysql
import pymysql.constants.FIELD_TYPE
import pymysql.converters
import pymysql.cursors

import config

# Return DATETIME/DATE/TIMESTAMP values as "YYYY-MM-DD HH:MM:SS" strings, the
# same format SQLite's datetime('now') produced. Callers rely on slicing
# (e.g. created_at[11:13]) and string display.
# pymysql ascii-decodes these columns to str BEFORE the converter runs, so the
# converters must handle both str and datetime/date objects.
def _as_datetime_str(value) -> str:
    if isinstance(value, str):
        return value[:19]
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)[:19]


def _as_date_str(value) -> str:
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


_MYSQL_CONVERTERS = pymysql.converters.conversions.copy()
_MYSQL_CONVERTERS[pymysql.constants.FIELD_TYPE.DATETIME] = _as_datetime_str
_MYSQL_CONVERTERS[pymysql.constants.FIELD_TYPE.TIMESTAMP] = _as_datetime_str
_MYSQL_CONVERTERS[pymysql.constants.FIELD_TYPE.DATE] = _as_date_str

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL CHECK (role IN ('customer', 'restaurant', 'delivery', 'admin'))
);

CREATE TABLE IF NOT EXISTS restaurants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    address VARCHAR(255) NOT NULL,
    cuisine VARCHAR(128) NOT NULL,
    rating DOUBLE DEFAULT 0.0,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS menu_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    restaurant_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    price DOUBLE NOT NULL,
    prep_time_min INT NOT NULL,
    FOREIGN KEY (restaurant_id) REFERENCES restaurants (id)
);

CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    restaurant_id INT NOT NULL,
    delivery_id INT,
    status VARCHAR(32) NOT NULL DEFAULT 'PLACED',
    total DOUBLE NOT NULL DEFAULT 0.0,
    coupon_code VARCHAR(255),
    discount_amount DOUBLE NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES users (id),
    FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
    FOREIGN KEY (delivery_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    menu_item_id INT NOT NULL,
    quantity INT NOT NULL,
    price DOUBLE NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders (id),
    FOREIGN KEY (menu_item_id) REFERENCES menu_items (id)
);

CREATE TABLE IF NOT EXISTS deliveries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    driver_id INT NOT NULL,
    pickup_time DATETIME,
    delivered_time DATETIME,
    FOREIGN KEY (order_id) REFERENCES orders (id),
    FOREIGN KEY (driver_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS trip_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    delivery_id INT NOT NULL,
    lat DOUBLE NOT NULL,
    lng DOUBLE NOT NULL,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (delivery_id) REFERENCES deliveries (id)
);

CREATE TABLE IF NOT EXISTS promo_codes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    discount_type VARCHAR(16) NOT NULL DEFAULT 'percent' CHECK (discount_type IN ('percent', 'flat')),
    discount_value DOUBLE NOT NULL,
    min_order_value DOUBLE NOT NULL DEFAULT 0,
    max_discount DOUBLE,
    valid_until VARCHAR(255),
    usage_limit INT,
    times_used INT NOT NULL DEFAULT 0,
    active INT NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


class Connection:
    """Thin adapter over a pymysql connection exposing the sqlite3 API used by the app.

    Adds Connection.execute() / executescript() and keeps the most recent
    cursor so callers can read .lastrowid and .description. All other methods
    delegate to the underlying pymysql connection.
    """

    def __init__(self, raw: "pymysql.connections.Connection"):
        self._raw = raw
        self._last_cursor = None

    def execute(self, sql: str, params: Optional[tuple] = None):
        cur = self._raw.cursor()
        cur.execute(sql, params)
        self._last_cursor = cur
        return cur

    def executescript(self, script: str) -> None:
        """Run a semicolon-separated script (internal constants only, no params)."""
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self.execute(statement)

    @property
    def lastrowid(self) -> int:
        return self._last_cursor.lastrowid

    @property
    def description(self):
        return self._last_cursor.description if self._last_cursor is not None else None

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    def cursor(self):
        return self._raw.cursor()


def _ensure_database_exists(raw: "pymysql.connections.Connection") -> None:
    """Create the FoodAI database if missing, then select it on this connection.

    The database name comes from config.py (internal constant), never user input.
    """
    cur = raw.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{config.MYSQL_DATABASE}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cur.close()
    raw.select_db(config.MYSQL_DATABASE)


def get_connection() -> Connection:
    """Open (and return) a connection to the FoodAI MySQL database."""
    kwargs = config.mysql_config()
    kwargs.pop("database", None)  # connect first, then select the DB in _ensure_database_exists
    raw = pymysql.connect(
        **kwargs,
        database=None,
        autocommit=False,
        cursorclass=pymysql.cursors.Cursor,
        conv=_MYSQL_CONVERTERS,
    )
    _ensure_database_exists(raw)
    return Connection(raw)


def init_db() -> None:
    """Create all tables. Safe to call multiple times.

    Also upgrades existing databases by adding columns that were introduced
    after the original schema (see _ensure_column), so an old schema works
    with the new helpers. Rerun-safe.
    """
    conn = get_connection()
    conn.executescript(SCHEMA)
    _ensure_column(conn, "orders", "coupon_code", "coupon_code VARCHAR(255) NULL")
    _ensure_column(
        conn,
        "orders",
        "discount_amount",
        "discount_amount DOUBLE NOT NULL DEFAULT 0",
    )
    conn.commit()
    conn.close()


def _ensure_column(conn: Connection, table: str, column: str, ddl: str) -> None:
    """Add a column to an existing table if it does not exist (MySQL 8 lacks IF NOT EXISTS for ADD COLUMN).

    `table` and `ddl` are internal constants from this module, never user input.
    """
    columns = {row[0] for row in conn.execute(f"SHOW COLUMNS FROM {table}")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


# ---- Query helpers (pure functions: same input -> same output) ----

def get_restaurants(conn: Connection) -> list[tuple]:
    """Return all restaurants as rows: (id, name, cuisine, rating, address)."""
    cur = conn.execute(
        "SELECT id, name, cuisine, rating, address FROM restaurants ORDER BY rating DESC"
    )
    return cur.fetchall()


def get_menu(conn: Connection, restaurant_id: int) -> list[tuple]:
    """Return menu items for one restaurant: (id, name, price, prep_time_min)."""
    cur = conn.execute(
        "SELECT id, name, price, prep_time_min FROM menu_items WHERE restaurant_id = %s",
        (restaurant_id,),
    )
    return cur.fetchall()


def get_user_by_email(conn: Connection, email: str) -> Optional[tuple]:
    """Return one user row (id, name, email, password_hash, role) or None."""
    cur = conn.execute(
        "SELECT id, name, email, password_hash, role FROM users WHERE email = %s",
        (email,),
    )
    return cur.fetchone()


def create_user(
    conn: Connection,
    name: str,
    email: str,
    password_hash: str,
    role: str,
) -> int:
    """Create a user row and return its new id."""
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        (name, email, password_hash, role),
    )
    conn.commit()
    return cur.lastrowid


def create_order(
    conn: Connection,
    customer_id: int,
    restaurant_id: int,
    items: list[tuple[int, int, float]],  # [(menu_item_id, quantity, price)]
    coupon_code: Optional[str] = None,
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
        "VALUES (%s, %s, %s, %s, %s)",
        (customer_id, restaurant_id, total, coupon_code, discount_amount),
    )
    order_id = cur.lastrowid
    for menu_item_id, quantity, price in items:
        conn.execute(
            "INSERT INTO order_items (order_id, menu_item_id, quantity, price) VALUES (%s, %s, %s, %s)",
            (order_id, menu_item_id, quantity, price),
        )
    conn.commit()
    return order_id


def update_order_status(conn: Connection, order_id: int, status: str) -> None:
    """Update an order's status (e.g. PLACED -> CONFIRMED)."""
    conn.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
    conn.commit()


def get_orders_for_customer(conn: Connection, customer_id: int) -> list[tuple]:
    """Return a customer's orders with restaurant name:
    (order_id, restaurant_name, status, total, created_at)."""
    cur = conn.execute(
        """
        SELECT o.id, r.name, o.status, o.total, o.created_at
        FROM orders o
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE o.customer_id = %s
        ORDER BY o.id DESC
        """,
        (customer_id,),
    )
    return cur.fetchall()


def get_orders_for_restaurant(conn: Connection, restaurant_user_id: int) -> list[tuple]:
    """Return orders for one restaurant owner:
    (order_id, customer_name, status, total, created_at)."""
    cur = conn.execute(
        """
        SELECT o.id, u.name, o.status, o.total, o.created_at
        FROM orders o
        JOIN restaurants r ON r.id = o.restaurant_id
        JOIN users u ON u.id = o.customer_id
        WHERE r.user_id = %s
        ORDER BY o.id DESC
        """,
        (restaurant_user_id,),
    )
    return cur.fetchall()


def get_order_items(conn: Connection, order_id: int) -> list[tuple]:
    """Return item lines for one order: (item_name, quantity, price)."""
    cur = conn.execute(
        """
        SELECT mi.name, oi.quantity, oi.price
        FROM order_items oi
        JOIN menu_items mi ON mi.id = oi.menu_item_id
        WHERE oi.order_id = %s
        """,
        (order_id,),
    )
    return cur.fetchall()


# ---- Delivery workflow helpers ----

def assign_delivery(conn: Connection, order_id: int, driver_id: int) -> int:
    """Assign a driver to an order; returns the delivery id.

    If the order already has a delivery row, returns its existing id
    instead of creating a duplicate assignment.
    """
    cur = conn.execute(
        "SELECT id FROM deliveries WHERE order_id = %s",
        (order_id,),
    )
    existing = cur.fetchone()
    if existing is not None:
        return existing[0]
    cur = conn.execute(
        "INSERT INTO deliveries (order_id, driver_id) VALUES (%s, %s)",
        (order_id, driver_id),
    )
    conn.commit()
    return cur.lastrowid


def get_assigned_delivery_for_order(conn: Connection, order_id: int) -> Optional[tuple]:
    """Return the delivery row for an order:
    (id, driver_id, pickup_time, delivered_time) or None."""
    cur = conn.execute(
        """
        SELECT id, driver_id, pickup_time, delivered_time
        FROM deliveries
        WHERE order_id = %s
        """,
        (order_id,),
    )
    return cur.fetchone()


def log_trip_position(
    conn: Connection, delivery_id: int, lat: float, lng: float
) -> None:
    """Log one GPS position for a delivery."""
    conn.execute(
        "INSERT INTO trip_logs (delivery_id, lat, lng) VALUES (%s, %s, %s)",
        (delivery_id, lat, lng),
    )
    conn.commit()


def get_latest_trip_position(conn: Connection, delivery_id: int) -> Optional[tuple]:
    """Return the most recent trip position for a delivery:
    (lat, lng, timestamp) or None."""
    cur = conn.execute(
        """
        SELECT lat, lng, timestamp
        FROM trip_logs
        WHERE delivery_id = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (delivery_id,),
    )
    return cur.fetchone()


def get_available_delivery_drivers(conn: Connection) -> list[tuple]:
    """Return all delivery drivers: (id, name, email)."""
    cur = conn.execute(
        "SELECT id, name, email FROM users WHERE role = 'delivery' ORDER BY name"
    )
    return cur.fetchall()


def get_deliveries_for_driver(conn: Connection, driver_id: int) -> list[tuple]:
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
        WHERE d.driver_id = %s
        ORDER BY d.id DESC
        """,
        (driver_id,),
    )
    return cur.fetchall()


def mark_delivery_picked_up(conn: Connection, delivery_id: int) -> None:
    """Record the pickup time for a delivery."""
    conn.execute(
        "UPDATE deliveries SET pickup_time = NOW() WHERE id = %s",
        (delivery_id,),
    )
    conn.commit()


def complete_delivery(conn: Connection, delivery_id: int) -> None:
    """Record the delivered time for a delivery."""
    conn.execute(
        "UPDATE deliveries SET delivered_time = NOW() WHERE id = %s",
        (delivery_id,),
    )
    conn.commit()


def find_active_delivery_for_order(conn: Connection, order_id: int) -> Optional[tuple]:
    """Return the active (not yet delivered) delivery row for an order:
    (id, order_id, driver_id, pickup_time, delivered_time) or None."""
    cur = conn.execute(
        """
        SELECT id, order_id, driver_id, pickup_time, delivered_time
        FROM deliveries
        WHERE order_id = %s AND delivered_time IS NULL
        """,
        (order_id,),
    )
    return cur.fetchone()


# ---- Admin analytics helpers ----

def get_revenue_totals(conn: Connection) -> dict:
    """Return revenue from DELIVERED orders:
    {"today": float, "total": float}; today = UTC calendar day.
    Empty DB -> {"today": 0.0, "total": 0.0}."""
    cur = conn.execute(
        """
        SELECT
            COALESCE(
                SUM(CASE WHEN DATE(created_at) = CURDATE() THEN total END),
                0.0
            ) AS today_revenue,
            COALESCE(SUM(total), 0.0) AS total_revenue
        FROM orders
        WHERE status = 'DELIVERED'
        """
    )
    row = cur.fetchone()
    return {"today": float(row[0]), "total": float(row[1])}


def get_order_stats(conn: Connection) -> dict:
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
        "total_orders": int(row[0]),
        "delivered": int(row[1]),
        "active": int(row[2]),
        "cancelled": int(row[3]),
    }


def get_orders_per_day(conn: Connection, limit_days: int = 7) -> list[dict]:
    """Return order volume for the last limit_days (UTC):
    [{"day": str, "count": int, "revenue": float}] oldest first;
    count = orders placed that day, revenue = DELIVERED total that day.
    Empty DB -> []."""
    cur = conn.execute(
        """
        SELECT
            DATE(created_at) AS day,
            COUNT(*) AS count,
            COALESCE(
                SUM(CASE WHEN status = 'DELIVERED' THEN total END),
                0.0
            ) AS revenue
        FROM orders
        WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
        GROUP BY DATE(created_at)
        ORDER BY day ASC
        """,
        (limit_days,),
    )
    return [
        {"day": row[0], "count": int(row[1]), "revenue": float(row[2])}
        for row in cur.fetchall()
    ]


def get_orders_per_restaurant(conn: Connection) -> list[dict]:
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
        {"restaurant_name": row[0], "count": int(row[1]), "revenue": float(row[2])}
        for row in cur.fetchall()
    ]


def get_top_items(conn: Connection, limit: int = 5) -> list[dict]:
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
        LIMIT %s
        """,
        (limit,),
    )
    return [
        {"item_name": row[0], "restaurant_name": row[1], "quantity": int(row[2])}
        for row in cur.fetchall()
    ]


def get_recent_orders(conn: Connection, limit: int = 10) -> list[dict]:
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
        LIMIT %s
        """,
        (limit,),
    )
    return [
        {
            "order_id": int(row[0]),
            "customer": row[1],
            "restaurant": row[2],
            "total": float(row[3]),
            "status": row[4],
            "placed_at": row[5],
        }
        for row in cur.fetchall()
    ]


# ---- Promo code helpers ----

def get_promo_codes(conn: Connection) -> list[dict]:
    """Return all promo codes, oldest first:
    [{"id": int, "code": str, "discount_type": str, ...}] keyed by column name."""
    cur = conn.execute("SELECT * FROM promo_codes ORDER BY id")
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_promo_by_code(conn: Connection, code: str) -> Optional[dict]:
    """Return one promo code (case-insensitive match) keyed by column name, or None.

    MySQL's default utf8mb4 collation is case-insensitive, so no COLLATE
    clause is needed (replaces SQLite's COLLATE NOCASE).
    """
    cur = conn.execute(
        "SELECT * FROM promo_codes WHERE code = %s",
        (code,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cur.description]
    return dict(zip(columns, row))


def validate_promo_code(
    conn: Connection, code: str, order_total: float
) -> tuple[bool, str, Optional[dict]]:
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
    conn: Connection, code: str, order_total: float
) -> tuple[bool, str, float]:
    """Validate a promo code and return (ok, message, discount_amount).

    Does NOT increment times_used — that happens only on order placement.
    """
    ok, message, promo = validate_promo_code(conn, code, order_total)
    if not ok:
        return False, message, 0.0
    return True, message, calculate_discount(promo, order_total)


def increment_promo_usage(conn: Connection, promo_id: int) -> None:
    """Increment a promo code's times_used counter (called on order placement)."""
    conn.execute(
        "UPDATE promo_codes SET times_used = times_used + 1 WHERE id = %s",
        (promo_id,),
    )
    conn.commit()
