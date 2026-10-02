"""
FoodAI backend - tracking router
=================================
Live order tracking over REST (GET /tracking/{order_id}) and WebSocket
(WS /ws/tracking/{order_id}?token=...). Both use the same
``tracking_state.build_tracking_state`` so REST and live views always agree.

WebSocket auth: the JWT is passed as the ``token`` query parameter (browsers
cannot set headers on WebSocket upgrade). The connection is only accepted for
the order owner, the restaurant, the assigned driver, or an admin.
"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, joinedload

from backend import security
from backend.db import SessionLocal, get_db
from backend.models import Delivery, Order, User
from backend.schemas import OrderIdListRequest
from backend.simulation import manager, notifications_manager
from backend.tracking_state import build_tracking_state

router = APIRouter(prefix="/tracking", tags=["tracking"])
ws_router = APIRouter(tags=["tracking"])


def _can_access_order(user: User, order: Order, db: Session) -> bool:
    if user.role == "admin":
        return True
    if user.role == "customer":
        return order.customer_id == user.id
    if user.role == "restaurant":
        return any(r.id == order.restaurant_id for r in user.restaurants)
    if user.role == "delivery":
        return (
            db.query(Delivery)
            .filter(Delivery.order_id == order.id, Delivery.driver_id == user.id)
            .first()
            is not None
        )
    return False


def _current_delivery(db: Session, order_id: int) -> Optional[Delivery]:
    """The delivery that represents this order's current rider.

    Assignment is guarded in application code so an order gets at most one
    delivery, but nothing in the schema enforces that, so ``.first()`` here is
    whatever the planner returns and can differ between two reads of the same
    order. Taking the newest row is deterministic and matches intent.
    """
    return (
        db.query(Delivery)
        .filter(Delivery.order_id == order_id)
        .order_by(Delivery.id.desc())
        .first()
    )


def _visible_orders(
    user: User, orders: list, deliveries: dict, db: Session
) -> list:
    """Filter ``orders`` to the ones ``user`` may read, without querying per order.

    Must agree with _can_access_order exactly. The difference is where the
    driver's assignments come from: _can_access_order issues a SELECT for every
    order it is asked about, which in a loop is the per-order fan-out this batch
    endpoint exists to remove -- and the symptom is invisible if the only
    query-count test runs as an admin, since that role short-circuits first.

    ``deliveries`` maps order_id to that order's current delivery.
    """
    if user.role == "admin":
        return list(orders)
    if user.role == "customer":
        return [o for o in orders if o.customer_id == user.id]
    if user.role == "restaurant":
        owned = {r.id for r in user.restaurants}
        return [o for o in orders if o.restaurant_id in owned]
    if user.role == "delivery":
        mine = {
            order_id
            for order_id, delivery in deliveries.items()
            if delivery.driver_id == user.id
        }
        return [o for o in orders if o.id in mine]
    return []


def _load_order_or_404(order_id: int, db: Session) -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    return order


@router.get("/{order_id}")
def get_tracking(
    order_id: int,
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    order = _load_order_or_404(order_id, db)
    if not _can_access_order(user, order, db):
        raise HTTPException(status_code=403, detail="You cannot access this order.")
    return build_tracking_state(order, _current_delivery(db, order_id))


@router.post("/batch")
def batch_tracking(
    payload: OrderIdListRequest,
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    """Tracking state for many orders in one round trip.

    The customer order history fetched /tracking/{id} per row to draw its
    timeline previews, so the browser cost one request per order on every
    render. Here the orders, their restaurants, their customers and their
    deliveries all come back in four statements regardless of how many orders
    were asked for.

    Orders the caller may not see are skipped rather than 403'd -- this replaces
    a fan-out of independent requests, and one of them failing should not blank
    the timelines for the rest. restaurant and customer are joined rather than
    lazy because build_tracking_state reads both on every order.

    Authorization runs through _visible_orders rather than _can_access_order,
    because the latter queries for each order and this endpoint's whole purpose
    is not to. When an order somehow has more than one delivery row, only the
    newest is kept, matching _current_delivery.
    """
    ids = set(payload.order_ids)
    orders = (
        db.query(Order)
        .options(joinedload(Order.restaurant), joinedload(Order.customer))
        .filter(Order.id.in_(ids))
        .all()
    )
    deliveries: dict = {}
    for delivery in (
        db.query(Delivery)
        .filter(Delivery.order_id.in_(ids))
        .order_by(Delivery.id.desc())
        .all()
    ):
        # First one wins, and the rows are newest-first, so this is the newest.
        deliveries.setdefault(delivery.order_id, delivery)
    authorized = _visible_orders(user, orders, deliveries, db)
    return {
        "states": {
            order.id: build_tracking_state(order, deliveries.get(order.id))
            for order in authorized
        }
    }


@ws_router.websocket("/ws/tracking/{order_id}")
async def ws_tracking(websocket: WebSocket, order_id: int):
    token = websocket.query_params.get("token")
    payload = security.decode_access_token(token) if token else None
    if payload is None:
        await websocket.close(code=4401)
        return

    loop = asyncio.get_running_loop()

    def _build_initial_state():
        """Blocking work (DB + OSRM + ML ETA) run off the event loop."""
        db = SessionLocal()
        try:
            user_id = int(payload["sub"])
            user = db.query(User).filter(User.id == user_id).first()
            if user is None:
                return None
            order = _load_order_or_404(order_id, db)
            if not _can_access_order(user, order, db):
                return "forbidden"
            return build_tracking_state(order, _current_delivery(db, order_id))
        finally:
            db.close()

    state = await loop.run_in_executor(None, _build_initial_state)
    if state is None:
        await websocket.close(code=4401)
        return
    if state == "forbidden":
        await websocket.close(code=4403)
        return

    await websocket.accept()
    await manager.subscribe(order_id, websocket)
    await websocket.send_json({"type": "state", "data": state})
    try:
        while True:
            # Keep the socket open; clients may send ping frames.
            message = await websocket.receive_text()
            if message:
                try:
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except (json.JSONDecodeError, AttributeError):
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        await manager.unsubscribe(order_id, websocket)


@ws_router.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket):
    """Per-user notification channel (e.g. drivers receive delivery_assigned
    events). Auth via ``?token=`` like the tracking socket."""
    token = websocket.query_params.get("token")
    payload = security.decode_access_token(token) if token else None
    if payload is None:
        await websocket.close(code=4401)
        return

    loop = asyncio.get_running_loop()

    def _load_user():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == int(payload["sub"])).first()
        finally:
            db.close()

    user = await loop.run_in_executor(None, _load_user)
    if user is None:
        await websocket.close(code=4401)
        return

    channel = f"user:{user.id}"
    await websocket.accept()
    await notifications_manager.subscribe(channel, websocket)
    await websocket.send_json({"type": "connected", "channel": channel})
    try:
        while True:
            message = await websocket.receive_text()
            if message:
                try:
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except (json.JSONDecodeError, AttributeError):
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        await notifications_manager.unsubscribe(channel, websocket)
