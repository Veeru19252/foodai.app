"""
FoodAI backend - seed data (parity port of seed_data.py)
=========================================================
Inserts the same demo users, restaurants + menus, and promo codes into
PostgreSQL so the API behaves identically to the legacy app.
"""

from hashlib import sha256

from sqlalchemy.orm import Session

from backend.models import MenuItem, PromoCode, Restaurant, User

# (name, city, address, cuisine, lat, lng, menu)
RESTAURANTS = [
    ("Spice Garden", "Bengaluru", "MG Road", "North Indian", 12.975, 77.606, [
        ("Paneer Butter Masala", 220.0, 20),
        ("Butter Chicken", 280.0, 25),
        ("Dal Tadka", 160.0, 15),
        ("Garlic Naan", 40.0, 5),
        ("Veg Biryani", 200.0, 20),
    ]),
    ("Dosa Plaza", "Bengaluru", "Lake View Road", "South Indian", 12.982, 77.619, [
        ("Masala Dosa", 90.0, 10),
        ("Idli Sambar", 60.0, 8),
        ("Vada", 40.0, 5),
        ("Filter Coffee", 30.0, 3),
        ("Uttapam", 100.0, 12),
    ]),
    ("Wok This Way", "Bengaluru", "City Center", "Chinese", 12.977, 77.596, [
        ("Hakka Noodles", 180.0, 15),
        ("Manchurian", 200.0, 18),
        ("Fried Rice", 170.0, 15),
        ("Spring Rolls", 140.0, 12),
        ("Chilli Paneer", 220.0, 20),
    ]),
    ("Pizza Junction", "Bengaluru", "Main Street", "Italian", 13.004, 77.610, [
        ("Margherita Pizza", 250.0, 20),
        ("Farmhouse Pizza", 320.0, 25),
        ("Garlic Bread", 120.0, 10),
        ("Pasta Alfredo", 230.0, 20),
        ("Tiramisu", 150.0, 5),
    ]),
    ("Burger Barn", "Bengaluru", "Tech Park", "Fast Food", 12.970, 77.750, [
        ("Classic Burger", 150.0, 12),
        ("Crispy Chicken Burger", 180.0, 15),
        ("French Fries", 90.0, 8),
        ("Cold Coffee", 110.0, 5),
        ("Chocolate Shake", 130.0, 5),
    ]),
    ("Delhi 6", "New Delhi", "Connaught Place", "North Indian", 28.6315, 77.2167, [
        ("Butter Chicken", 320.0, 25),
        ("Chole Bhature", 140.0, 15),
        ("Kadai Paneer", 240.0, 20),
        ("Tandoori Roti", 30.0, 5),
        ("Gulab Jamun", 80.0, 5),
    ]),
    ("Karim's", "New Delhi", "Jama Masjid", "Mughlai", 28.6505, 77.2332, [
        ("Mutton Korma", 380.0, 30),
        ("Chicken Jahangiri", 320.0, 25),
        ("Butter Naan", 50.0, 5),
        ("Seekh Kebab", 280.0, 20),
        ("Firni", 120.0, 5),
    ]),
    ("Bombay Canteen", "Mumbai", "Lower Parel", "Modern Indian", 19.0126, 72.8360, [
        ("Vada Pav", 60.0, 5),
        ("Prawn Balchao", 340.0, 25),
        ("Keema Pav", 260.0, 20),
        ("Kala Khatta", 90.0, 5),
        ("Mango Lassi", 110.0, 3),
    ]),
    ("Bademiya", "Mumbai", "Colaba", "Kebab", 18.9169, 72.8265, [
        ("Chicken Tikka Roll", 160.0, 12),
        ("Mutton Seekh Roll", 190.0, 15),
        ("Butter Chicken", 300.0, 20),
        ("Roomali Roti", 40.0, 5),
        ("Kulfi", 70.0, 3),
    ]),
    ("Paradise Biryani", "Hyderabad", "Paradise Circle", "Hyderabadi", 17.4435, 78.4977, [
        ("Chicken Dum Biryani", 260.0, 30),
        ("Mutton Biryani", 340.0, 35),
        ("Double Ka Meetha", 90.0, 5),
        ("Mirchi Ka Salan", 120.0, 10),
        ("Sweet Lassi", 80.0, 3),
    ]),
    ("Saravana Bhavan", "Chennai", "T. Nagar", "South Indian", 13.0418, 80.2341, [
        ("Ghee Roast Dosa", 110.0, 10),
        ("Rava Idli", 70.0, 8),
        ("Pongal", 90.0, 8),
        ("Filter Coffee", 40.0, 3),
        ("Curd Rice", 80.0, 5),
    ]),
    ("Peter Cat", "Kolkata", "Park Street", "Continental", 22.5528, 88.3522, [
        ("Chelo Kebab", 350.0, 25),
        ("Mutton Biryani", 320.0, 30),
        ("Chicken Cutlet", 180.0, 12),
        ("Roasted Papad", 60.0, 3),
        ("Mango Fool", 140.0, 5),
    ]),
    ("Vaishali", "Pune", "FC Road", "North Indian", 18.5314, 73.8446, [
        ("Cheese Corn Sandwich", 120.0, 8),
        ("Paneer Kathi Roll", 150.0, 12),
        ("Veg Kolhapuri", 200.0, 15),
        ("Butter Roti", 35.0, 5),
        ("Masala Chai", 40.0, 3),
    ]),
    ("Chokhi Dhani", "Jaipur", "Tonk Road", "Rajasthani", 26.8439, 75.8105, [
        ("Dal Baati Churma", 220.0, 20),
        ("Gatte Ki Sabzi", 180.0, 15),
        ("Ker Sangri", 190.0, 15),
        ("Bajra Roti", 40.0, 5),
        ("Ghewar", 110.0, 5),
    ]),
    ("Rajwadu", "Ahmedabad", "Sarkhej", "Gujarati", 22.9904, 72.5005, [
        ("Kathiyawadi Thali", 280.0, 20),
        ("Undhiyu", 200.0, 15),
        ("Thepla", 60.0, 5),
        ("Khichdi Kadhi", 150.0, 12),
        ("Shrikhand", 90.0, 3),
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
    for name, city, address, cuisine, lat, lng, menu in RESTAURANTS:
        restaurant = db.query(Restaurant).filter(Restaurant.name == name).first()
        if restaurant is None:
            owner_email = name.split()[0].lower() + "@foodai.com"
            owner = db.query(User).filter(User.email == owner_email).first()
            owner_id = owner.id if owner else db.query(User).filter(User.role == "admin").first().id
            restaurant = Restaurant(user_id=owner_id, name=name, address=address, cuisine=cuisine, rating=4.0)
            db.add(restaurant)
            db.flush()  # assign restaurant.id for the menu items
            for item_name, price, prep in menu:
                db.add(MenuItem(restaurant_id=restaurant.id, name=item_name, price=price, prep_time_min=prep))
        # Always sync location fields: backfills legacy rows created before the
        # pan-India rollout (city/lat/lng columns were nullable then).
        restaurant.city = city
        restaurant.lat = lat
        restaurant.lng = lng


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
    """Seed demo data when the users table is empty. Returns True if seeded.

    Restaurant seeding (and location backfill) always runs so databases that
    were created before the pan-India rollout pick up the new cities on boot.
    """
    seeded = False
    if db.query(User).first() is None:
        seed_users(db)
        db.flush()
        seed_promos(db)
        seeded = True
    seed_restaurants(db)
    db.commit()
    return seeded
