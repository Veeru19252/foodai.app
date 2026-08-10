"""
FoodAI backend - SQLAlchemy models
==================================
One-to-one mapping of the legacy MySQL schema (database.SCHEMA): users,
restaurants, menu_items, orders, order_items, deliveries, trip_logs,
promo_codes. Column names and semantics are preserved so the API behaves
identically to the Streamlit app it replaces.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from backend.db import Base

VALID_ROLES = ("customer", "restaurant", "delivery", "admin")
VALID_ORDER_STATUSES = (
    "PLACED",
    "CONFIRMED",
    "PREPARING",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "CANCELLED",
)
VALID_PAYMENT_METHODS = ("COD", "RAZORPAY")
VALID_PAYMENT_STATUSES = ("PENDING", "PAID", "FAILED", "REFUNDED")


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True)
    phone = Column(String(15), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False)
    purpose = Column(String(32), nullable=False, default="order_verify")
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False)
    # OTP verification: the customer's mobile, stamped the first time they
    # verify a code at checkout (so returning customers can be pre-filled).
    phone = Column(String(15), nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)

    restaurants = relationship("Restaurant", back_populates="owner")
    deliveries = relationship("Delivery", back_populates="driver")


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    address = Column(String(255), nullable=False)
    cuisine = Column(String(128), nullable=False)
    rating = Column(Float, default=0.0)
    # Pan-India rollout: city + lat/lng keep restaurants across the country
    # positioned on the map and labelled with their city (nullable for
    # backward-compatible legacy rows; seed/backfill populates them).
    city = Column(String(64), nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)

    owner = relationship("User", back_populates="restaurants")
    menu_items = relationship("MenuItem", back_populates="restaurant")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    name = Column(String(255), nullable=False)
    price = Column(Float, nullable=False)
    prep_time_min = Column(Integer, nullable=False)

    restaurant = relationship("Restaurant", back_populates="menu_items")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    delivery_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(32), nullable=False, default="PLACED")
    total = Column(Float, nullable=False, default=0.0)
    coupon_code = Column(String(255), nullable=True)
    discount_amount = Column(Float, nullable=False, default=0.0)
    payment_method = Column(String(16), nullable=False, default="COD")
    payment_status = Column(String(16), nullable=False, default="PENDING")
    payment_id = Column(String(64), nullable=True)
    delivery_lat = Column(Float, nullable=True)
    delivery_lng = Column(Float, nullable=True)
    delivery_address = Column(String(255), nullable=True)
    delivery_phone = Column(String(15), nullable=True)
    delivery_city = Column(String(64), nullable=True)
    delivery_state = Column(String(64), nullable=True)
    delivery_pincode = Column(String(10), nullable=True)
    # Pre-order verification gate: the customer verified their phone via OTP
    # and explicitly confirmed the delivery location before ordering.
    phone_verified = Column(Boolean, nullable=False, default=False)
    location_confirmed = Column(Boolean, nullable=False, default=False)
    location_confirm_lat = Column(Float, nullable=True)
    location_confirm_lng = Column(Float, nullable=True)
    # Scheduling + surge pricing (Layer 2).
    scheduled_for = Column(DateTime, nullable=True)
    delivery_fee = Column(Float, nullable=False, default=0.0)
    surge_multiplier = Column(Float, nullable=False, default=1.0)
    # Live GPS reported by the driver's device (Layer 2c). When present and
    # fresh, tracking shows the real position instead of the simulation.
    driver_lat = Column(Float, nullable=True)
    driver_lng = Column(Float, nullable=True)
    driver_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    customer = relationship("User", foreign_keys=[customer_id])
    restaurant = relationship("Restaurant")
    assigned_driver = relationship("User", foreign_keys=[delivery_id])
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem")


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    pickup_time = Column(DateTime, nullable=True)
    delivered_time = Column(DateTime, nullable=True)

    driver = relationship("User", back_populates="deliveries")
    trip_logs = relationship("TripLog", back_populates="delivery")


class TripLog(Base):
    __tablename__ = "trip_logs"

    id = Column(Integer, primary_key=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    delivery = relationship("Delivery", back_populates="trip_logs")


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True)
    code = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    discount_type = Column(String(16), nullable=False, default="percent")
    discount_value = Column(Float, nullable=False)
    min_order_value = Column(Float, nullable=False, default=0.0)
    max_discount = Column(Float, nullable=True)
    valid_until = Column(Date, nullable=True)
    usage_limit = Column(Integer, nullable=True)
    times_used = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    restaurant = relationship("Restaurant")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    photo_url = Column(String(255), nullable=True)
    owner_reply = Column(Text, nullable=True)
    replied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    order = relationship("Order")
    user = relationship("User")
    restaurant = relationship("Restaurant")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(32), nullable=False, default="info")
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=True)
    order_id = Column(Integer, nullable=True)
    read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User")


class SavedAddress(Base):
    __tablename__ = "saved_addresses"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    label = Column(String(64), nullable=False)
    address = Column(String(255), nullable=False)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User")
