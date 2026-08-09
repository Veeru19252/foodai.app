"""
FoodAI backend - restaurants router
====================================
Public catalog endpoints: restaurant list with cuisine filter, and a menu
endpoint. No authentication required for browsing (mirrors the app's browse
flow; order creation itself stays protected).

Restaurant-owner endpoints (prefixed ``/restaurants/me``) power the menu
management, offer, and analytics dashboards. These are registered before the
``/{restaurant_id}`` routes so FastAPI never treats ``me`` as a restaurant id.
"""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import security
from backend.db import get_db
from backend.models import MenuItem, Order, OrderItem, PromoCode, Restaurant, Review, User
from backend.schemas import MenuItemCreate, MenuItemOut, MenuItemUpdate, OfferCreate

router = APIRouter(prefix="/restaurants", tags=["restaurants"])

restaurant_only = security.require_roles("restaurant")


def _review_summary(db: Session) -> dict:
    """One grouped query: average user rating + review count per restaurant."""
    rows = (
        db.query(
            Review.restaurant_id,
            func.avg(Review.rating),
            func.count(Review.id),
        )
        .group_by(Review.restaurant_id)
        .all()
    )
    return {
        r_id: {"reviews_rating": round(avg or 0.0, 1), "review_count": count}
        for r_id, avg, count in rows
    }


def _restaurant_payload(restaurant: Restaurant, summary: dict) -> dict:
    review = summary.get(restaurant.id, {"reviews_rating": 0.0, "review_count": 0})
    return {
        "id": restaurant.id,
        "name": restaurant.name,
        "address": restaurant.address,
        "cuisine": restaurant.cuisine,
        "rating": round(restaurant.rating or 0.0, 2),
        "reviews_rating": review["reviews_rating"],
        "review_count": review["review_count"],
    }


def _own_restaurant(user: User, db: Session) -> Restaurant:
    """Return the first restaurant owned by a restaurant-role user."""
    restaurant = (
        db.query(Restaurant).filter(Restaurant.user_id == user.id).order_by(Restaurant.id).first()
    )
    if restaurant is None:
        raise HTTPException(
            status_code=403,
            detail="You do not own a restaurant in this demo.",
        )
    return restaurant


def _offer_payload(promo: PromoCode, own_id: int) -> dict:
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
        "active": bool(promo.active),
        "scope": "restaurant" if promo.restaurant_id == own_id else "platform",
    }


@router.get("")
def list_restaurants(
    cuisine: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Restaurant)
    if cuisine and cuisine != "All":
        query = query.filter(Restaurant.cuisine == cuisine)
    if q:
        query = query.filter(
            Restaurant.name.ilike(f"%{q}%") | Restaurant.cuisine.ilike(f"%{q}%")
        )
    restaurants = query.order_by(Restaurant.rating.desc()).all()
    summary = _review_summary(db)
    return [_restaurant_payload(r, summary) for r in restaurants]


# ---- restaurant-owner dashboards (registered before /{restaurant_id} routes) ----

@router.get("/me")
def my_restaurant(
    user: User = Depends(restaurant_only),
    db: Session = Depends(get_db),
):
    restaurant = _own_restaurant(user, db)
    summary = _review_summary(db)
    return _restaurant_payload(restaurant, summary)


@router.get("/me/menu", response_model=list[MenuItemOut])
def my_menu(user: User = Depends(restaurant_only), db: Session = Depends(get_db)):
    restaurant = _own_restaurant(user, db)
    items = (
        db.query(MenuItem)
        .filter(MenuItem.restaurant_id == restaurant.id)
        .order_by(MenuItem.id)
        .all()
    )
    return [
        MenuItemOut(
            id=i.id, name=i.name, price=round(i.price, 2), prep_time_min=i.prep_time_min
        )
        for i in items
    ]


@router.post("/me/menu", status_code=201)
def add_menu_item(
    payload: MenuItemCreate,
    user: User = Depends(restaurant_only),
    db: Session = Depends(get_db),
):
    restaurant = _own_restaurant(user, db)
    item = MenuItem(
        restaurant_id=restaurant.id,
        name=payload.name,
        price=payload.price,
        prep_time_min=payload.prep_time_min,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "name": item.name, "price": round(item.price, 2)}


