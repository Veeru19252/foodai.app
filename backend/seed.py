"""
FoodAI backend - seed data (parity port of seed_data.py)
=========================================================
Inserts the same demo users, restaurants + menus, and promo codes into
PostgreSQL so the API behaves identically to the legacy app.
"""

from hashlib import sha256

from sqlalchemy.orm import Session

from backend.models import MenuItem, PromoCode, Restaurant, User

RESTAURANTS = [
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
    ("WELCOME10", "10% off up to ₹50 on orders above ₹100", "percent", 10, 100, 50, "2026-12-31", 100, 0, True),
    ("FLAT50", "Flat ₹50 off on orders above ₹200", "flat", 50, 200, None, None, 50, 0, True),
    ("FOODIE20", "20% off up to ₹150 on orders above ₹300", "percent", 20, 300, 150, "2026-12-31", 30, 0, True),
]


def _hash_password(password: str) -> str:
    return sha256(password.encode()).hexdigest()


def seed_users(db: Session) -> None:
    for name, email, password, role in USERS:
        exists = db.query(User).filter(User.email == email).first()
        if exists is None:
            db.add(User(name=name, email=email, password_hash=_hash_password(password), role=role))


def seed_restaurants(db: Session) -> None:
    for name, address, cuisine, menu in RESTAURANTS:
        if db.query(Restaurant).filter(Restaurant.name == name).first():
            continue
        owner_email = name.split()[0].lower() + "@foodai.com"
        owner = db.query(User).filter(User.email == owner_email).first()
        owner_id = owner.id if owner else db.query(User).filter(User.role == "admin").first().id
        restaurant = Restaurant(user_id=owner_id, name=name, address=address, cuisine=cuisine, rating=4.0)
        db.add(restaurant)
        db.flush()  # assign restaurant.id for the menu items
        for item_name, price, prep in menu:
            db.add(MenuItem(restaurant_id=restaurant.id, name=item_name, price=price, prep_time_min=prep))


def seed_promos(db: Session) -> None:
    for (code, description, discount_type, discount_value, min_order_value,
         max_discount, valid_until, usage_limit, times_used, active) in PROMOS:
        if db.query(PromoCode).filter(PromoCode.code == code).first():
            continue
        db.add(PromoCode(
            code=code, description=description, discount_type=discount_type,
            discount_value=discount_value, min_order_value=min_order_value,
            max_discount=max_discount, valid_until=valid_until,
            usage_limit=usage_limit, times_used=times_used, active=active,
        ))


def seed_if_empty(db: Session) -> bool:
    """Seed demo data when the users table is empty. Returns True if seeded."""
    if db.query(User).first() is not None:
        return False
    seed_users(db)
    db.flush()
    seed_restaurants(db)
    seed_promos(db)
    db.commit()
    return True
