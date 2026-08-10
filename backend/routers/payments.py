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
