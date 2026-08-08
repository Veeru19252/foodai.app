"""
FoodAI - Seed data
==================
Fills the database with demo data (5 restaurants, menu items, users, promo codes).

How to use (Person A):
    from database import init_db
    from seed_data import seed_all

    init_db()
    seed_all()
"""

import hashlib

from database import get_connection

RESTAURANTS = [
    # name, address, cuisine, [menu items as (name, price, prep_time_min)]
    ("Spice Garden", "MG Road", "North Indian", [
        ("Paneer Butter Masala", 220.0, 20),
        ("Butter Chicken", 280.0, 25),
        ("Dal Tadka", 160.0, 15),
        ("Garlic Naan", 40.0, 5),
        ("Veg Biryani", 200.0, 20),
    ]),
    ("Dosa Plaza", "Lake View Road", "South Indian", [
        ("Masala Dosa", 90.0, 10),
        ("Idli Sambar", 60.0, 8),
        ("Vada", 40.0, 5),
        ("Filter Coffee", 30.0, 3),
        ("Uttapam", 100.0, 12),
    ]),
    ("Wok This Way", "City Center", "Chinese", [
        ("Hakka Noodles", 180.0, 15),
        ("Manchurian", 200.0, 18),
        ("Fried Rice", 170.0, 15),
        ("Spring Rolls", 140.0, 12),
        ("Chilli Paneer", 220.0, 20),
    ]),
    ("Pizza Junction", "Main Street", "Italian", [
        ("Margherita Pizza", 250.0, 20),
        ("Farmhouse Pizza", 320.0, 25),
        ("Garlic Bread", 120.0, 10),
        ("Pasta Alfredo", 230.0, 20),
        ("Tiramisu", 150.0, 5),
    ]),
    ("Burger Barn", "Tech Park", "Fast Food", [
        ("Classic Burger", 150.0, 12),
        ("Crispy Chicken Burger", 180.0, 15),
        ("French Fries", 90.0, 8),
        ("Cold Coffee", 110.0, 5),
        ("Chocolate Shake", 130.0, 5),
    ]),
]

USERS = [
    # name, email, password, role
    ("Demo Customer", "customer@foodai.com", "password123", "customer"),
    ("Spice Garden Owner", "spice@foodai.com", "password123", "restaurant"),
    ("Dosa Plaza Owner", "dosa@foodai.com", "password123", "restaurant"),
    ("Wok This Way Owner", "wok@foodai.com", "password123", "restaurant"),
    ("Pizza Junction Owner", "pizza@foodai.com", "password123", "restaurant"),
    ("Burger Barn Owner", "burger@foodai.com", "password123", "restaurant"),
    ("Rider Ram", "rider@foodai.com", "password123", "delivery"),
    ("Rider Priya", "priya@foodai.com", "password123", "delivery"),
    ("Admin", "admin@foodai.com", "password123", "admin"),
]

PROMOS = [
    # code, description, discount_type, discount_value, min_order_value,
    # max_discount, valid_until, usage_limit, times_used, active
    ("WELCOME10", "10% off up to ₹50 on orders above ₹100", "percent", 10, 100, 50, None, 100, 0, 1),
    ("FLAT50", "Flat ₹50 off on orders above ₹200", "flat", 50, 200, None, None, 50, 0, 1),
    ("FOODIE20", "20% off up to ₹150 on orders above ₹300", "percent", 20, 300, 150, "2026-12-31", 30, 0, 1),
]


def _hash_password(password: str) -> str:
    """Return a hashed password (simple SHA-256 for the demo)."""
    return hashlib.sha256(password.encode()).hexdigest()


def seed_users(conn) -> None:
    """Insert demo users (skip if the email already exists)."""
    for name, email, password, role in USERS:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE email = ?", (email,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                (name, email, _hash_password(password), role),
            )
    conn.commit()


def seed_restaurants(conn) -> None:
    """Insert demo restaurants with their menus (skip if already seeded)."""
    for name, address, cuisine, menu in RESTAURANTS:
        exists = conn.execute(
            "SELECT 1 FROM restaurants WHERE name = ?", (name,)
        ).fetchone()
        if exists:
            continue
        # Find this restaurant's owner by matching the demo email (e.g. spice@foodai.com)
        owner_email = name.split()[0].lower() + "@foodai.com"
        owner = conn.execute(
            "SELECT id FROM users WHERE email = ?", (owner_email,)
        ).fetchone()
        owner_id = owner[0] if owner else conn.execute(
            "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO restaurants (user_id, name, address, cuisine, rating) VALUES (?, ?, ?, ?, ?)",
            (owner_id, name, address, cuisine, 4.0),
        )
        restaurant_id = cur.lastrowid
        for item_name, price, prep in menu:
            conn.execute(
                "INSERT INTO menu_items (restaurant_id, name, price, prep_time_min) VALUES (?, ?, ?, ?)",
                (restaurant_id, item_name, price, prep),
            )
    conn.commit()


def seed_promos(conn) -> None:
    """Insert demo promo codes (skip if the code already exists)."""
    for (code, description, discount_type, discount_value, min_order_value,
         max_discount, valid_until, usage_limit, times_used, active) in PROMOS:
        exists = conn.execute(
            "SELECT 1 FROM promo_codes WHERE code = ?", (code,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO promo_codes (code, description, discount_type, discount_value, "
                "min_order_value, max_discount, valid_until, usage_limit, times_used, active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (code, description, discount_type, discount_value, min_order_value,
                 max_discount, valid_until, usage_limit, times_used, active),
            )
    conn.commit()


def seed_all() -> None:
    """Seed users, then restaurants (owners must exist first), then promo codes."""
    conn = get_connection()
    seed_users(conn)
    seed_restaurants(conn)
    seed_promos(conn)
    conn.close()
    print("Seeding complete! Try logging in with customer@foodai.com / password123")


if __name__ == "__main__":
    seed_all()
