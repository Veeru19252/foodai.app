"""
FoodAI backend - restaurants router
====================================
Public catalog endpoints: restaurant list with cuisine filter, and a menu
endpoint. No authentication required for browsing (mirrors the app's browse
flow; order creation itself stays protected).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import MenuItem, Restaurant, Review
from backend.schemas import MenuItemOut

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


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
