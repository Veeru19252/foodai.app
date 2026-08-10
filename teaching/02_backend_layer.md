# FoodAI Teaching Guide — Part 2: The Backend Layer

> **Prerequisite:** read `teaching/01_database_layer.md` first (models, DB session, Alembic).
> This part walks every backend file that powers the API: auth/JWT, Pydantic schemas,
> tracking state, the simulation engine, the orders router, the **new payments router**,
> the ML router (overview — full ML deep-dive is Layer 3), and the FastAPI app itself.

**Format for every file**
```text
What it does   -> the file's job in one breath
Why this way   -> the design decision, and the constraint it respects
What breaks    -> the concrete failure you'd hit with the obvious alternative
How this connects -> where this file plugs into the rest of the system
```

---

## Layer diagram (how the request flows)

```text
   Next.js frontend (later layer)
        |  HTTPS JSON / WebSocket
        v
   FastAPI app (main.py)
        |  routers: auth, restaurants, orders, payments, tracking(ws), ml, admin, reviews, addresses
        |
        |-- security.py        (JWT + role checks, used by every router)
        |-- schemas.py         (Pydantic contracts — request/response shape)
        |-- tracking_state.py  (shared "what's happening with order N" brain)
        |-- simulation.py      (moves riders, publishes WS events, kitchen load)
        |
        +-- backend/db.py -> SQLAlchemy -> PostgreSQL (models.py from Part 1)
        +-- eta_service / explain_service / forecast_service / tracking / routing
                                 (ML services, deep-dive in Layer 3)
```

The two golden rules you'll see everywhere:
1. **Never trust the client.** Prices, discounts, roles, payment methods are always
   re-validated server-side.
2. **One source of truth for state.** Tracking REST and WebSocket both go through
   `tracking_state.py`, so they can never disagree.

---

## File 1 — `backend/security.py`

```python
"""
FoodAI backend - security helpers
==================================
Password hashing (SHA-256, parity with the legacy app so seeded users keep
working), JWT access/refresh tokens, and FastAPI auth dependencies with
role-based access control for the four roles.
"""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend import config
from backend.db import get_db
from backend.models import User

# Use a single Depends-able HTTPBearer so Swagger shows the lock icon.
_bearer = HTTPBearer(auto_error=False)

ROLE_HIERARCHY = ("customer", "restaurant", "delivery", "admin")


def hash_password(password: str) -> str:
    """Return the SHA-256 hex digest (legacy-compatible demo hashing)."""
    return sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish check (demo scheme; real prod would use bcrypt)."""
    return sha256(password.encode()).hexdigest() == password_hash


def _create_token(subject: str, role: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def create_access_token(user_id: int, role: str) -> str:
    return _create_token(
        str(user_id), role, timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: int, role: str) -> str:
    return _create_token(
        str(user_id), role, timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str) -> Optional[dict]:
    """Decode + validate a JWT; return its payload or None when invalid."""
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the Bearer token (raises 401)."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise unauthorized
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise unauthorized
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise unauthorized
    return user


def require_roles(*roles: str):
    """Return a dependency that allows only the given roles."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user

    return _checker


def authorize_token_for_order(user: User, order_owner_id: int, order_restaurant_id: int) -> None:
    """Raise 403 unless the user may view an order (owner/restaurant/admin)."""
    allowed = (
        user.role == "admin"
        or user.id == order_owner_id
        or (user.role == "restaurant" and user.id == order_restaurant_id)
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot access this order.",
        )
```

**What it does**
- Password hashing + verification (`hash_password`, `verify_password`).
- JWT minting (`_create_token`) and the two public wrappers: access token (short-lived) and refresh token (long-lived).
- `get_current_user` — the FastAPI dependency every protected route declares; it resolves the `User` row from the bearer token or raises 401.
- `require_roles(...)` — a *factory* that returns a dependency enforcing role membership (used like `Depends(customer_only)`).
- `authorize_token_for_order` — the order-scoped check.

**Why this way**
- **SHA-256 for parity**: the legacy Streamlit app hashed passwords this way, and `seed.py` pre-creates users with those hashes. Switching to bcrypt would lock every seeded demo user out. In real production you'd use bcrypt/argon2 *and* re-seed — this is a deliberate demo trade-off.
- **JWT in the DB-free direction**: `get_current_user` decodes the token, reads `sub` (user id), and loads the row from the DB. The token itself is stateless — only the DB lookup needs a connection. That means any service that can reach the DB can validate requests, which is what lets the same frontend talk to the API for all four roles.
- **`require_roles` returns a *new function*** (closure over `roles`) because FastAPI dependencies are resolved by inspecting function signatures. If you passed `roles` directly it would be evaluated once at import time; the closure captures them per-call so each guard is its own dependency.

**What breaks**
- If you hash with anything other than SHA-256 → every seeded user's password stops working (401 on login).
- If you stored the raw password instead of a hash → a leaked DB dumps plaintext credentials (the "what breaks with the alternative" you never want to hit).
- If `get_current_user` trusted `role` from the token without loading the DB row → a user who was demoted would keep their old privileges until token expiry.
- If you put `Authorization` parsing manually in every route → one route forgets it, and you've opened a hole; centralizing it in a dependency guarantees uniform enforcement.

**How this connects**
- `auth.py` calls `create_access_token`/`create_refresh_token` on login/register.
- Every router imports `security.get_current_user` or a `require_roles(...)` guard, so "who is allowed" is decided in exactly one place.
- `Order` rows store `customer_id`; `authorize_token_for_order` + the inline checks in `orders.py` tie the JWT subject to row ownership.

---

## File 2 — `backend/schemas.py`

```python
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
    # Payment + structured-address fields (Layer 2).
    payment_method: str = Field(default="COD", max_length=16)
    delivery_phone: Optional[str] = Field(default=None, max_length=15)
    delivery_city: Optional[str] = Field(default=None, max_length=64)
    delivery_state: Optional[str] = Field(default=None, max_length=64)
    delivery_pincode: Optional[str] = Field(default=None, max_length=10)


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
```

**What it does**
- Defines the *contracts*: every request body and every response shape, grouped by feature area (auth, restaurants, orders, tracking, ml, reviews, addresses, payments).

**Why this way**
- **Pydantic gives you validation for free.** `Field(ge=1)` on `quantity` means a negative quantity is rejected *before* your route code runs — one fewer class of bug.
- **`In` vs `Out` split mirrors the DB's "write vs read" split.** You never accept a field from the client that you don't intend to persist (notice `CreateOrderRequest` has no `total` — the server computes it).
- **Optional fields = backward compatibility.** `payment_method` defaults to `"COD"` so existing clients that omit it keep working (matches the DB column default we added in Layer 1 — contract and schema agree).
- **`dict` fields (`user`, `notes`)**: pragmatic shortcuts for demo responses; a stricter API would model them as nested models, but these are read-only blobs.

