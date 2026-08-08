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
"""


def get_connection() -> sqlite3.Connection:
    """Open (and return) a connection to the FoodAI database."""
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Create all tables. Safe to call multiple times."""
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


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


def create_order(
    conn: sqlite3.Connection,
    customer_id: int,
    restaurant_id: int,
    items: list[tuple[int, int, float]],  # [(menu_item_id, quantity, price)]
) -> int:
    """Create an order with its items. Returns the new order id."""
    total = sum(quantity * price for _, quantity, price in items)
    cur = conn.execute(
        "INSERT INTO orders (customer_id, restaurant_id, total) VALUES (?, ?, ?)",
        (customer_id, restaurant_id, total),
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
