"""
FoodAI backend - notifications router
=====================================
In-app notification center. Notifications are persisted per user and also
pushed in real time over the per-user WebSocket channel ("user:{id}").

Notification persistence lets the UI poll GET /notifications and show an
unread badge even when the socket is momentarily disconnected.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import security, simulation
from backend.db import get_db
from backend.models import Notification, User
from backend.schemas import NotificationListOut, NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


def notify(
    db: Session,
    user_id: int,
    type_: str,
    title: str,
    message: str,
    order_id: int = None,
) -> Notification:
    """Persist a notification and push it live over the user's channel."""
    notification = Notification(
        user_id=user_id,
        type=type_,
        title=title,
        message=message,
        order_id=order_id,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    simulation.publish_sync(
        simulation.notifications_manager,
        f"user:{user_id}",
        {
            "type": type_,
            "title": title,
            "message": message,
            "order_id": order_id,
        },
    )
    return notification


def _payload(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "message": n.message,
        "order_id": n.order_id,
        "read": n.read,
        "created_at": n.created_at,
    }


@router.get("", response_model=NotificationListOut)
def my_notifications(
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.id.desc())
        .limit(50)
        .all()
    )
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read.is_(False))
        .count()
    )
    return {"items": [_payload(n) for n in rows], "unread": unread}


@router.post("/read-all")
def mark_all_read(
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter(
        Notification.user_id == user.id, Notification.read.is_(False)
    ).update({Notification.read: True})
    db.commit()
    return {"ok": True}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    user: User = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id)
        .first()
    )
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found.")
    notification.read = True
    db.commit()
    return _payload(notification)
