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
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
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


class IdempotencyRecord(Base):
    """Replay guard for unsafe, money-touching POSTs.

    Why this exists: the classic failure is a client that sends
    ``POST /orders``, the server commits the order, the response is lost to a
    network timeout, and the client retries. Without a guard that is two real
    orders, two delivery fees, and two cards charged.

    Semantics (the standard idempotency-key contract):

    * The key is scoped to ``(user_id, endpoint)`` -- two different users may
      legitimately pick the same key string, and one key reused across two
      endpoints is a client bug, not a replay.
    * ``request_hash`` pins the key to one payload. Reusing a key with a
      *different* body is rejected (409) rather than silently returning the
      first response, which would hide a genuine client bug.
    * The row is written in the **same transaction** as the orders it guards.
      A crash therefore rolls back both together, so a retry after a crash
      finds no row and is free to try again. There is no half-committed state.
    * Only order IDs are stored, not a serialized response body. On replay we
      re-read the live orders, so a retried request returns the order's
      *current* status (PLACED, or DELIVERED by now) rather than a stale
      snapshot frozen at creation time.
    """

    __tablename__ = "idempotency_records"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key = Column(String(255), nullable=False)
    endpoint = Column(String(64), nullable=False)
    request_hash = Column(String(64), nullable=False)
    # JSON array of created order IDs. Written in the same commit as the
    # orders; NULL would mean "claimed but the transaction rolled back",
    # which cannot persist because the claim shares that transaction.
    order_ids = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        # The database is the concurrency control. Two in-flight requests with
        # the same key both insert; the second blocks on this unique index
        # until the first commits (then it gets a clean conflict and replays)
        # or rolls back (then it proceeds and creates the order). This is why
        # the guard must not be a check-then-insert in Python.
        UniqueConstraint(
            "user_id", "endpoint", "key", name="uq_idempotency_user_endpoint_key"
        ),
        # Supports purge_expired(): the table grows by one row per order, so
        # without a sweep it becomes the largest table in the schema.
        Index("ix_idempotency_records_created_at", "created_at"),
    )


class RateLimitCounter(Base):
    """Fixed-window counter backing login/OTP throttling.

    One row per ``(bucket, window_start)``. The bucket names what is being
    limited (e.g. ``login:ip:1.2.3.4`` or ``login:email:foo@bar``) and the
    window is the start of the fixed interval. Incrementing is a single atomic
    upsert, so concurrent attempts cannot race past the limit -- the same
    database-as-concurrency-control idea as the idempotency guard.

    Kept in the database rather than an in-process dict so the limit survives
    a restart and is shared across uvicorn workers.
    """

    __tablename__ = "rate_limit_counters"

    id = Column(Integer, primary_key=True)
    bucket = Column(String(255), nullable=False)
    window_start = Column(DateTime, nullable=False)
    count = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "bucket", "window_start", name="uq_rate_limit_bucket_window"
        ),
        # Supports purge_old(): old windows are swept at startup.
        Index("ix_rate_limit_counters_window_start", "window_start"),
    )


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
