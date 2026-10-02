"""
FoodAI backend - reviews router
===============================
Customers rate a restaurant after a DELIVERED order. One review per order.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from backend import security
from backend.db import get_db
from backend.pagination import DEFAULT_LIMIT, count_of, set_total, validate_page
from backend.models import Order, Review, User
from backend.schemas import ReviewCreate, ReviewOut, ReviewReplyIn

router = APIRouter(prefix="/reviews", tags=["reviews"])

customer_only = security.require_roles("customer")
restaurant_only = security.require_roles("restaurant")


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
        photo_url=payload.photo_url,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return _review_out(review)


@router.post("/{review_id}/reply", response_model=ReviewOut)
def reply_to_review(
    review_id: int,
    payload: ReviewReplyIn,
    user: User = Depends(restaurant_only),
    db: Session = Depends(get_db),
):
    """Restaurant owners answer a review left on their restaurant."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    if not any(r.id == review.restaurant_id for r in user.restaurants):
        raise HTTPException(status_code=403, detail="Not your restaurant's review.")
    review.owner_reply = payload.reply
    review.replied_at = datetime.utcnow()
    db.commit()
    db.refresh(review)
    return _review_out(review)


@router.get("/restaurant/{restaurant_id}", response_model=list)
def list_reviews(
    restaurant_id: int,
    db: Session = Depends(get_db),
    response: Response = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
):
    # _review_out reads review.user.name, which is lazy: one SELECT per review
    # (measured 101 queries for 100 reviews). Reviews are unbounded and public,
    # so the busiest restaurant is the worst case -- and this endpoint needs no
    # authentication at all.
    limit, offset = validate_page(limit, offset)
    query = (
        db.query(Review)
        .options(joinedload(Review.user))
        .filter(Review.restaurant_id == restaurant_id)
        .order_by(Review.id.desc())
    )
    set_total(response, count_of(query))
    reviews = query.limit(limit).offset(offset).all()
    return [_review_out(r) for r in reviews]


@router.get("/me", response_model=list)
def my_restaurant_reviews(
    user: User = Depends(restaurant_only),
    db: Session = Depends(get_db),
    response: Response = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
):
    """Reviews left on any restaurant owned by the logged-in owner."""
    # Validated before the early return, so a bad limit is a 422 whether or not
    # the owner happens to have restaurants yet.
    limit, offset = validate_page(limit, offset)
    restaurant_ids = [r.id for r in user.restaurants]
    if not restaurant_ids:
        set_total(response, 0)
        return []
    query = (
        db.query(Review)
        .options(joinedload(Review.user))
        .filter(Review.restaurant_id.in_(restaurant_ids))
        .order_by(Review.id.desc())
    )
    set_total(response, count_of(query))
    reviews = query.limit(limit).offset(offset).all()
    return [_review_out(r) for r in reviews]


@router.get("/restaurant/{restaurant_id}/rating")
def restaurant_rating(restaurant_id: int, db: Session = Depends(get_db)):
    # Averaged in SQL. This loads every review row to compute one mean, so its
    # cost grew with the restaurant's review history. The mean is rounded in
    # Python rather than by the database on purpose: Postgres rounds halves
    # away from zero and Python rounds half to even, so an average landing
    # exactly on a .x5 boundary would otherwise change value here.
    avg, count = (
        db.query(func.avg(Review.rating), func.count(Review.id))
        .filter(Review.restaurant_id == restaurant_id)
        .first()
    )
    if not count:
        return {"restaurant_id": restaurant_id, "rating": None, "review_count": 0}
    return {
        "restaurant_id": restaurant_id,
        "rating": round(float(avg), 1),
        "review_count": int(count),
    }


def _review_out(review: Review) -> dict:
    return {
        "id": review.id,
        "restaurant_id": review.restaurant_id,
        "user_name": review.user.name if review.user else "Customer",
        "rating": review.rating,
        "comment": review.comment,
        "photo_url": review.photo_url,
        "owner_reply": review.owner_reply,
        "replied_at": review.replied_at,
        "created_at": review.created_at,
    }
