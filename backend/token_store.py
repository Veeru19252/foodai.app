"""Refresh-token rotation with reuse detection.

Every refresh token carries a unique ``jti`` that is recorded here, which is
what makes the token revocable. The flow:

* **Issue** (login/register): mint a token, record its ``jti``.
* **Rotate** (refresh): revoke the presented token's row and issue a new one,
  so a stolen token is only good until the thief's first use.
* **Reuse detection**: presenting an already-revoked token means the token
  leaked and the real holder is still using it. The whole set for that user
  is revoked, forcing a fresh login.

Before this, refresh tokens were stateless: any captured token stayed valid
for its full 7-day lifetime no matter how often it was replayed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from backend import config, security
from backend.models import RefreshToken, User


class ReuseDetected(Exception):
    """Raised when an already-rotated refresh token is presented again."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"refresh token reuse detected for user {user_id}")


def issue(db: Session, user: User) -> tuple[str, str]:
    """Mint a refresh token and record its jti. Returns ``(token, jti)``.

    The caller is responsible for committing.
    """
    jti = uuid4().hex
    db.add(
        RefreshToken(
            user_id=user.id,
            jti=jti,
            expires_at=datetime.utcnow()
            + timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    return security.create_refresh_token(user.id, user.role, jti), jti


def rotate(db: Session, jti: str) -> RefreshToken | None:
    """Revoke the row for ``jti`` and return it, or None if unusable.

    Returns None when the token is unknown or expired (the caller rejects it).
    Raises :class:`ReuseDetected` when the token was already rotated, which
    means someone is replaying a token that leaked.
    """
    row = db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
    if row is None:
        return None
    if row.revoked:
        raise ReuseDetected(row.user_id)
    if row.expires_at < datetime.utcnow():
        return None
    row.revoked = True
    return row


def revoke_all_for_user(db: Session, user_id: int) -> int:
    """Revoke every live refresh token for a user. Returns the row count."""
    return (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
        .update({"revoked": True})
    )


def purge_expired(db: Session) -> int:
    """Delete rows for tokens that expired more than a day ago."""
    cutoff = datetime.utcnow() - timedelta(days=1)
    return db.query(RefreshToken).filter(RefreshToken.expires_at < cutoff).delete()
