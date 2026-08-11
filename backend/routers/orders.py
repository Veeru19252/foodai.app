"""
FoodAI backend - orders router
===============================
Customer order creation/listing, restaurant order management, driver
assignment, and promo-code validation. Prices are always taken from the
server-side menu (never from the client), and promo logic is a parity port of
database.py (validate_promo_code / calculate_discount / increment usage).
"""

from datetime import date, datetime, timezone
from typing import Optional

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
    DriverLocationUpdate,
    OrderItemOut,
    OrderOut,
    PromoApplyRequest,
    PromoApplyResponse,
    ReceiptResponse,
    SurgeResponse,
    UpdateOrderStatusRequest,
)
from backend.simulation import publish_sync
from backend.security import get_current_user
from backend.tracking_state import (
    eta_for_order,
    order_route,
    progress_at_position,
    restaurant_start,
    rider_progress,
)
from backend.routers.notifications import notify

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


def validate_promo_code(
    db: Session, code: str, order_total: float, restaurant_id: Optional[int] = None
):
    """Return (ok, message, promo_or_None), mirroring database.py semantics.

    Restaurant-scoped promos (``restaurant_id`` set) only apply to that
    restaurant; platform-wide promos (``restaurant_id`` NULL) apply anywhere.
    """
    promo = db.query(PromoCode).filter(PromoCode.code == code).first()
    if promo is None:
        return False, "Invalid promo code.", None
    if not promo.active:
        return False, "This promo code is no longer active.", None
    if (
        promo.restaurant_id is not None
        and restaurant_id is not None
        and promo.restaurant_id != restaurant_id
    ):
        return False, "This promo code is not valid for this restaurant.", None
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
        "scheduled_for": order.scheduled_for,
        "delivery_address": order.delivery_address,
        "delivery_city": order.delivery_city,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
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
        "scheduled_for": order.scheduled_for,
        "delivery_fee": round(order.delivery_fee, 2),
        "surge_multiplier": order.surge_multiplier,
        "phone_verified": order.phone_verified,
        "location_confirmed": order.location_confirmed,
        "location_confirm_lat": order.location_confirm_lat,
        "location_confirm_lng": order.location_confirm_lng,
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
    ok, message, promo = validate_promo_code(
        db, payload.code, payload.order_total, payload.restaurant_id
    )
    discount = calculate_discount(promo, payload.order_total) if promo else 0.0
    return PromoApplyResponse(ok=ok, message=message, discount=discount)


# ---- surge pricing ----

BASE_DELIVERY_FEE = 25.0
SURGE_MIN_LOAD = 180
SURGE_MAX_MULTIPLIER = 1.5


def surge_state(hour: Optional[int] = None) -> dict:
    """Delivery fee + surge multiplier from the simulated kitchen load.

    The multiplier climbs only once the platform is busy (high incoming
    order load across all kitchen zones) so riders get a higher incentive
    during peaks. Base fee ₹25; peak fee up to ₹37.5.
    """
    load = simulation.kitchen_load(hour)
    total = load["total"]
    if total <= SURGE_MIN_LOAD:
        multiplier = 1.0
    else:
        multiplier = 1.0 + min(
            (total - SURGE_MIN_LOAD) / 300.0,
            SURGE_MAX_MULTIPLIER - 1.0,
        )
    multiplier = round(multiplier, 2)
    return {
        "hour": load["hour"],
        "total_load": total,
        "surge_multiplier": multiplier,
        "delivery_fee": round(BASE_DELIVERY_FEE * multiplier, 2),
    }


@router.get("/surge", response_model=SurgeResponse)
def current_surge(
    user: User = Depends(security.get_current_user),
):
    """Current delivery-fee state so checkout can show surge before ordering."""
    return surge_state()


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
            "payment_method": order.payment_method,
            "payment_status": order.payment_status,
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


def _normalize_phone(phone: str) -> str:
    """Strip separators so a +91 / 0-prefixed number matches its OTP subject."""
    return "".join(ch for ch in phone if ch.isdigit())[-10:]


def _require_pre_order_verification(payload: CreateOrderRequest) -> None:
    """Enforce the pre-order gate: phone verified via OTP + location confirmed.

    Raises 400 unless the customer presents a valid otp_token whose subject
    matches the order's delivery phone, and explicitly confirmed the delivery
    location. Reorder endpoints deliberately skip this (repeat address/phone).
    """
    if not payload.location_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Please confirm your delivery location before ordering.",
        )

    delivery_phone = _normalize_phone(payload.delivery_phone or "")
    if not delivery_phone:
        raise HTTPException(
            status_code=400,
            detail="A delivery phone number is required. Verify it with an OTP first.",
        )

    verified_phone = security.decode_otp_token(payload.otp_token or "")
    if verified_phone is None or _normalize_phone(verified_phone) != delivery_phone:
        raise HTTPException(
            status_code=400,
            detail="Please verify your phone number with an OTP before ordering.",
        )


