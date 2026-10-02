"""
FoodAI backend - admin router
==============================
Admin-only management: platform overview, restaurant/menu management, and
user listing. Admin is the sole allowed role here.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

import tracking

from backend import security
from backend.pagination import DEFAULT_LIMIT, count_of, set_total, validate_page
from backend.tracking_state import resolve_restaurant_coordinates
from backend.db import get_db
from backend.models import Delivery, MenuItem, Order, Restaurant, User, VALID_ORDER_STATUSES
from backend.schemas import MenuItemCreate, RestaurantCreate, UserRoleUpdate

router = APIRouter(prefix="/admin", tags=["admin"])

admin_only = security.require_roles("admin")


@router.get("/overview")
def overview(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    # Grouped counts: one query per table instead of one per role/status. The
    # admin dashboard polls this endpoint, so the old shape cost 14 round-trips
    # per poll (4 role counts + 6 status counts + 4 singles). Unknown roles and
    # statuses are ignored, matching the per-value counts this replaced.
    role_counts = {role: 0 for role in ("customer", "restaurant", "delivery", "admin")}
    for role, count in db.query(User.role, func.count(User.id)).group_by(User.role):
        if role in role_counts:
            role_counts[role] = count

    order_status = {status: 0 for status in VALID_ORDER_STATUSES}
    for status, count in db.query(Order.status, func.count(Order.id)).group_by(Order.status):
        if status in order_status:
            order_status[status] = count

    active_deliveries = (
        db.query(Delivery)
        .filter(Delivery.pickup_time.isnot(None), Delivery.delivered_time.is_(None))
        .count()
    )
    # Summed by the database, not in Python: loading every order's total just
    # to add them up made this endpoint's memory and time grow with the order
    # history. COALESCE keeps an empty table at 0.0 rather than None.
    revenue = db.query(func.coalesce(func.sum(Order.total), 0.0)).scalar()
    return {
        "users": role_counts,
        "orders_by_status": order_status,
        "total_orders": sum(order_status.values()),
        "revenue": round(revenue or 0.0, 2),
        "active_deliveries": active_deliveries,
        "restaurants": db.query(Restaurant).count(),
        "menu_items": db.query(MenuItem).count(),
    }


@router.get("/users")
def list_users(
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
    response: Response = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
):
    # The whole user table used to be returned and serialized in one response;
    # it grows with the platform, and this is the admin's first page load.
    limit, offset = validate_page(limit, offset)
    query = db.query(User).order_by(User.id)
    set_total(response, count_of(db, query))
    users = query.limit(limit).offset(offset).all()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in users]


VALID_ROLES = ("customer", "restaurant", "delivery", "admin")


@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role.")
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    target.role = payload.role
    db.commit()
    return {"id": target.id, "role": target.role}


@router.get("/orders")
def all_orders(
    user: User = Depends(admin_only),
    db: Session = Depends(get_db),
    response: Response = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
):
    # joinedload: customer and restaurant are read for every row below, and
    # leaving them lazy issued two extra SELECTs per order (401 queries for a
    # 200-order table). This endpoint is polled by the admin dashboard, so it
    # is the most visible place that scaling bites.
    limit, offset = validate_page(limit, offset)
    query = (
        db.query(Order)
        .options(joinedload(Order.customer), joinedload(Order.restaurant))
        .order_by(Order.id.desc())
    )
    set_total(response, count_of(db, query))
    orders = query.limit(limit).offset(offset).all()
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
    # restaurants.user_id is NOT NULL, so an omitted owner used to reach the
    # INSERT and surface as an IntegrityError -- a 500 for what is a bad
    # request. Requiring it up front keeps that a 400.
    if payload.user_id is None:
        raise HTTPException(
            status_code=400,
            detail="user_id is required: pick an existing restaurant-role user to own this restaurant.",
        )
    owner = db.query(User).filter(User.id == payload.user_id, User.role == "restaurant").first()
    if owner is None:
        raise HTTPException(status_code=400, detail="Owner must be an existing restaurant-role user.")
    city, point = resolve_restaurant_coordinates(payload.city, payload.lat, payload.lng)
    if point is None:
        # Without a position every delivery from this restaurant routes from the
        # demo home, which misroutes it and inflates the driver's payout. Refuse
        # the create instead of storing a restaurant we cannot place.
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide lat/lng, or a city this app knows: "
                + ", ".join(sorted(tracking.CITY_CENTERS))
                + "."
            ),
        )
    restaurant = Restaurant(
        name=payload.name,
        address=payload.address,
        cuisine=payload.cuisine,
        rating=payload.rating,
        user_id=owner.id,
        city=city,
        lat=point[0],
        lng=point[1],
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
