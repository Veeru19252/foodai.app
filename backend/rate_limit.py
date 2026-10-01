"""
FoodAI backend - rate limiting
==============================
A small fixed-window limiter backed by PostgreSQL so it survives restarts and
is shared across uvicorn workers (an in-process dict would reset on every
deploy and would not be visible to a second worker).

Usage::

    allowed, retry_after = rate_limit.hit(
        db, f"login:email:{email}", limit=5, window_seconds=300
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts.",
            headers={"Retry-After": str(retry_after)},
        )

The increment is a single ``INSERT ... ON CONFLICT DO UPDATE`` so N concurrent
attempts always produce a count of N -- there is no read-modify-write race.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.models import RateLimitCounter


def _window_start(now: datetime, window_seconds: int) -> datetime:
    """Floor ``now`` to the start of its fixed window."""
    epoch = int(now.timestamp())
    return datetime.utcfromtimestamp(epoch - (epoch % window_seconds))


def hit(
    db: Session,
    bucket: str,
    *,
    limit: int,
    window_seconds: int,
    now: Optional[datetime] = None,
) -> tuple[bool, int]:
    """Record one attempt and report whether it is within the limit.

    Returns ``(allowed, retry_after_seconds)``. ``allowed`` is False once the
    count for the current window exceeds ``limit``.
    """
    now = now or datetime.utcnow()
    window_start = _window_start(now, window_seconds)
    stmt = (
        pg_insert(RateLimitCounter)
        .values(bucket=bucket, window_start=window_start, count=1)
        .on_conflict_do_update(
            constraint="uq_rate_limit_bucket_window",
            set_={"count": RateLimitCounter.__table__.c.count + 1},
        )
        .returning(RateLimitCounter.count)
    )
    count = db.execute(stmt).scalar_one()
    db.commit()
    retry_after = window_seconds - int((now - window_start).total_seconds())
    return count <= limit, max(1, retry_after)


def reset(db: Session, bucket: str) -> None:
    """Clear a bucket (e.g. after a successful login)."""
    db.execute(delete(RateLimitCounter).where(RateLimitCounter.bucket == bucket))
    db.commit()


def purge_old(db: Session, *, older_than_seconds: int = 86400) -> int:
    """Delete windows older than ``older_than_seconds``; returns rows removed."""
    cutoff = datetime.utcnow() - timedelta(seconds=older_than_seconds)
    result = db.execute(
        delete(RateLimitCounter).where(RateLimitCounter.window_start < cutoff)
    )
    db.commit()
    return result.rowcount or 0
