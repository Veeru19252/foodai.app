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

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from backend import security
from backend.db import SessionLocal, get_db
from backend.models import Delivery, Order, User
from backend.simulation import manager
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
    delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
    return build_tracking_state(order, delivery)


@ws_router.websocket("/ws/tracking/{order_id}")
async def ws_tracking(websocket: WebSocket, order_id: int):
    token = websocket.query_params.get("token")
    payload = security.decode_token(token) if token else None
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
            delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
            return build_tracking_state(order, delivery)
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
