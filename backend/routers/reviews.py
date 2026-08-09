"""
FoodAI backend - reviews router
===============================
Customers rate a restaurant after a DELIVERED order. One review per order.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import security
from backend.db import get_db
from backend.models import Order, Review, User
from backend.schemas import ReviewCreate, ReviewOut

router = APIRouter(prefix="/reviews", tags=["reviews"])

customer_only = security.require_roles("customer")


@router.post("", response_model=ReviewOut, status_code=201)
def create_review(
    payload: ReviewCreate,
    user: User = Depends(customer_only),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == payload.order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="You can only review your own orders.")
    if order.status != "DELIVERED":
        raise HTTPException(status_code=400, detail="You can only review delivered orders.")
    existing = db.query(Review).filter(Review.order_id == payload.order_id).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="This order has already been reviewed.")

    review = Review(
        order_id=payload.order_id,
        user_id=user.id,
        restaurant_id=order.restaurant_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return _review_out(review)


@router.get("/restaurant/{restaurant_id}", response_model=list)
def list_reviews(restaurant_id: int, db: Session = Depends(get_db)):
    reviews = (
        db.query(Review)
        .filter(Review.restaurant_id == restaurant_id)
        .order_by(Review.id.desc())
        .all()
    )
    return [_review_out(r) for r in reviews]


@router.get("/restaurant/{restaurant_id}/rating")
def restaurant_rating(restaurant_id: int, db: Session = Depends(get_db)):
    rows = db.query(Review).filter(Review.restaurant_id == restaurant_id).all()
    if not rows:
        return {"restaurant_id": restaurant_id, "rating": None, "review_count": 0}
    avg = sum(r.rating for r in rows) / len(rows)
    return {
        "restaurant_id": restaurant_id,
        "rating": round(avg, 1),
        "review_count": len(rows),
    }


def _review_out(review: Review) -> dict:
    return {
        "id": review.id,
        "restaurant_id": review.restaurant_id,
        "user_name": review.user.name if review.user else "Customer",
        "rating": review.rating,
        "comment": review.comment,
        "created_at": review.created_at,
    }