def _create_single_order(
    db: Session,
    user: User,
    payload: CreateOrderRequest,
    apply_delivery_fee: bool = True,
) -> Order:
    """Create one order for a restaurant group (shared by single + batch).

    ``apply_delivery_fee`` is False for every group after the first in a
    multi-restaurant cart so the customer is charged exactly the one delivery
    fee the checkout page shows (per-cart, not per-restaurant).
    """
    restaurant = db.query(Restaurant).filter(Restaurant.id == payload.restaurant_id).first()
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found.")

    _require_pre_order_verification(payload)

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
        ok, message, promo = validate_promo_code(
            db, payload.coupon_code, subtotal, payload.restaurant_id
        )
        if not ok:
            raise HTTPException(status_code=400, detail=message)
        discount = calculate_discount(promo, subtotal)

    if payload.payment_method not in VALID_PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Unsupported payment method.")

    surge = surge_state()
    scheduled_for = None
    if payload.scheduled_for is not None:
        scheduled_at = payload.scheduled_for
        if isinstance(scheduled_at, str):
            raw = scheduled_at
            if raw.endswith("Z"):
                # Python 3.9's fromisoformat rejects the 'Z' suffix; JS sends it.
                raw = raw[:-1] + "+00:00"
            scheduled_at = datetime.fromisoformat(raw)
        if scheduled_at.tzinfo is not None:
            # Normalize to naive UTC for the DB's timestamp column, then
            # compare against a naive UTC clock.
            scheduled_at = scheduled_at.astimezone(timezone.utc).replace(tzinfo=None)
        if scheduled_at < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Scheduled time must be in the future.")
        scheduled_for = scheduled_at

    delivery_fee = surge["delivery_fee"] if apply_delivery_fee else 0.0
    total = max(0.0, subtotal - discount) + delivery_fee

    order = Order(
        customer_id=user.id,
        restaurant_id=payload.restaurant_id,
        total=round(total, 2),
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
        scheduled_for=scheduled_for,
        delivery_fee=delivery_fee,
        surge_multiplier=surge["surge_multiplier"],
        status="PLACED",
        phone_verified=True,
        location_confirmed=payload.location_confirmed,
        location_confirm_lat=payload.location_confirm_lat,
        location_confirm_lng=payload.location_confirm_lng,
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
    order = _create_single_order(db, user, payload)
    if order.restaurant is not None and order.restaurant.user_id:
        notify(
            db,
            order.restaurant.user_id,
            "new_order",
            "New order received",
            f"Order #{order.id} from {user.name} — ₹{order.total:.0f}",
            order.id,
        )
    return _order_detail(order)


@router.post("/batch", response_model=BatchOrderResponse, status_code=201)
def create_orders_batch(
    payload: BatchOrderRequest,
    user: User = Depends(customer_only),
    db: Session = Depends(get_db),
):
    """Create one order per restaurant group in a single cart (Swiggy-style)."""
    orders = [
        _create_single_order(db, user, req, apply_delivery_fee=(idx == 0))
        for idx, req in enumerate(payload.orders)
    ]
    for order in orders:
        if order.restaurant is not None and order.restaurant.user_id:
            notify(
                db,
                order.restaurant.user_id,
                "new_order",
                "New order received",
                f"Order #{order.id} from {user.name} — ₹{order.total:.0f}",
                order.id,
            )
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
    # Reorders are a fresh order: re-resolve today's surge fee and default to
    # COD. Copying a RAZORPAY method would leave the reorder unpaid forever
    # (the reorder endpoint has no payment-intent flow), and skipping the fee
    # would silently give free delivery.
    surge = surge_state()
    total = round(subtotal + surge["delivery_fee"], 2)
    order = Order(
        customer_id=user.id,
        restaurant_id=source.restaurant_id,
        total=total,
        delivery_lat=source.delivery_lat,
        delivery_lng=source.delivery_lng,
        delivery_address=source.delivery_address,
        payment_method="COD",
        delivery_phone=source.delivery_phone,
        delivery_city=source.delivery_city,
        delivery_state=source.delivery_state,
        delivery_pincode=source.delivery_pincode,
        status="PLACED",
        delivery_fee=surge["delivery_fee"],
        surge_multiplier=surge["surge_multiplier"],
        # Repeat order: the customer already verified this phone + location.
        phone_verified=True,
        location_confirmed=True,
        location_confirm_lat=source.location_confirm_lat,
        location_confirm_lng=source.location_confirm_lng,
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


def _ensure_order_accessible(db: Session, user: User, order_id: int) -> Order:
    """Return the order or 404/403 unless the user may view it."""
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
    return order


@router.get("/{order_id}")
def get_order(
    order_id: int,
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    order = _ensure_order_accessible(db, user, order_id)
    return _order_detail(order)


@router.get("/{order_id}/receipt", response_model=ReceiptResponse)
def order_receipt(
    order_id: int,
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    """Itemised receipt — used by the "view / email receipt" actions."""
    order = _ensure_order_accessible(db, user, order_id)
    items = [
        OrderItemOut(name=oi.menu_item.name if oi.menu_item else "Item", quantity=oi.quantity, price=oi.price)
        for oi in order.items
    ]
    food_total = sum(item.price * item.quantity for item in items)
    return {
        "order_id": order.id,
        "restaurant_name": order.restaurant.name if order.restaurant else "",
        "customer_name": order.customer.name if order.customer else "",
        "billed_to": order.customer.email if order.customer else None,
        "items": [i.dict() for i in items],
        "food_total": round(food_total, 2),
        "discount_amount": round(order.discount_amount, 2),
        "delivery_fee": round(order.delivery_fee, 2),
        "surge_multiplier": order.surge_multiplier,
        "grand_total": round(
            max(0.0, food_total - order.discount_amount) + order.delivery_fee, 2
        ),
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "placed_at": order.created_at,
    }


@router.post("/{order_id}/receipt/email")
def email_receipt(
    order_id: int,
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    """Deliver the receipt by email. This demo writes the receipt to the log
    instead of calling a real SMTP provider; the response is what the UI
    shows as a successful email."""
    order = _ensure_order_accessible(db, user, order_id)
    recipient = order.customer.email if order.customer else user.email
    import logging
    logging.getLogger("foodai.receipts").info(
        "Receipt emailed for order %s to %s", order.id, recipient
    )
    return {"emailed": True, "to": recipient, "order_id": order.id}


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
        # The assigned driver can complete the trip (money/keys already in
        # hand); everything else stays restaurant/admin-only.
        allowed = is_restaurant_owner or is_admin
        if payload.status == "DELIVERED":
            allowed = allowed or is_assigned_driver
        if not allowed:
            raise HTTPException(status_code=403, detail="You cannot update this order.")

    order.status = payload.status
    # Starting the trip stamps pickup_time so the simulation engine advances
    # the rider along the route (mirrors the legacy driver "Start Delivery").
    if payload.status == "OUT_FOR_DELIVERY":
        delivery = db.query(Delivery).filter(Delivery.order_id == order.id).first()
        if delivery is not None and delivery.pickup_time is None:
            delivery.pickup_time = datetime.utcnow()
    db.commit()
    # Notify the customer on the big milestones.
    if payload.status in ("OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"):
        notify(
            db,
            order.customer_id,
            "order_update",
            f"Order #{order.id} {payload.status.replace('_', ' ').title()}",
            {
                "OUT_FOR_DELIVERY": "Your rider is on the way with your food.",
                "DELIVERED": "Your order has been delivered. Enjoy!",
                "CANCELLED": "Your order was cancelled.",
            }[payload.status],
            order.id,
        )
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
    # Notify the driver in real time (persisted + pushed over their channel).
    notify(
        db,
        driver.id,
        "delivery_assigned",
        "New delivery assigned",
        f"New delivery assigned for order #{order.id} from {order.restaurant.name if order.restaurant else 'Restaurant'}",
        order.id,
    )
    return {"delivery_id": delivery.id, "message": "Delivery assigned."}


@router.put("/{order_id}/driver-location")
def update_driver_location(
    order_id: int,
    payload: DriverLocationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Report the driver's live GPS position for an order in transit.

    Only the driver assigned to the order (or an admin) may report a fix.
    The position is timestamped on the order and pushed immediately to the
    order's tracking channel, so the customer's map marker follows the real
    scooter instead of the simulator.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if user.role != "admin":
        if user.role != "delivery":
            raise HTTPException(
                status_code=403,
                detail="Only the assigned driver may report a location.",
            )
        is_driver = (
            db.query(Delivery)
            .filter(Delivery.order_id == order_id, Delivery.driver_id == user.id)
            .first()
            is not None
        )
        if not is_driver:
            raise HTTPException(
                status_code=403, detail="You are not assigned to this order."
            )
    order.driver_lat = payload.lat
    order.driver_lng = payload.lng
    order.driver_updated_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    publish_sync(
        simulation.manager,
        order.id,
        {
            "type": "position",
            "order_id": order.id,
            "status": order.status,
            "lat": round(payload.lat, 6),
            "lng": round(payload.lng, 6),
            "progress": round(
                progress_at_position(order, payload.lat, payload.lng), 4
            ),
        },
    )
    return {
        "ok": True,
        "order_id": order.id,
        "driver_lat": round(payload.lat, 6),
        "driver_lng": round(payload.lng, 6),
        "updated_at": order.driver_updated_at,
    }


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

    restaurant_pos = restaurant_start(order)

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