@router.patch("/me/menu/{item_id}")
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    user: User = Depends(restaurant_only),
    db: Session = Depends(get_db),
):
    restaurant = _own_restaurant(user, db)
    item = (
        db.query(MenuItem)
        .filter(MenuItem.id == item_id, MenuItem.restaurant_id == restaurant.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found.")
    if payload.name is not None:
        item.name = payload.name
    if payload.price is not None:
        item.price = payload.price
    if payload.prep_time_min is not None:
        item.prep_time_min = payload.prep_time_min
    db.commit()
    db.refresh(item)
    return {"id": item.id, "name": item.name, "price": round(item.price, 2)}


@router.delete("/me/menu/{item_id}")
def delete_menu_item(
    item_id: int,
    user: User = Depends(restaurant_only),
    db: Session = Depends(get_db),
):
    restaurant = _own_restaurant(user, db)
    item = (
        db.query(MenuItem)
        .filter(MenuItem.id == item_id, MenuItem.restaurant_id == restaurant.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Menu item not found.")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.get("/me/offers")
def my_offers(user: User = Depends(restaurant_only), db: Session = Depends(get_db)):
    restaurant = _own_restaurant(user, db)
    promos = (
        db.query(PromoCode)
        .filter((PromoCode.restaurant_id == restaurant.id) | (PromoCode.restaurant_id.is_(None)))
        .order_by(PromoCode.id.desc())
        .all()
    )
    return [_offer_payload(p, restaurant.id) for p in promos]


@router.post("/me/offers", status_code=201)
def create_offer(
    payload: OfferCreate,
    user: User = Depends(restaurant_only),
    db: Session = Depends(get_db),
):
    restaurant = _own_restaurant(user, db)
    if db.query(PromoCode).filter(PromoCode.code == payload.code).first() is not None:
        raise HTTPException(status_code=400, detail="That code already exists.")
    promo = PromoCode(
        code=payload.code,
        description=payload.description,
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        min_order_value=payload.min_order_value,
        max_discount=payload.max_discount,
        valid_until=payload.valid_until,
        usage_limit=payload.usage_limit,
        restaurant_id=restaurant.id,
        active=True,
    )
    db.add(promo)
    db.commit()
    db.refresh(promo)
    return _offer_payload(promo, restaurant.id)


@router.patch("/me/offers/{promo_id}/toggle")
def toggle_offer(
    promo_id: int,
    user: User = Depends(restaurant_only),
    db: Session = Depends(get_db),
):
    restaurant = _own_restaurant(user, db)
    promo = (
        db.query(PromoCode)
        .filter(PromoCode.id == promo_id, PromoCode.restaurant_id == restaurant.id)
        .first()
    )
    if promo is None:
        raise HTTPException(status_code=404, detail="Offer not found.")
    promo.active = not promo.active
    db.commit()
    return _offer_payload(promo, restaurant.id)


@router.get("/me/analytics")
def my_analytics(user: User = Depends(restaurant_only), db: Session = Depends(get_db)):
    restaurant = _own_restaurant(user, db)
    orders = (
        db.query(Order).filter(Order.restaurant_id == restaurant.id).order_by(Order.id).all()
    )
    revenue = round(sum(o.total for o in orders), 2)
    status_counts = {}
    for o in orders:
        status_counts[o.status] = status_counts.get(o.status, 0) + 1

    review_row = (
        db.query(func.avg(Review.rating), func.count(Review.id))
        .filter(Review.restaurant_id == restaurant.id)
        .first()
    )

    item_rows = (
        db.query(MenuItem.name, func.sum(OrderItem.quantity))
        .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            Order.restaurant_id == restaurant.id,
            Order.status == "DELIVERED",
        )
        .group_by(MenuItem.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
        .all()
    )

    week_ago = datetime.utcnow() - timedelta(days=7)
    last_week = (
        db.query(func.count(Order.id))
        .filter(Order.restaurant_id == restaurant.id, Order.created_at >= week_ago)
        .scalar()
        or 0
    )

    return {
        "restaurant_id": restaurant.id,
        "restaurant_name": restaurant.name,
        "total_orders": len(orders),
        "revenue": revenue,
        "orders_by_status": status_counts,
        "avg_rating": round(review_row[0], 2) if review_row and review_row[0] is not None else None,
        "review_count": review_row[1] if review_row else 0,
        "popular_items": [{"name": name, "quantity": int(qty)} for name, qty in item_rows],
        "orders_last_7_days": last_week,
    }


@router.get("/cuisines")
def list_cuisines(db: Session = Depends(get_db)):
    cuisines = sorted({c for (c,) in db.query(Restaurant.cuisine).distinct()})
    return cuisines


@router.get("/{restaurant_id}/menu", response_model=list[MenuItemOut])
def get_menu(restaurant_id: int, db: Session = Depends(get_db)):
    if db.query(Restaurant).filter(Restaurant.id == restaurant_id).first() is None:
        raise HTTPException(status_code=404, detail="Restaurant not found.")
    items = (
        db.query(MenuItem)
        .filter(MenuItem.restaurant_id == restaurant_id)
        .order_by(MenuItem.id)
        .all()
    )
    return [
        MenuItemOut(
            id=i.id, name=i.name, price=round(i.price, 2), prep_time_min=i.prep_time_min
        )
        for i in items
    ]