**What breaks**
- If `CreateOrderRequest` allowed the client to send `total` → a customer could place an order at ₹1 by forging the total (the #1 "why the server computes prices" lesson).
- If you removed the length constraints on `delivery_phone`/`delivery_pincode` → 20-digit "phone numbers" and 50-digit "pincodes" would flow straight into your DB.
- If you made the new payment fields required instead of optional → every existing frontend page that posts an order (before the frontend layer is updated) would start failing validation.

**How this connects**
- Routers import these classes: `payload: CreateOrderRequest` auto-validates the body; `response_model=OrderOut` shapes (and filters!) the response.
- `_order_detail()` in orders.py builds exactly the fields `OrderOut` declares — the contract is enforced at the edge, not scattered through route code.

---

## File 3 — `backend/tracking_state.py`

```python
"""
FoodAI backend - shared tracking state
=======================================
Pure-ish helpers that compute a live tracking state for an order using the
existing ML/route modules (tracking.py, routing.py, eta_service.py). Used by
both the REST tracking endpoint and the WebSocket simulation so the two views
can never drift apart.
"""

import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import eta_service
import routing
import tracking

from backend.models import Delivery, Order


def delivery_end(order: Order) -> Tuple[float, float]:
    """Return the order's stored delivery point, else the default home."""
    if order.delivery_lat is not None and order.delivery_lng is not None:
        return (order.delivery_lat, order.delivery_lng)
    return tracking.DEFAULT_CUSTOMER_HOME


def order_route(order: Order):
    """Return (route, distance_km) along real roads for an order.

    route is a tuple of (lat, lng) points; distance_km is the OSRM road
    distance (or haversine fallback). Cached per start/end pair. Restaurants
    created at runtime (no legacy coordinate) fall back to the demo home.
    """
    try:
        start = tracking.restaurant_coordinates(order.restaurant_id)
    except ValueError:
        start = tracking.DEFAULT_CUSTOMER_HOME
    end = delivery_end(order)
    return routing.get_route(start, end)


def rider_progress(
    order: Order, delivery: Optional[Delivery]
) -> Tuple[float, Tuple[float, float]]:
    """Return (progress 0..1, rider position) for a delivery.

    Before pickup the rider sits at the restaurant (progress 0). Afterwards
    progress is elapsed time over the trip estimate, walking the road route so
    the marker makes real turns.
    """
    start = tracking.restaurant_coordinates(order.restaurant_id)
    if delivery is None or delivery.pickup_time is None:
        return 0.0, start
    route, _ = order_route(order)
    pickup_epoch = _to_epoch_utc(delivery.pickup_time)
    elapsed = time.time() - pickup_epoch
    total_seconds = tracking.estimate_trip_seconds(list(route), tracking.AVG_SPEED_KMH)
    progress = min(1.0, max(0.0, elapsed / total_seconds)) if total_seconds > 0 else 1.0
    rider_pos = tracking.interpolate_position(list(route), progress)
    return progress, rider_pos


def eta_for_order(order: Order, progress: float) -> Tuple[Optional[float], str]:
    """Return (eta_min, source) using the existing ML pipeline (fallback-safe)."""
    route, _ = order_route(order)
    return eta_service.best_eta(
        list(route),
        progress,
        order.restaurant_id,
        prep_time_min=15,
        customer_home=delivery_end(order),
    )


def build_tracking_state(order: Order, delivery: Optional[Delivery]) -> dict:
    """Return the TrackingState dict for an order."""
    route, distance_km = order_route(order)
    progress, rider_pos = rider_progress(order, delivery)
    eta_min, eta_source = eta_for_order(order, progress)
    return {
        "order_id": order.id,
        "status": order.status,
        "restaurant_id": order.restaurant_id,
        "restaurant_name": order.restaurant.name if order.restaurant else "",
        "customer_name": order.customer.name if order.customer else "",
        "delivery_address": order.delivery_address,
        "created_at": order.created_at,
        "pickup_time": delivery.pickup_time if delivery else None,
        "delivered_time": delivery.delivered_time if delivery else None,
        "route": [[lat, lng] for lat, lng in route],
        "route_distance_km": round(distance_km, 2),
        "rider_lat": round(rider_pos[0], 6),
        "rider_lng": round(rider_pos[1], 6),
        "progress": round(progress, 4),
        "eta_min": eta_min,
        "eta_source": eta_source,
    }


def _to_epoch_utc(value: datetime) -> float:
    """Convert a (possibly naive-UTC) datetime to an epoch float."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()
```

**What it does**
- Turns "an order + an optional delivery row" into the full tracking picture: the road route, distance, the rider's current position/progress, and an ML-based ETA.

**Why this way**
- **Single source of truth.** The REST endpoint (`tracking.py`) and the WebSocket simulation (`simulation.py`) both call these same functions, so a customer polling REST and a rider on WebSockets can never see contradictory positions.
- **Graceful degradation everywhere.** Missing coordinates → `DEFAULT_CUSTOMER_HOME`; missing delivery → progress 0; missing model → `eta_source` reports fallback. The whole feature is "best effort, never crash."
- **Deterministic math, not stored state.** Rider position is *derived* from `pickup_time` + elapsed wall-clock time, interpolated along the route. No background thread needs to persist "rider is at x,y" — the simulation just needs to advance and broadcast, and any late subscriber computes the same answer from the same inputs.

**What breaks**
- If REST and WS computed positions separately → a customer and a rider looking at the same order could see different markers (the exact class of bug this file exists to prevent).
- If progress used `datetime.now()` naive vs UTC → off-by-timezone errors that are brutal to debug; `_to_epoch_utc` normalizes naive-UTC stamps explicitly.
- If you stored a new "rider_lat" column and updated it from the loop → every request hits the DB for a value you could derive in memory, and the two sources inevitably drift.

**How this connects**
- `simulation.py`'s `_advance_delivery` calls `rider_progress`, then writes a `TripLog` (history) and publishes the position.
- `tracking.py`'s REST endpoint calls `build_tracking_state` and returns it as `TrackingState` (schema).
- `orders.py` calls `order_route`/`rider_progress`/`eta_for_order` for earnings and the delay nudge.

---

## File 4 — `backend/simulation.py`

```python
"""
FoodAI backend - delivery simulation + WebSocket broker
========================================================
The demo has no real fleet, so rider movement is simulated: every 2 seconds
the engine advances each active delivery (picked up, not yet delivered) along
its OSRM road route and publishes live position/delivered events to everyone
subscribed to that order's WebSocket channel.

The ConnectionManager is the pub/sub broker. It is intentionally in-memory
for Phase 1 (single-process uvicorn); swapping in Redis later only requires
replacing publish()/subscribe() with channel-based calls.
"""

import asyncio
import logging
import math
import random
import traceback
from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional, Set

from backend.db import SessionLocal
from backend.models import Delivery, Order, TripLog
from backend.tracking_state import rider_progress

logger = logging.getLogger("foodai.simulation")

SIM_INTERVAL_SECONDS = 2.0

# Kitchen zones mirror the demand-forecast zones (A–E). Used by the
# kitchen-load simulation so restaurant owners see expected load.
KITCHEN_ZONES = ("A", "B", "C", "D", "E")


def poisson_count(mean: float) -> int:
    """Draw one Poisson-distributed integer (Knuth's algorithm).

    mean is the expected number of events; the result clusters around it
    (a mean of 12 returns 12 most often, 8 or 16 rarely). This gives the
    kitchen load realistic day-to-day variation instead of a fixed count.
    """
    limit = math.exp(-mean)
    k = 0
    product = 1.0
    while product > limit:
        k += 1
        product *= random.random()
    return k - 1


def kitchen_load(hour: Optional[int] = None) -> dict:
    """Simulate each kitchen zone's incoming order load for an hour.

    The expected arrival rate follows a two-hump curve: a modest baseline,
    a lunch peak near 13:00 and a bigger dinner peak near 20:00. The actual
    count per zone is a Poisson draw around that expectation, with busier
    zones (A, B — city centre) scaled up and the quietest (E) scaled down.
    """
    if hour is None:
        hour = datetime.utcnow().hour
    lunch_peak = 45.0 * math.exp(-0.5 * ((hour - 13) / 2.0) ** 2)
    dinner_peak = 60.0 * math.exp(-0.5 * ((hour - 20) / 2.0) ** 2)
    baseline = 10.0
    loads = {}
    for zone in KITCHEN_ZONES:
        expected = baseline + lunch_peak + dinner_peak
        if zone in ("A", "B"):
            expected *= 1.25
        elif zone == "E":
            expected *= 0.8
        loads[zone] = poisson_count(expected)
    return {"hour": hour, "loads": loads, "total": sum(loads.values())}


class ConnectionManager:
    """In-process pub/sub for order tracking channels (order_id -> sockets)."""

    def __init__(self) -> None:
        self._channels: Dict[int, Set] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, order_id: int, websocket) -> None:
        async with self._lock:
            self._channels[order_id].add(websocket)

    async def unsubscribe(self, order_id: int, websocket) -> None:
        async with self._lock:
            self._channels[order_id].discard(websocket)
            if not self._channels[order_id]:
                self._channels.pop(order_id, None)

    async def publish(self, order_id: int, message: dict) -> None:
        async with self._lock:
            sockets = list(self._channels.get(order_id, ()))
        dead = []
        for socket in sockets:
            try:
                await socket.send_json(message)
            except Exception:
                dead.append(socket)
        for socket in dead:
            await self.unsubscribe(order_id, socket)


manager = ConnectionManager()

# Separate channel namespace for per-user notifications (e.g. drivers being
# assigned a delivery). Channels are string keys like "user:7".
notifications_manager = ConnectionManager()

# Set during app startup so sync request handlers (which run in worker
# threads) can publish onto the main event loop safely.
MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def publish_sync(manager_: ConnectionManager, channel, message: dict) -> None:
    """Publish a message from a worker thread onto the main event loop."""
    if MAIN_LOOP is not None:
        asyncio.run_coroutine_threadsafe(
            manager_.publish(channel, message), MAIN_LOOP
        )


def _advance_delivery(db, delivery: Delivery) -> Optional[dict]:
    """Advance one delivery one tick; return an event dict to publish (or None)."""
    order = db.query(Order).filter(Order.id == delivery.order_id).first()
    if order is None or order.status != "OUT_FOR_DELIVERY":
        return None
    progress, rider_pos = rider_progress(order, delivery)
    db.add(TripLog(delivery_id=delivery.id, lat=rider_pos[0], lng=rider_pos[1]))
    delivered = progress >= 1.0
    if delivered:
        delivery.delivered_time = datetime.utcnow()
        order.status = "DELIVERED"
    db.commit()
    return {
        "type": "delivered" if delivered else "position",
        "order_id": order.id,
        "status": order.status,
        "lat": round(rider_pos[0], 6),
        "lng": round(rider_pos[1], 6),
        "progress": round(progress, 4),
        "delivery_address": order.delivery_address,
    }


def advance_all_deliveries(loop: asyncio.AbstractEventLoop) -> None:
    """Advance every active delivery and publish events (called on a timer)."""
    db = SessionLocal()
    try:
        deliveries = (
            db.query(Delivery)
            .filter(Delivery.pickup_time.isnot(None), Delivery.delivered_time.is_(None))
            .all()
        )
        for delivery in deliveries:
            event = _advance_delivery(db, delivery)
            if event is not None:
                loop.create_task(manager.publish(delivery.order_id, event))
    except Exception:
        logger.exception("simulation tick failed")
    finally:
        db.close()


async def simulation_loop() -> None:
    """Background task: tick every SIM_INTERVAL_SECONDS forever."""
    logger.info("delivery simulation started")
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(SIM_INTERVAL_SECONDS)
        try:
            # Run the sync DB work in the default executor so the event loop
            # stays responsive for WebSocket traffic. The loop reference is
            # passed explicitly: get_event_loop() in a worker thread would
            # create an unrelated loop that never runs.
            await loop.run_in_executor(None, advance_all_deliveries, loop)
        except Exception:
            traceback.print_exc()
```

**What it does**
- Simulates the rider fleet (advances every active delivery each tick and broadcasts position events over WebSockets).
- Acts as the pub/sub broker (`ConnectionManager`, plus a separate `notifications_manager` for per-user channels like "you got a delivery").
- **New in Layer 2:** `poisson_count` + `kitchen_load` — a realistic per-zone kitchen-load snapshot.

**Why this way**
- **In-memory pub/sub on purpose.** Phase 1 runs one uvicorn process, so a `defaultdict(order_id -> {websockets})` is enough. The class shape mirrors a Redis pub/sub API, so swapping later means replacing two method bodies, not rewriting callers.
- **Simulation *derives* position from time** (via `rider_progress`) rather than storing coordinates, so it stays consistent with the REST view and with late joiners.
- **`publish_sync` + `MAIN_LOOP` solve a real asyncio trap.** FastAPI runs sync endpoints in worker threads; from a thread you cannot `await` or call `loop.create_task`. `run_coroutine_threadsafe` hands the coroutine to the *main* event loop, which is the only loop actually running.
- **`run_in_executor` keeps the loop responsive.** DB queries inside `advance_all_deliveries` are blocking; running them in the default executor keeps WebSocket traffic flowing during a slow tick.
- **Poisson for kitchen load because it's how demand actually behaves** — arrivals cluster around an expected rate but jitter realistically. Knuth's algorithm is only ~5 lines and needs no numpy.
- **Two-hump hourly curve** (baseline + lunch ~13:00 + dinner ~20:00) matches how real delivery platforms see demand; busier zones scaled up.

**What breaks**
- If `publish_sync` called `asyncio.get_event_loop()` from the worker thread → you'd get a *different, non-running* loop and the coroutine would never execute (the comment in the file says this explicitly).
- If the sync DB work ran directly in the async loop → a slow Postgres query would stall *every* WebSocket send on the server (queueing, latency spikes).
- If `poisson_count` used `math.exp(-mean)` with mean huge → probability underflows to 0 and the loop spins forever (a classic; our means stay small, and the algorithm is standard).
- If you removed the `dead` socket sweep → disconnected riders would accumulate forever and `send_json` would raise on every publish.

**How this connects**
- `main.py` starts `simulation.simulation_loop()` in the lifespan and sets `simulation.MAIN_LOOP`.
- `tracking.py`'s WebSocket endpoint subscribes sockets to `order:<id>` channels.
- `orders.py` publishes `delivery_assigned` to `user:<driver_id>` via `notifications_manager` + `publish_sync`.
- `ml.py`'s new `/ml/kitchen-load` endpoint calls `simulation.kitchen_load(hour)`.

---

## File 5 — `backend/routers/orders.py`

```python
"""
FoodAI backend - orders router
===============================
Customer order creation/listing, restaurant order management, driver
assignment, and promo-code validation. Prices are always taken from the
server-side menu (never from the client), and promo logic is a parity port of
database.py (validate_promo_code / calculate_discount / increment usage).
"""

from datetime import date, datetime

import tracking
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import security, simulation
from backend.db import get_db
from backend.models import (
    Delivery,
    MenuItem,
    Order,
    OrderItem,
    PromoCode,
    Restaurant,
    TripLog,
    User,
    VALID_ORDER_STATUSES,
    VALID_PAYMENT_METHODS,
)
from backend.schemas import (
    AssignDeliveryRequest,
    BatchOrderRequest,
    BatchOrderResponse,
    CreateOrderRequest,
    OrderItemOut,
    OrderOut,
    PromoApplyRequest,
    PromoApplyResponse,
    UpdateOrderStatusRequest,
)
from backend.simulation import publish_sync
from backend.security import get_current_user
from backend.tracking_state import eta_for_order, order_route, rider_progress

router = APIRouter(prefix="/orders", tags=["orders"])

customer_only = security.require_roles("customer")
restaurant_or_admin = security.require_roles("restaurant", "admin")
restaurant_admin_or_delivery = security.require_roles("restaurant", "admin", "delivery")


# ---- promo helpers (parity port) ----

def _promo_payload(promo: PromoCode) -> dict:
    return {
        "id": promo.id,
        "code": promo.code,
        "description": promo.description,
        "discount_type": promo.discount_type,
        "discount_value": promo.discount_value,
        "min_order_value": promo.min_order_value,
        "max_discount": promo.max_discount,
        "valid_until": promo.valid_until,
        "usage_limit": promo.usage_limit,
        "times_used": promo.times_used,
        "active": 1 if promo.active else 0,
    }


def validate_promo_code(db: Session, code: str, order_total: float):
    """Return (ok, message, promo_or_None), mirroring database.py semantics."""
    promo = db.query(PromoCode).filter(PromoCode.code == code).first()
    if promo is None:
        return False, "Invalid promo code.", None
    if not promo.active:
        return False, "This promo code is no longer active.", None
    if promo.valid_until is not None:
        valid_until = promo.valid_until
        if isinstance(valid_until, str):
            valid_until = date.fromisoformat(valid_until[:10])
        if valid_until < date.today():
            return False, "This promo code has expired.", None
    if order_total < promo.min_order_value:
        return False, f"This promo requires a minimum order of ₹{promo.min_order_value:.0f}.", None
    if promo.usage_limit is not None and promo.times_used >= promo.usage_limit:
        return False, "This promo code has reached its usage limit.", None
    return True, "Promo code applied!", promo


def calculate_discount(promo: PromoCode, order_total: float) -> float:
    if promo.discount_type == "flat":
        discount = min(promo.discount_value, order_total)
    else:  # percent
        raw = order_total * promo.discount_value / 100.0
        cap = promo.max_discount if promo.max_discount is not None else order_total
        discount = min(raw, cap)
    return round(max(0.0, min(discount, order_total)), 2)


# ---- serialization ----

def _order_brief(order: Order) -> dict:
    return {
        "id": order.id,
        "restaurant_id": order.restaurant_id,
        "restaurant_name": order.restaurant.name if order.restaurant else "",
        "status": order.status,
        "total": round(order.total, 2),
        "created_at": order.created_at,
        "delivery_address": order.delivery_address,
    }


def _order_detail(order: Order) -> dict:
    items = [
        OrderItemOut(name=oi.menu_item.name if oi.menu_item else "Item", quantity=oi.quantity, price=oi.price)
        for oi in order.items
    ]
    return {
        **_order_brief(order),
        "customer_name": order.customer.name if order.customer else "",
        "coupon_code": order.coupon_code,
        "discount_amount": round(order.discount_amount, 2),
        "delivery_lat": order.delivery_lat,
        "delivery_lng": order.delivery_lng,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "delivery_phone": order.delivery_phone,
        "delivery_city": order.delivery_city,
        "delivery_state": order.delivery_state,
        "delivery_pincode": order.delivery_pincode,
        "items": [i.dict() for i in items],
    }


# ---- endpoints (static paths first so they beat /{order_id}) ----

@router.get("/drivers")
def list_drivers(user: User = Depends(restaurant_or_admin), db: Session = Depends(get_db)):
    drivers = db.query(User).filter(User.role == "delivery").order_by(User.name).all()
    return [{"id": d.id, "name": d.name, "email": d.email} for d in drivers]


@router.post("/promo/validate", response_model=PromoApplyResponse)
def validate_promo(
    payload: PromoApplyRequest,
    user: User = Depends(customer_only),
    db: Session = Depends(get_db),
):
    ok, message, promo = validate_promo_code(db, payload.code, payload.order_total)
    discount = calculate_discount(promo, payload.order_total) if promo else 0.0
    return PromoApplyResponse(ok=ok, message=message, discount=discount)


@router.get("")
def my_orders(user: User = Depends(customer_only), db: Session = Depends(get_db)):
    orders = (
        db.query(Order)
        .filter(Order.customer_id == user.id)
        .order_by(Order.id.desc())
        .all()
    )
    return [_order_brief(o) for o in orders]


@router.get("/restaurant")
def restaurant_orders(user: User = Depends(restaurant_or_admin), db: Session = Depends(get_db)):
    query = (
        db.query(Order)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .order_by(Order.id.desc())
    )
    if user.role == "restaurant":
        query = query.filter(Restaurant.user_id == user.id)
    orders = query.all()
    return [
        {
            "id": o.id,
            "customer_name": o.customer.name if o.customer else "",
            "status": o.status,
            "total": round(o.total, 2),
            "created_at": o.created_at,
            "assigned_driver_id": o.assigned_driver.id if o.assigned_driver else None,
            "assigned_driver_name": o.assigned_driver.name if o.assigned_driver else None,
        }
        for o in orders
    ]


@router.get("/driver")
def driver_orders(user: User = Depends(security.require_roles("delivery")), db: Session = Depends(get_db)):
    deliveries = (
        db.query(Delivery)
        .filter(Delivery.driver_id == user.id)
        .order_by(Delivery.id.desc())
        .all()
    )
    result = []
    for d in deliveries:
        order = db.query(Order).filter(Order.id == d.order_id).first()
        if order is None:
            continue
        result.append({
            "delivery_id": d.id,
            "order_id": order.id,
            "restaurant_name": order.restaurant.name if order.restaurant else "",
            "customer_name": order.customer.name if order.customer else "",
            "order_status": order.status,
            "pickup_time": d.pickup_time,
            "delivered_time": d.delivered_time,
        })
    return result


PER_DELIVERY_RATE = 60.0
PER_KM_RATE = 12.0


@router.get("/driver/earnings")
def driver_earnings(
    user: User = Depends(security.require_roles("delivery")),
    db: Session = Depends(get_db),
):
    """Driver earnings dashboard: flat rate per delivered order plus a
    distance-based top-up, computed from completed deliveries only."""
    deliveries = (
        db.query(Delivery)
        .filter(Delivery.driver_id == user.id)
        .order_by(Delivery.id.desc())
        .all()
    )
    completed = [d for d in deliveries if d.delivered_time is not None]
    recent = []
    total_earned = 0.0
    for d in deliveries:
        order = db.query(Order).filter(Order.id == d.order_id).first()
        if order is None:
            continue
        try:
            _route, distance_km = order_route(order)
        except ValueError:
            distance_km = 1.0
        distance_km = max(distance_km, 1.0)
        earned = PER_DELIVERY_RATE + PER_KM_RATE * distance_km
        if d.delivered_time is not None:
            total_earned += earned
        recent.append({
            "delivery_id": d.id,
            "order_id": order.id,
            "restaurant_name": order.restaurant.name if order.restaurant else "",
            "customer_name": order.customer.name if order.customer else "",
            "distance_km": round(distance_km, 2),
            "earned": round(earned, 2) if d.delivered_time else 0.0,
            "completed_at": d.delivered_time,
        })
    return {
        "per_delivery_rate": PER_DELIVERY_RATE,
        "per_km_rate": PER_KM_RATE,
        "total_earnings": round(total_earned, 2),
        "total_deliveries": len(deliveries),
        "completed_deliveries": len(completed),
        "active_deliveries": sum(
            1 for d in deliveries if d.pickup_time is not None and d.delivered_time is None
        ),
        "recent": recent[:10],
    }


def _create_single_order(db: Session, user: User, payload: CreateOrderRequest) -> Order:
    """Create one order for a restaurant group (shared by single + batch)."""
    restaurant = db.query(Restaurant).filter(Restaurant.id == payload.restaurant_id).first()
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found.")

    # Resolve prices server-side; reject items that aren't on this menu.
    menu_items = {
        mi.id: mi
        for mi in db.query(MenuItem).filter(MenuItem.restaurant_id == payload.restaurant_id).all()
    }
    for line in payload.items:
        if line.menu_item_id not in menu_items:
            raise HTTPException(status_code=400, detail=f"Menu item {line.menu_item_id} is not on this restaurant's menu.")

    subtotal = sum(menu_items[line.menu_item_id].price * line.quantity for line in payload.items)

    discount = 0.0
    promo = None
    if payload.coupon_code:
        ok, message, promo = validate_promo_code(db, payload.coupon_code, subtotal)
        if not ok:
            raise HTTPException(status_code=400, detail=message)
        discount = calculate_discount(promo, subtotal)

    if payload.payment_method not in VALID_PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Unsupported payment method.")

    order = Order(
        customer_id=user.id,
        restaurant_id=payload.restaurant_id,
        total=max(0.0, subtotal - discount),
        coupon_code=payload.coupon_code,
        discount_amount=discount,
        delivery_lat=payload.delivery_lat,
        delivery_lng=payload.delivery_lng,
        delivery_address=payload.delivery_address,
        payment_method=payload.payment_method,
        delivery_phone=payload.delivery_phone,
        delivery_city=payload.delivery_city,
        delivery_state=payload.delivery_state,
        delivery_pincode=payload.delivery_pincode,
        status="PLACED",
    )
    db.add(order)
    db.flush()
    for line in payload.items:
        db.add(OrderItem(
            order_id=order.id,
            menu_item_id=line.menu_item_id,
            quantity=line.quantity,
            price=menu_items[line.menu_item_id].price,
        ))
    if promo is not None:
        promo.times_used += 1
    db.commit()
    db.refresh(order)
    return order


@router.post("", response_model=OrderOut, status_code=201)
def create_order(
    payload: CreateOrderRequest,
    user: User = Depends(customer_only),
    db: Session = Depends(get_db),
):
    return _order_detail(_create_single_order(db, user, payload))


@router.post("/batch", response_model=BatchOrderResponse, status_code=201)
def create_orders_batch(
    payload: BatchOrderRequest,
    user: User = Depends(customer_only),
    db: Session = Depends(get_db),
):
    """Create one order per restaurant group in a single cart (Swiggy-style)."""
    orders = [_create_single_order(db, user, req) for req in payload.orders]
    return BatchOrderResponse(orders=[_order_detail(o) for o in orders])


@router.post("/{order_id}/reorder", response_model=OrderOut, status_code=201)
def reorder_order(
    order_id: int,
    user: User = Depends(customer_only),
    db: Session = Depends(get_db),
):
    """One-tap "Order again": clone a past order's items into a fresh PLACED
    order at the same restaurant (prices re-resolved server-side)."""
    source = db.query(Order).filter(Order.id == order_id).first()
    if source is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if source.customer_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot reorder this order.")

    menu = {
        mi.id: mi
        for mi in db.query(MenuItem)
        .filter(MenuItem.restaurant_id == source.restaurant_id)
        .all()
    }
    for oi in source.items:
        if oi.menu_item_id not in menu:
            raise HTTPException(
                status_code=400,
                detail="One or more items are no longer on this restaurant's menu.",
            )

    subtotal = sum(menu[oi.menu_item_id].price * oi.quantity for oi in source.items)
    order = Order(
        customer_id=user.id,
        restaurant_id=source.restaurant_id,
        total=round(subtotal, 2),
        delivery_lat=source.delivery_lat,
        delivery_lng=source.delivery_lng,
        delivery_address=source.delivery_address,
        payment_method=source.payment_method,
        delivery_phone=source.delivery_phone,
        delivery_city=source.delivery_city,
        delivery_state=source.delivery_state,
        delivery_pincode=source.delivery_pincode,
        status="PLACED",
    )
    db.add(order)
    db.flush()
    for oi in source.items:
        db.add(OrderItem(
            order_id=order.id,
            menu_item_id=oi.menu_item_id,
            quantity=oi.quantity,
            price=menu[oi.menu_item_id].price,
        ))
    db.commit()
    db.refresh(order)
    return _order_detail(order)


@router.get("/{order_id}")
def get_order(
    order_id: int,
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if user.role == "delivery":
        is_driver = db.query(Delivery).filter(
            Delivery.order_id == order_id, Delivery.driver_id == user.id
        ).first() is not None
        if not is_driver and user.role != "admin":
            raise HTTPException(status_code=403, detail="You cannot access this order.")
    elif user.role == "customer" and order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot access this order.")
    elif (
        user.role == "restaurant"
        and not any(r.id == order.restaurant_id for r in user.restaurants)
    ):
        raise HTTPException(status_code=403, detail="You cannot access this order.")
    return _order_detail(order)


@router.patch("/{order_id}/status")
def update_order_status(
    order_id: int,
    payload: UpdateOrderStatusRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Advance an order's status. Restaurant owners (and admins) can confirm/
    dispatch; the assigned driver can start their trip (OUT_FOR_DELIVERY)."""
    if payload.status not in VALID_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {payload.status}")
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")

    is_restaurant_owner = (
        user.role == "restaurant"
        and any(r.id == order.restaurant_id for r in user.restaurants)
    )
    is_admin = user.role == "admin"
    is_assigned_driver = (
        user.role == "delivery"
        and db.query(Delivery).filter(
            Delivery.order_id == order_id, Delivery.driver_id == user.id
        ).first() is not None
    )

    if payload.status == "OUT_FOR_DELIVERY":
        # Only the restaurant owner, admin, or the assigned driver may dispatch.
        if not (is_restaurant_owner or is_admin or is_assigned_driver):
            raise HTTPException(status_code=403, detail="You cannot dispatch this order.")
        if not is_assigned_driver and not db.query(Delivery).filter(
            Delivery.order_id == order_id
        ).first():
            raise HTTPException(status_code=400, detail="Assign a driver before dispatching.")
    elif payload.status in ("CONFIRMED", "PREPARING"):
        if not (is_restaurant_owner or is_admin):
            raise HTTPException(status_code=403, detail="Only the restaurant can update this order.")
    else:
        if not (is_restaurant_owner or is_admin):
            raise HTTPException(status_code=403, detail="You cannot update this order.")

    order.status = payload.status
    # Starting the trip stamps pickup_time so the simulation engine advances
    # the rider along the route (mirrors the legacy driver "Start Delivery").
    if payload.status == "OUT_FOR_DELIVERY":
        delivery = db.query(Delivery).filter(Delivery.order_id == order.id).first()
        if delivery is not None and delivery.pickup_time is None:
            delivery.pickup_time = datetime.utcnow()
    db.commit()
    return _order_detail(order)


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Customer (or admin) cancels an order that hasn't left the kitchen yet."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if user.role == "customer" and order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot cancel this order.")
    if user.role not in ("customer", "admin"):
        raise HTTPException(status_code=403, detail="You cannot cancel this order.")
    if order.status in ("DELIVERED", "CANCELLED", "OUT_FOR_DELIVERY"):
        raise HTTPException(status_code=400, detail=f"Order cannot be cancelled once {order.status}.")
    order.status = "CANCELLED"
    db.commit()
    return _order_detail(order)


@router.post("/{order_id}/assign")
def assign_delivery(
    order_id: int,
    payload: AssignDeliveryRequest,
    user: User = Depends(restaurant_or_admin),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if user.role == "restaurant" and order.restaurant_id not in [
        r.id for r in user.restaurants
    ]:
        raise HTTPException(status_code=403, detail="Not your restaurant's order.")
    driver = db.query(User).filter(User.id == payload.driver_id, User.role == "delivery").first()
    if driver is None:
        raise HTTPException(status_code=400, detail="Driver not found.")
    existing = db.query(Delivery).filter(Delivery.order_id == order_id).first()
    if existing is not None:
        return {"delivery_id": existing.id, "message": "Delivery already assigned."}
    delivery = Delivery(order_id=order_id, driver_id=payload.driver_id)
    db.add(delivery)
    order.delivery_id = payload.driver_id
    db.commit()
    db.refresh(delivery)
    # Notify the driver in real time over their notification channel.
    publish_sync(
        simulation.notifications_manager,
        f"user:{driver.id}",
        {
            "type": "delivery_assigned",
            "order_id": order.id,
            "restaurant_name": order.restaurant.name if order.restaurant else "Restaurant",
            "customer_name": order.customer.name if order.customer else "Customer",
            "message": f"New delivery assigned for order #{order.id}",
        },
    )
    return {"delivery_id": delivery.id, "message": "Delivery assigned."}


def _rider_last_position(db: Session, driver_id: int, fallback) -> tuple:
    """Return the rider's last known position (latest TripLog), else fallback."""
    log = (
        db.query(TripLog)
        .join(Delivery, Delivery.id == TripLog.delivery_id)
        .filter(Delivery.driver_id == driver_id)
        .order_by(TripLog.timestamp.desc())
        .first()
    )
    if log is None:
        return fallback
    return (log.lat, log.lng)


def _rider_load(db: Session, driver_id: int) -> dict:
    deliveries = db.query(Delivery).filter(Delivery.driver_id == driver_id).all()
    active = sum(1 for d in deliveries if d.pickup_time is not None and d.delivered_time is None)
    queued = sum(1 for d in deliveries if d.pickup_time is None)
    return {"active": active, "queued": queued, "load": active * 2 + queued}


@router.post("/{order_id}/auto-assign")
def auto_assign_delivery(
    order_id: int,
    user: User = Depends(restaurant_or_admin),
    db: Session = Depends(get_db),
):
    """Smart auto-dispatch: pick the rider with the lowest combined load and
    distance-to-restaurant score (Swiggy-style smart allocation)."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if user.role == "restaurant" and order.restaurant_id not in [
        r.id for r in user.restaurants
    ]:
        raise HTTPException(status_code=403, detail="Not your restaurant's order.")
    existing = db.query(Delivery).filter(Delivery.order_id == order_id).first()
    if existing is not None:
        driver = db.query(User).filter(User.id == existing.driver_id).first()
        return {
            "delivery_id": existing.id,
            "driver_name": driver.name if driver else "",
            "message": "Delivery already assigned.",
            "reason": "Rider already assigned to this order",
        }

    drivers = (
        db.query(User)
        .filter(User.role == "delivery")
        .order_by(User.name)
        .all()
    )
    if not drivers:
        raise HTTPException(status_code=400, detail="No riders available.")

    try:
        restaurant_pos = tracking.restaurant_coordinates(order.restaurant_id)
    except ValueError:
        restaurant_pos = tracking.DEFAULT_CUSTOMER_HOME

    best = None
    for driver in drivers:
        load = _rider_load(db, driver.id)
        pos = _rider_last_position(db, driver.id, restaurant_pos)
        dist_km = tracking.haversine_km(pos, restaurant_pos)
        score = load["load"] + dist_km * 0.5
        candidate = {
            "driver": driver,
            "load": load,
            "dist_km": dist_km,
            "score": score,
        }
        if best is None or score < best["score"]:
            best = candidate

    delivery = Delivery(order_id=order_id, driver_id=best["driver"].id)
    db.add(delivery)
    order.delivery_id = best["driver"].id
    db.commit()
    db.refresh(delivery)
    publish_sync(
        simulation.notifications_manager,
        f"user:{best['driver'].id}",
        {
            "type": "delivery_assigned",
            "order_id": order.id,
            "restaurant_name": order.restaurant.name if order.restaurant else "Restaurant",
            "customer_name": order.customer.name if order.customer else "Customer",
            "message": f"New delivery assigned for order #{order.id}",
        },
    )
    return {
        "delivery_id": delivery.id,
        "driver_name": best["driver"].name,
        "message": "Rider auto-assigned.",
        "reason": (
            f"Lowest load ({best['load']['active']} active, {best['load']['queued']} queued) "
            f"and {best['dist_km']:.1f} km from the restaurant"
        ),
    }


@router.get("/{order_id}/nudge")
def order_nudge(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delay-prediction nudge for restaurant owners, the assigned rider, and
    admins. Compares elapsed time against the ML/route ETA and flags at-risk
    orders so they can be reprioritized."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    is_restaurant_owner = (
        user.role == "restaurant"
        and any(r.id == order.restaurant_id for r in user.restaurants)
    )
    is_admin = user.role == "admin"
    is_assigned_driver = (
        user.role == "delivery"
        and db.query(Delivery)
        .filter(Delivery.order_id == order_id, Delivery.driver_id == user.id)
        .first()
        is not None
    )
    if not (is_restaurant_owner or is_admin or is_assigned_driver):
        raise HTTPException(status_code=403, detail="You cannot view this order.")

    delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
    route, _ = order_route(order)
    progress, _rider = rider_progress(order, delivery)
    eta_min, _source = eta_for_order(order, progress)

    if order.status in ("DELIVERED", "CANCELLED"):
        return {
            "order_id": order.id,
            "status": order.status,
            "delay_min": 0,
            "risk": "LOW",
            "message": "Order finished.",
            "eta_min": eta_min,
            "progress": round(progress, 4),
        }

    elapsed_min = (
        (datetime.utcnow() - order.created_at).total_seconds() / 60.0
        if order.created_at
        else 0.0
    )
    # Expected full-trip minutes = prep allowance + whole-route travel time.
    travel_min = tracking.compute_eta(route, 0.0, tracking.AVG_SPEED_KMH)
    expected_total = 15 + travel_min
    delay = max(0.0, elapsed_min - expected_total)

    if delay >= 10:
        risk = "HIGH"
        message = (
            f"This order is running ~{delay:.0f} min late. Consider prioritizing "
            "prep or reassigning the rider."
        )
    elif delay >= 3:
        risk = "MEDIUM"
        message = f"This order is running ~{delay:.0f} min behind. Keep it moving."
    else:
        risk = "LOW"
        message = "On track — no action needed."

    return {
        "order_id": order.id,
        "status": order.status,
        "delay_min": round(delay, 1),
        "risk": risk,
        "message": message,
        "eta_min": eta_min,
        "progress": round(progress, 4),
        "elapsed_min": round(elapsed_min, 1),
    }
```

**What it does**
- Everything order-shaped: create/list orders (single + batch + reorder), promo validation, status transitions, cancel, manual + auto driver assignment, driver earnings, delay nudges.

**Why this way**
- **Prices are server-side only.** `_create_single_order` looks up `MenuItem.price` from the DB; the client only sends `menu_item_id` + `quantity`. If the client could send a price, forgery would be trivial.
- **Static paths before dynamic.** `GET /drivers`, `/promo/validate`, `/restaurant`, `/driver` are declared *above* `GET /{order_id}`. FastAPI matches in declaration order, so `/drivers` must win over `/{order_id}` — reorder them and "drivers" gets parsed as an order id.
- **`_create_single_order` shared by single + batch.** Batch (Swiggy multi-restaurant cart) reuses the exact same validation, so a bug fix applies to both paths automatically.
- **Ownership checks are explicit per endpoint.** Customers see their own, restaurants their own, riders their assigned — via small inline predicates rather than one clever helper, which keeps each rule readable (at the cost of some repetition, accepted deliberately).
- **The status machine is guarded, not free-form.** `update_order_status` checks *who* may perform *which* transition, and dispatching requires an assigned `Delivery` first. `OUT_FOR_DELIVERY` stamps `pickup_time` — that's the trigger that makes the simulation start moving the rider.
- **Auto-assign scores `load + 0.5 × distance`.** A rider who is idle but far scores worse than a slightly-busy rider who is close — the classic delivery-platform trade-off, made explicit and tunable.
- **Nudge reuses the shared ETA** (`eta_for_order`) so the "is this late?" answer is consistent with what the customer sees.
- **Layer 2 additions**: `payment_method` is validated against the model constants before the order is created, and the structured address fields (phone/city/state/pincode) ride along on create and reorder.

**What breaks**
- `POST /payments/razorpay/order` placed before `POST /orders` … no, more precisely: if `/orders/drivers` came *after* `/orders/{order_id}`, `GET /orders/drivers` would 422 (drivers can't be an int).
- If `batch` didn't share `_create_single_order` → coupon usage (`promo.times_used`) could be incremented twice per cart, or skipped entirely.
- If `update_order_status` allowed any role to set any status → a customer could mark their order `DELIVERED` without ever receiving it.
- If `assign` didn't check `existing` → re-assigning creates duplicate `Delivery` rows for the same order.
- If `cancel_order` allowed cancelling `OUT_FOR_DELIVERY` → the simulation would keep moving a rider for a cancelled order (we block it explicitly).
- If `payment_method` weren't validated → any string lands in the DB; later the payments router would 400 on unknown methods anyway, but it's cheaper to fail at creation.

**How this connects**
- Calls `security.require_roles` (guards), `get_db` (session), `tracking_state` (route/progress/ETA), `simulation.notifications_manager + publish_sync` (real-time driver alerts), and `VALID_PAYMENT_METHODS` from models (Layer 1).
- The new `payments.py` router reads `order.total`, `order.payment_method`, `order.payment_status` — all written here at creation.

---

## File 6 — `backend/routers/payments.py` (NEW in Layer 2)

```python
"""
FoodAI backend - payments router
==================================
Two payment modes, both demo-ready:

1. COD (Cash on Delivery) — *fully working*, no external dependency. The
   customer picks COD at checkout (``payment_method='COD'``), and when the
   rider drops the order off, the customer (or an admin) marks the cash as
   collected -> ``payment_status='PAID'``. Reversing it before collection
   -> ``'FAILED'``. No money ever moves through us.

2. Razorpay — *test-mode interface*. A real deployment would call Razorpay's
   Orders API to create an intent and verify its webhook signature. This
   demo keeps the exact same contract (amount in paise, currency INR,
   razorpay_order_id / razorpay_payment_id / razorpay_signature) but runs
   against placeholder keys, so ``test_mode: true`` is returned and the
   frontend can render "Razorpay (test)". Drop in real keys via env vars
   (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET) and only the signature step
   changes — the code path is identical.

The money record always lives on the Order row (payment_method,
payment_status, payment_id), matching how the legacy app stored payments, so
every other router can show payment state without joining another table.
"""

import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import config
from backend.db import get_db
from backend.models import Order, User, VALID_PAYMENT_METHODS, VALID_PAYMENT_STATUSES
from backend.schemas import (
    PaymentIntentResponse,
    PaymentStatusOut,
    RazorpayCreateRequest,
    RazorpayVerifyRequest,
)
from backend.security import get_current_user

router = APIRouter(prefix="/payments", tags=["payments"])

# Placeholder test keys. In production set RAZORPAY_KEY_ID and
# RAZORPAY_KEY_SECRET in the environment; getattr keeps local runs green
# even though config.py does not define them.
RAZORPAY_KEY_ID = getattr(config, "RAZORPAY_KEY_ID", "rzp_test_FoodAI_demo")
RAZORPAY_KEY_SECRET = getattr(config, "RAZORPAY_KEY_SECRET", "foodai_demo_secret")


def _get_order(db: Session, order_id: int) -> Order:
    """Fetch an order by id or raise the standard 404."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    return order


def _can_view_payment(user: User, order: Order) -> bool:
    """Who may read a payment: the customer, the restaurant, or an admin."""
    if user.role == "admin":
        return True
    if user.role == "customer":
        return order.customer_id == user.id
    if user.role == "restaurant":
        return any(r.id == order.restaurant_id for r in user.restaurants)
    return False


def _can_manage_payment(user: User, order: Order) -> bool:
    """Who may *change* a payment: the customer or an admin. Restaurants can
    see the payment state but never collect/reverse money."""
    return user.role == "admin" or order.customer_id == user.id


def _payment_dict(order: Order) -> dict:
    return {
        "order_id": order.id,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "payment_id": order.payment_id,
        "amount": round(order.total, 2),
    }


# ---- COD (fully working) ----

@router.post("/orders/{order_id}/cod/confirm", response_model=PaymentStatusOut)
def confirm_cod(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a COD order as collected (cash handed to the rider at the door).

    Only valid for COD orders in a collectable state; admin can confirm any
    COD order, a customer only their own.
    """
    order = _get_order(db, order_id)
    if not _can_manage_payment(user, order):
        raise HTTPException(status_code=403, detail="You cannot confirm this payment.")
    if order.payment_method != "COD":
        raise HTTPException(status_code=400, detail="This order is not a COD order.")
    if order.payment_status not in ("PENDING", "FAILED"):
        raise HTTPException(
            status_code=400, detail=f"Payment already {order.payment_status}."
        )
    order.payment_status = "PAID"
    db.commit()
    db.refresh(order)
    return _payment_dict(order)


@router.post("/orders/{order_id}/cod/cancel", response_model=PaymentStatusOut)
def cancel_cod(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reverse a COD payment (e.g. the order was cancelled before the rider
    collected). Flags the payment FAILED so it never shows as settled."""
    order = _get_order(db, order_id)
    if not _can_manage_payment(user, order):
        raise HTTPException(status_code=403, detail="You cannot cancel this payment.")
    if order.payment_method != "COD":
        raise HTTPException(status_code=400, detail="This order is not a COD order.")
    if order.payment_status == "PAID":
        raise HTTPException(
            status_code=400, detail="Payment already collected; use a refund flow."
        )
    order.payment_status = "FAILED"
    db.commit()
    db.refresh(order)
    return _payment_dict(order)


# ---- Razorpay (test-mode interface) ----

@router.post("/razorpay/order", response_model=PaymentIntentResponse)
def create_razorpay_intent(
    payload: RazorpayCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Razorpay-style payment intent for an order.

    In production this maps to ``razorpay.Order.create()`` and returns the
    server-side order id that the checkout SDK opens. Here we mint a
    deterministic-looking id from the order id + random hex so the frontend
    flow is identical without any external call. Marks the order as a
    pending Razorpay payment so verify() knows what to settle.
    """
    order = _get_order(db, payload.order_id)
    if not _can_manage_payment(user, order):
        raise HTTPException(status_code=403, detail="You cannot pay for this order.")
    if order.payment_status == "PAID":
        raise HTTPException(status_code=400, detail="Order already paid.")
    order.payment_method = "RAZORPAY"
    order.payment_status = "PENDING"
    db.commit()
    db.refresh(order)

    amount_paise = int(round(order.total, 2) * 100)
    razorpay_order_id = f"order_{order.id}_{secrets.token_hex(4)}"
    return {
        "order_id": order.id,
        "amount": round(order.total, 2),
        "amount_paise": amount_paise,
        "currency": "INR",
        "razorpay_order_id": razorpay_order_id,
        "key_id": RAZORPAY_KEY_ID,
        "test_mode": RAZORPAY_KEY_ID == "rzp_test_FoodAI_demo",
        "notes": {
            "order_id": order.id,
            "restaurant_id": order.restaurant_id,
            "customer_id": order.customer_id,
        },
    }


@router.post("/razorpay/verify", response_model=PaymentStatusOut)
def verify_razorpay(
    payload: RazorpayVerifyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify a Razorpay signature and settle the order.

    Real Razorpay signs ``<razorpay_order_id>|<razorpay_payment_id>`` with
    your key secret (HMAC-SHA256). We reproduce exactly that, so the same
    verification code works in production — only the secret changes. A
    mismatch raises 400 and the order stays PENDING.
    """
    order = _get_order(db, payload.order_id)
    if not _can_manage_payment(user, order):
        raise HTTPException(status_code=403, detail="You cannot verify this payment.")
    if order.payment_method != "RAZORPAY":
        raise HTTPException(status_code=400, detail="This order is not a Razorpay order.")

    expected = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment signature mismatch.")

    order.payment_status = "PAID"
    order.payment_id = payload.razorpay_payment_id
    db.commit()
    db.refresh(order)
    return _payment_dict(order)


# ---- status ----

@router.get("/orders/{order_id}", response_model=PaymentStatusOut)
def payment_status(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read a payment's state. Available to the customer, the restaurant that
    fulfilled the order, and admins — the checkout page, the restaurant
    dashboard and the admin panel all hit this one endpoint."""
    order = _get_order(db, order_id)
    if not _can_view_payment(user, order):
        raise HTTPException(status_code=403, detail="You cannot view this payment.")
    return _payment_dict(order)
```

**What it does**
- **COD, fully working:** `confirm_cod` (cash collected → `PAID`), `cancel_cod` (reversed → `FAILED`).
- **Razorpay, test-mode interface:** `create_razorpay_intent` mints a Razorpay-shaped order id; `verify_razorpay` recomputes the HMAC signature (the real Razorpay algorithm) and settles the order.
- `payment_status` is the shared read endpoint for the checkout page, restaurant dashboard and admin panel.

**Why this way**
- **Money state lives on the Order row** (columns added in Layer 1). No separate `payments` table → no joins, no sync bugs, and every existing order response can show payment state for free.
- **The signature verification is the *real* Razorpay algorithm** (`HMAC-SHA256(order_id|payment_id, key_secret)`). In production you'd only swap the key secret env var; the code path is identical. `hmac.compare_digest` is constant-time, which prevents timing attacks on the comparison.
- **`getattr(config, ...)` keeps the demo green** without polluting `config.py`; setting real env vars later just works.
- **View vs manage split**: restaurants need to *see* COD collected for their orders but should never *confirm* payments — a clear separation of duties (and a good security boundary).
- **Guards mirror the order lifecycle** — you can't confirm COD twice, can't "confirm" a Razorpay order as COD, can't pay for a paid order.

**What breaks**
- If you called Razorpay's API for real without keys → `RAZORPAY_KEY_SECRET` stays a placeholder and production would silently accept fake signatures. The `test_mode` flag exists precisely so the frontend can display the mode.
- If you accepted the signature from the client and just trusted it → anyone could mark any order PAID (the whole point of server-side verification).
- If you compared signatures with `==` instead of `compare_digest` → timing side-channel (minor for a demo, fatal for real payments).
- If you used `amount_paise = order.total * 100` without rounding → float math could produce 1999.999… paise for ₹20.00 and break the amount check.
- If COD confirm were allowed on a Razorpay order → an unpaid order would show as collected; the `payment_method` guard prevents cross-mode corruption.

**How this connects**
- Depends on the `Order` columns from Layer 1 (`payment_method`, `payment_status`, `payment_id`).
- The frontend checkout flow (Layer 4) will call: create order (COD default) → optionally `POST /payments/razorpay/order` → `POST /payments/razorpay/verify` (or `cod/confirm` after delivery).
- Registered in `main.py` under `/payments`.

---

## File 7 — `backend/routers/ml.py` (overview; deep-dive in Layer 3)

The ML router exposes the XGBoost pipeline behind small JSON endpoints. It was already wired in the codebase — Layer 2 adds one endpoint and explains the shape; Layer 3 walks the model services themselves.

**Current endpoints**
- `GET /ml/eta` — predicted delivery time (minutes) from distance + prep time + optional home point; `fallback: true` when the model file is missing.
- `POST /ml/eta/explain` — SHAP-based explanation of that prediction.
- `GET /ml/forecast` and `GET /ml/forecast/series` — per-zone demand forecast for the next N hours (admin dashboard).
- `GET /ml/recommendations` and `GET /ml/recommendations/items` — personalised restaurant / menu-item recommendations with human-readable reasons.
- `GET /ml/order/{order_id}` — per-order prediction + explanation.
- **`GET /ml/kitchen-load` (NEW)** — current simulated load per kitchen zone via `simulation.kitchen_load(hour)`.

```python
@router.get("/kitchen-load")
def get_kitchen_load(
    hour: Optional[int] = Query(None),
    user: User = Depends(security.get_current_user),
):
    """Simulated per-zone kitchen load for an hour (Poisson arrivals).

    Feeds the restaurant/admin dashboards with a realistic "how busy is each
    kitchen zone right now" number. The underlying distribution comes from
    backend.simulation.kitchen_load(); the ML forecast endpoint is separate
    and predicts demand hours ahead — this one is the current snapshot.
    """
    return simulation.kitchen_load(hour)
```

**What it does / Why this way**
- One line of route code because the heavy lifting lives in `simulation.kitchen_load` (Poisson draws) — the router is deliberately thin.
- Any authenticated user can read it (dashboard data, not order data).
- The forecast endpoints *predict*; this endpoint *measures the current simulated moment* — the two are complementary views for the admin panel.

**What breaks**
- If `kitchen_load` called `random` per zone without a seeded RNG → each request gives a totally different picture (acceptable for a demo dashboard; a real system would use a time-bucketed store).
- If the endpoint required a restaurant owner role → the admin panel (admin role) couldn't fetch it; `get_current_user` (any role) is the right breadth here.

**How this connects**
- Uses `simulation.kitchen_load` (Layer 2) and the standard `security.get_current_user` guard. Registered in `main.py` under `/ml`.

---

## File 8 — `backend/main.py`

```python
"""
FoodAI backend - FastAPI application
=====================================
Production-grade API server for FoodAI: auth (JWT), restaurant catalog,
orders + promo codes, live delivery tracking (REST + WebSocket with a
simulated rider fleet), ML ETA/forecast endpoints, and admin management.

Run:
    uvicorn backend.main:app --reload --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import config, simulation
from backend.db import Base, SessionLocal, engine
from backend import models  # noqa: F401  (register tables on Base.metadata)
from backend import seed
from backend.routers import (
    addresses,
    admin,
    auth,
    ml,
    orders,
    payments,
    restaurants,
    reviews,
    tracking,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("foodai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables + seed demo data on startup (Alembic migrations later).
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed.seed_if_empty(db)
    finally:
        db.close()
    simulation.MAIN_LOOP = asyncio.get_running_loop()
    task = None
    try:
        task = asyncio.get_running_loop().create_task(simulation.simulation_loop())
    except Exception:
        logger.exception("simulation loop failed to start; continuing without it")
    yield
    if task is not None:
        task.cancel()


app = FastAPI(
    title="FoodAI API",
    version="0.1.0",
    description=(
        "Delivery platform API: JWT auth, restaurants, orders + promos, "
        "live tracking over WebSocket, and the XGBoost ETA/forecast pipeline."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(restaurants.router)
app.include_router(orders.router)
app.include_router(tracking.router)
app.include_router(tracking.ws_router)
app.include_router(ml.router)
app.include_router(admin.router)
app.include_router(reviews.router)
app.include_router(addresses.router)
app.include_router(payments.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "foodai-backend"}
```

**What it does**
- Assembles the FastAPI app: CORS, lifespan (DB tables + seed + simulation loop), and every router mounted at its prefix. Health check at `/api/health`.

**Why this way**
- **Lifespan is the app's "startup/shutdown" hook.** It creates tables (parity with the legacy app — Alembic migrations are an alternative for stricter deployments), seeds demo data *only when empty*, stores the running event loop in `simulation.MAIN_LOOP`, and starts the background simulation task. On shutdown it cancels the task so uvicorn can exit cleanly.
- **`import models` with `# noqa` is a registration trick.** SQLAlchemy only knows about tables whose model classes have been imported; importing the module here (even though nothing else uses the name) makes `Base.metadata.create_all` see every table.
- **CORS allows the Next.js dev server + legacy Streamlit** (from `config.CORS_ORIGINS`). The demo doesn't send cookies — JWT lives in `Authorization` headers — but `allow_credentials=True` is on for forward-compat.
- **Router mount order is cosmetic** (prefixes are distinct) except that both REST and WS tracking routers are mounted.
- **Layer 2 changes:** `payments` added to imports + mounts. Also fixed a real wart: the addresses router had been registered **twice** (a leftover from a concurrent edit), which would double-register its routes — harmless-ish in FastAPI but sloppy; now it's mounted once.

**What breaks**
- If `Base.metadata.create_all` ran without importing `models` → only tables you happened to import elsewhere would exist (missing `orders`, `deliveries`, …).
- If `seed.seed_if_empty` didn't guard on empty → every restart would duplicate demo data.
- If `simulation.MAIN_LOOP` were never set → `publish_sync` silently no-ops and driver notifications / tracking events vanish (the `if MAIN_LOOP is not None` guard hides the failure — that's why startup must set it).
- If CORS origins didn't include the frontend's port → browser requests would be blocked with a CORS error even though the API works from curl.
- If the duplicate `addresses.router` had stayed → `/addresses/*` routes would be registered twice; FastAPI would serve the first, but OpenAPI docs would show duplicates.

**How this connects**
- This is the wiring hub: every router, the DB session factory (`SessionLocal`), the seed, and the simulation engine all meet here. `uvicorn backend.main:app` is the single entry point the Dockerfile runs.

---

## Layer 2 — what we did and didn't do

**Did**
- Added a fully working COD flow and a test-mode Razorpay interface (`payments.py`), wired to the new `Order` payment columns (Layer 1).
- Validated `payment_method` server-side at order creation and persisted structured address fields (phone/city/state/pincode) on create + reorder.
- Added a Poisson kitchen-load simulation (`simulation.py`) exposed as `GET /ml/kitchen-load`.
- Registered `/payments` and fixed the duplicated `addresses.router` mount in `main.py`.
- Verified: `python3 -m py_compile` passes on every changed file; `backend.main:app` imports cleanly with 63 routes registered (including the 5 new payment routes + kitchen-load).

**Didn't (deliberately, next layers)**
- Did **not** apply the new Alembic migration to a live Postgres (a concurrent "saved addresses" feature is mid-flight in the repo; we don't want to stomp its DB state). The migration file from Layer 1 is ready: `alembic upgrade head` when the time is right.
- Did **not** add the frontend checkout/payment screens — that's Layer 4.
- Did **not** deep-dive the ML services (`eta_service`, `explain_service`, `forecast_service`, `tracking`, `routing`) — that's Layer 3.

## Layer 2 exit checklist
- [x] Every changed backend file passes `py_compile`.
- [x] `backend.main:app` imports and registers `/payments/*` + `/ml/kitchen-load`.
- [x] Payment + address fields flow: schemas → orders creation → order responses.
- [x] COD endpoints guard correctly (COD-only, manage-permission, no double-pay).
- [x] Razorpay verify uses the real HMAC-SHA256 algorithm with constant-time compare.
- [x] Kitchen-load uses a Poisson draw with a two-hump hourly curve.

## What's next
- **Layer 3 — the ML services**: every line of `eta_service.py`, `explain_service.py`, `forecast_service.py`, `tracking.py`, `routing.py`, plus the full `ml.py` route walkthrough and why the models "fallback" instead of crash.
- Then **Layer 4 — the frontend**: the Next.js app, the four role dashboards, the new shadcn/ui checkout + rider navigation screens, and the glossary.
