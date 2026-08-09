"""
FoodAI backend - Pydantic schemas (request/response contracts)
"""

from datetime import datetime
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


class ReviewOut(BaseModel):
    id: int
    restaurant_id: int
    user_name: str
    rating: int
    comment: Optional[str]
    created_at: datetime


# ---- addresses ----

class SavedAddressIn(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    address: str = Field(min_length=1, max_length=255)
    lat: Optional[float] = None
    lng: Optional[float] = None


class UserRoleUpdate(BaseModel):
    role: str = Field(min_length=1, max_length=32)
