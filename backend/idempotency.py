"""Idempotency-key helper for order creation.

The problem
-----------
A client sends ``POST /orders``. The server commits the order. The response is
lost -- a proxy timeout, a dropped mobile connection, a browser tab closed
mid-request. The client cannot tell the difference between "never arrived" and
"arrived but the reply was lost", so it retries. Without a guard that produces
two real orders, two delivery fees, and two cards charged.

The mechanism
-------------
The client sends a key it generated *before* the first attempt::

    Idempotency-Key: 7f3c1e0a-...

This module claims that key by INSERTing a row under a unique constraint. The
insert is the lock:

* **First attempt** -- the insert succeeds, the caller creates the orders, and
  the key row and the orders are committed *together*.
* **Retry, after success** -- the insert hits the unique constraint. The
  committed row names the orders, so they are returned as they are now.
* **Retry, concurrent with the first** -- the insert *blocks* on the unique
  index until the first transaction resolves, then behaves as above. No
  double order is possible even if both arrive in the same millisecond.
* **Retry, after a crash** -- the first transaction rolled back, so its key row
  vanished with it. The retry's insert succeeds and it creates the order
  normally. A crashed request never blocks a legitimate retry.

What is deliberately not here
-----------------------------
No locking, no ``SELECT ... FOR UPDATE``, no in-process cache. The unique index
does all of it, which means the guarantee survives multiple API processes
without any coordination between them. A Redis-based version of this would be
strictly worse: it would need its own durability story to avoid the same
duplicate, and Redis being down would silently disable the protection.

One nuance worth stating: the response is *re-derived* from the database on
replay rather than cached as bytes. So a retry issued twenty minutes later
returns the order's current status, not a frozen copy of the original 201
response. That is the more useful behaviour for a client re-syncing its order
list, and it also means a schema change cannot leave a stale blob behind.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.models import IdempotencyRecord, Order, OrderItem

#: Bound on the key so a client cannot use an unbounded string as an index key.
MAX_KEY_LENGTH = 255

#: How a key is labelled in the unique constraint. Part of the key's scope.
ENDPOINT_ORDERS = "POST /orders"
ENDPOINT_ORDERS_BATCH = "POST /orders/batch"


def normalize_key(raw: Optional[str]) -> Optional[str]:
    """Validate and normalize a client-supplied key.

    Returns None when the client sent nothing, which means "no replay
    protection requested" -- the endpoint then behaves exactly as it did
    before, so this is a backwards-compatible opt-in feature.
    """
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    if len(key) > MAX_KEY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Idempotency-Key must be at most {MAX_KEY_LENGTH} characters.",
        )
    return key


def request_fingerprint(payload: object) -> str:
    """Hash a request body so key reuse with a different payload is detectable.

    Sorted keys make this stable regardless of JSON key order, which matters
    because two retries of the *same* logical request may serialize differently.
    """
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stored_order_ids(record: IdempotencyRecord) -> list[int]:
    if not record.order_ids:
        return []
    try:
        return [int(oid) for oid in json.loads(record.order_ids)]
    except (TypeError, ValueError, json.JSONDecodeError):
        # Should be unreachable: we are the only writer of this column. Treat a
        # corrupt row as "nothing was created" rather than returning garbage.
        return []


def claim(
    db: Session,
    user_id: int,
    key: str,
    endpoint: str,
    payload: object,
) -> tuple[list[Order], bool]:
    """Claim ``key``, or return the orders an earlier attempt already created.

    Returns ``(orders, is_replay)``. On a replay the orders are the live rows,
    re-read from the database.

    The caller must still commit. On a fresh claim the row is only *pending*;
    it becomes visible to other processes when the caller's transaction
    commits, which is what makes the claim and the orders atomic.
    """
    fingerprint = request_fingerprint(payload)
    record = IdempotencyRecord(
        user_id=user_id,
        key=key,
        endpoint=endpoint,
        request_hash=fingerprint,
    )
    db.add(record)
    try:
        # Flush, not commit: we want the unique violation raised here, inside
        # our transaction, but we do not want to commit before the orders
        # exist -- that would leave a key claiming success for orders that do
        # not exist yet.
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(IdempotencyRecord)
            .filter(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.endpoint == endpoint,
                IdempotencyRecord.key == key,
            )
            .first()
        )
        if existing is None:
            # Extremely rare: the conflicting transaction rolled back between
            # our flush failing and this read. The key is genuinely free now.
            # Re-raising makes the client retry rather than us guessing.
            raise HTTPException(
                status_code=409,
                detail="Conflicting idempotency key. Please retry.",
            )
        if existing.request_hash != fingerprint:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This Idempotency-Key was already used with a different "
                    "request body. Use a new key for a new order."
                ),
            )
        order_ids = _stored_order_ids(existing)
        orders = _load_orders(db, order_ids)
        if not orders:
            # The key committed but names orders that are gone (deleted by an
            # admin, or a partial manual DB edit). Returning 409 is honest;
            # silently creating a new order would re-introduce the duplicate
            # this whole mechanism exists to prevent.
            raise HTTPException(
                status_code=409,
                detail=(
                    "This Idempotency-Key refers to orders that no longer "
                    "exist. Use a new key to place a new order."
                ),
            )
        return orders, True
    return [], False


def record_created(
    db: Session,
    user_id: int,
    key: str,
    endpoint: str,
    order_ids: Iterable[int],
) -> None:
    """Attach the created order IDs to the pending claim from :func:`claim`.

    The caller commits, so this and the orders land atomically.
    """
    record = (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.endpoint == endpoint,
            IdempotencyRecord.key == key,
        )
        .first()
    )
    if record is None:
        # claim() returned a fresh claim, so this cannot happen. Raising beats
        # silently committing orders with no replay guard.
        raise HTTPException(
            status_code=500,
            detail="Internal error: lost idempotency claim.",
        )
    record.order_ids = json.dumps([int(oid) for oid in order_ids])


def _load_orders(db: Session, order_ids: Sequence[int]) -> list[Order]:
    """Re-read orders by ID, preserving the original order of the list.

    Eager-loads what the replay response needs. A batch replay serializes these
    through _order_detail, which reads the customer, the restaurant and every
    line item; left lazy that was one query per relationship per order
    (measured 30 queries for 25 orders, and the line items are per-order
    collections so the count grows with the batch).
    """
    if not order_ids:
        return []
    found = {
        order.id: order
        for order in db.query(Order)
        .options(
            selectinload(Order.customer),
            selectinload(Order.restaurant),
            selectinload(Order.items).selectinload(OrderItem.menu_item),
        )
        .filter(Order.id.in_(list(order_ids)))
        .all()
    }
    return [found[oid] for oid in order_ids if oid in found]


#: How long a key is honoured. Long enough to cover any realistic client retry
#: (a mobile app that was offline overnight), short enough that the table does
#: not grow without bound. After this window the same key is treated as new,
#: which is safe: a client retrying a day later is not retrying the same
#: request, it is placing a new order.
RETENTION = timedelta(days=7)


def purge_expired(db: Session, now: Optional[datetime] = None) -> int:
    """Delete keys older than :data:`RETENTION`. Returns the number removed.

    Called from the startup path rather than on every request: the sweep is
    O(rows deleted) and there is no reason to pay for it per order. The
    ``created_at`` index exists so this is an index range scan, not a
    sequential scan of the whole table.
    """
    cutoff = (now or datetime.utcnow()) - RETENTION
    deleted = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted)
