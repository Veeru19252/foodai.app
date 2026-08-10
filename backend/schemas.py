"""
FoodAI backend - Pydantic schemas (request/response contracts)
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---- auth ----

class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str
    password: str = Field(min_length=6)
    role: str = "customer"


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


# ---- restaurants ----

class MenuItemOut(BaseModel):
    id: int
    name: str
    price: float
    prep_time_min: int


class RestaurantOut(BaseModel):
    id: int
    name: str
    address: str
    cuisine: str
    rating: float
    city: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    menu: List[MenuItemOut] = []


class RestaurantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    address: str = Field(min_length=1, max_length=255)
    cuisine: str = Field(min_length=1, max_length=128)
    rating: float = Field(ge=0, le=5, default=0.0)
    user_id: Optional[int] = None


class MenuItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    price: float = Field(ge=0)
    prep_time_min: int = Field(ge=0, default=15)


class MenuItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    price: Optional[float] = Field(default=None, ge=0)
    prep_time_min: Optional[int] = Field(default=None, ge=0)


class OfferCreate(BaseModel):
    code: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    discount_type: str = Field(default="percent", pattern="^(percent|flat)$")
    discount_value: float = Field(ge=0)
    min_order_value: float = Field(ge=0, default=0.0)
    max_discount: Optional[float] = Field(default=None, ge=0)
    valid_until: Optional[date] = None
    usage_limit: Optional[int] = Field(default=None, ge=1)


# ---- orders ----

class OrderItemIn(BaseModel):
    menu_item_id: int
    quantity: int = Field(ge=1)


class CreateOrderRequest(BaseModel):
    restaurant_id: int
    items: List[OrderItemIn] = Field(min_length=1)
    coupon_code: Optional[str] = None
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None
    delivery_address: Optional[str] = None
    # Payment + structured-address fields (Layer 2).
    payment_method: str = Field(default="COD", max_length=16)
    delivery_phone: Optional[str] = Field(default=None, max_length=15)
    delivery_city: Optional[str] = Field(default=None, max_length=64)
    delivery_state: Optional[str] = Field(default=None, max_length=64)
    delivery_pincode: Optional[str] = Field(default=None, max_length=10)
    scheduled_for: Optional[datetime] = None


class OrderItemOut(BaseModel):
    name: str
    quantity: int
    price: float


class OrderOut(BaseModel):
    id: int
    restaurant_id: int
    restaurant_name: str
    customer_name: str
    status: str
    total: float
    coupon_code: Optional[str]
    discount_amount: float
    delivery_address: Optional[str]
    # Layer 2 additions so every order response carries payment state.
    payment_method: str
    payment_status: str
    delivery_phone: Optional[str] = None
    delivery_city: Optional[str] = None
    delivery_state: Optional[str] = None
    delivery_pincode: Optional[str] = None
    # Layer 2b: scheduling + surge pricing.
    scheduled_for: Optional[datetime] = None
    delivery_fee: float = 0.0
    surge_multiplier: float = 1.0
    created_at: datetime
    items: List[OrderItemOut] = []


class UpdateOrderStatusRequest(BaseModel):
    status: str


class BatchOrderRequest(BaseModel):
    orders: List[CreateOrderRequest] = Field(min_length=1)


class BatchOrderResponse(BaseModel):
    orders: List[OrderOut]


class AssignDeliveryRequest(BaseModel):
    driver_id: int


class PromoApplyRequest(BaseModel):
    code: str
    order_total: float


class PromoApplyResponse(BaseModel):
    ok: bool
    message: str
    discount: float


# ---- tracking ----

class TrackingState(BaseModel):
    order_id: int
    status: str
    restaurant_name: str
    customer_name: str
    delivery_address: Optional[str]
    route: List[List[float]] = []
    route_distance_km: float
    rider_lat: float
    rider_lng: float
    progress: float
    eta_min: Optional[float]
    eta_source: str


# ---- ml / admin ----

class EtaRequest(BaseModel):
    restaurant_id: int
    distance_km: float = Field(ge=0)
    prep_time_min: float = Field(ge=0, default=15)
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None


class EtaResponse(BaseModel):
    eta_min: Optional[float]
    source: str
    explanation: Optional[dict] = None


class ForecastRequest(BaseModel):
    hour: Optional[int] = None
    day_of_week: Optional[int] = None
    prev_counts_by_zone: Optional[dict] = None


class ForecastResponse(BaseModel):
    by_zone: dict
    source: str


# ---- reviews ----

class ReviewCreate(BaseModel):
    order_id: int
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None
    photo_url: Optional[str] = Field(default=None, max_length=255)


class ReviewOut(BaseModel):
    id: int
    restaurant_id: int
    user_name: str
    rating: int
    comment: Optional[str]
    photo_url: Optional[str] = None
    owner_reply: Optional[str] = None
    replied_at: Optional[datetime] = None
    created_at: datetime


class ReviewReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=1000)


# ---- notifications ----

class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    message: Optional[str]
    order_id: Optional[int]
    read: bool
    created_at: datetime


class NotificationListOut(BaseModel):
    items: List[NotificationOut]
    unread: int


# ---- surge + receipts ----

class SurgeResponse(BaseModel):
    hour: int
    total_load: int
    surge_multiplier: float
    delivery_fee: float


class ReceiptResponse(BaseModel):
    order_id: int
    restaurant_name: str
    customer_name: str
    billed_to: Optional[str]
    items: List[OrderItemOut]
    food_total: float
    discount_amount: float
    delivery_fee: float
    surge_multiplier: float
    grand_total: float
    payment_method: str
    payment_status: str
    placed_at: datetime


# ---- addresses ----

class SavedAddressIn(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=1, max_length=255)
    lat: Optional[float] = None
    lng: Optional[float] = None


class UserRoleUpdate(BaseModel):
    role: str = Field(min_length=1, max_length=32)


# ---- payments (Layer 2) ----

class PaymentStatusOut(BaseModel):
    order_id: int
    payment_method: str
    payment_status: str
    payment_id: Optional[str] = None
    amount: float


class RazorpayCreateRequest(BaseModel):
    order_id: int


class RazorpayVerifyRequest(BaseModel):
    order_id: int
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentIntentResponse(BaseModel):
    order_id: int
    amount: float
    amount_paise: int
    currency: str = "INR"
    razorpay_order_id: str
    key_id: str
    test_mode: bool
    notes: dict = {}


# ---- live driver location (Layer 2c) ----

class DriverLocationUpdate(BaseModel):
    """A driver's current GPS position (lat/lng decimal degrees)."""

    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
