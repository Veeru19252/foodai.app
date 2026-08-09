"""
FoodAI backend - saved addresses router
=======================================
Customers save labeled delivery addresses (Home/Work/Other) and reuse them at
checkout. Coordinates are optional — the tracking pipeline already falls back
to delivery presets in ``tracking.preset_coordinates`` when lat/lng are absent.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import security
from backend.db import get_db
from backend.models import SavedAddress, User
from backend.schemas import SavedAddressIn

router = APIRouter(prefix="/addresses", tags=["addresses"])

customer_only = security.require_roles("customer")


def _address_payload(address: SavedAddress) -> dict:
    return {
        "id": address.id,
        "label": address.label,
        "address": address.address,
        "lat": address.lat,
        "lng": address.lng,
        "created_at": address.created_at,
    }


@router.get("")
def my_addresses(
    user: User = Depends(customer_only),
    db: Session = Depends(get_db),
):
    addresses = (
        db.query(SavedAddress)
        .filter(SavedAddress.user_id == user.id)
        .order_by(SavedAddress.id.desc())
        .all()
    )
    return [_address_payload(a) for a in addresses]


@router.post("", status_code=201)
def create_address(
    payload: SavedAddressIn,
    user: User = Depends(customer_only),
    db: Session = Depends(get_db),
):
    address = SavedAddress(
        user_id=user.id,
        label=payload.label,
        address=payload.address,
        lat=payload.lat,
        lng=payload.lng,
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return _address_payload(address)


@router.delete("/{address_id}")
def delete_address(
    address_id: int,
    user: User = Depends(customer_only),
    db: Session = Depends(get_db),
):
    address = db.query(SavedAddress).filter(SavedAddress.id == address_id).first()
    if address is None:
        raise HTTPException(status_code=404, detail="Address not found.")
    if address.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your address.")
    db.delete(address)
    db.commit()
    return {"ok": True}
