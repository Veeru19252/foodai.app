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
import traceback
from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional, Set

from backend.db import SessionLocal
from backend.models import Delivery, Order, TripLog
from backend.tracking_state import rider_progress

logger = logging.getLogger("foodai.simulation")

SIM_INTERVAL_SECONDS = 2.0


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
