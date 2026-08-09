"""
FoodAI backend - admin router
==============================
Admin-only management: platform overview, restaurant/menu management, and
user listing. Admin is the sole allowed role here.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import security
from backend.db import get_db
from backend.models import Delivery, MenuItem, Order, Restaurant, User, VALID_ORDER_STATUSES
from backend.schemas import MenuItemCreate, RestaurantCreate

router = APIRouter(prefix="/admin", tags=["admin"])

admin_only = security.require_roles("admin")


@router.get("/overview")
def overview(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    role_counts = {
        role: db.query(User).filter(User.role == role).count() for role in ("customer", "restaurant", "delivery", "admin")
    }
    order_status = {
        status: db.query(Order).filter(Order.status == status).count()
        for status in VALID_ORDER_STATUSES
    }
    active_deliveries = (
        db.query(Delivery)
        .filter(Delivery.pickup_time.isnot(None), Delivery.delivered_time.is_(None))
        .count()
    )
    revenue = db.query(Order).with_entities(Order.total).all()
    return {
        "users": role_counts,
        "orders_by_status": order_status,
        "total_orders": sum(order_status.values()),
        "revenue": round(sum(r[0] for r in revenue), 2),
        "active_deliveries": active_deliveries,
        "restaurants": db.query(Restaurant).count(),
        "menu_items": db.query(MenuItem).count(),
    }


@router.get("/users")
def list_users(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id).all()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in users]


@router.get("/orders")
def all_orders(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    orders = db.query(Order).order_by(Order.id.desc()).all()
    return [
        {
            "id": o.id,
            "customer_name": o.customer.name if o.customer else "",
            "restaurant_name": o.restaurant.name if o.restaurant else "",
            "status": o.status,
            "total": round(o.total, 2),
            "coupon_code": o.coupon_code,
            "created_at": o.created_at,
        }
        for o in orders
    ]


@router.post("/restaurants", status_code=201)
def create_restaurant(
    payload: RestaurantCreate,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    owner = None
    if payload.user_id is not None:
        owner = db.query(User).filter(User.id == payload.user_id, User.role == "restaurant").first()
        if owner is None:
            raise HTTPException(status_code=400, detail="Owner must be an existing restaurant-role user.")
    restaurant = Restaurant(
        name=payload.name,
        address=payload.address,
        cuisine=payload.cuisine,
        rating=payload.rating,
        user_id=owner.id if owner else None,
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return {"id": restaurant.id, "name": restaurant.name}


@router.post("/restaurants/{restaurant_id}/menu", status_code=201)
def add_menu_item(
    restaurant_id: int,
    payload: MenuItemCreate,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found.")
    item = MenuItem(
        restaurant_id=restaurant_id,
        name=payload.name,
        price=payload.price,
        prep_time_min=payload.prep_time_min,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "name": item.name, "price": round(item.price, 2)}
