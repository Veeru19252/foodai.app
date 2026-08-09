"""
FoodAI backend - security helpers
==================================
Password hashing (SHA-256, parity with the legacy app so seeded users keep
working), JWT access/refresh tokens, and FastAPI auth dependencies with
role-based access control for the four roles.
"""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend import config
from backend.db import get_db
from backend.models import User

# Use a single Depends-able HTTPBearer so Swagger shows the lock icon.
_bearer = HTTPBearer(auto_error=False)

ROLE_HIERARCHY = ("customer", "restaurant", "delivery", "admin")


def hash_password(password: str) -> str:
    """Return the SHA-256 hex digest (legacy-compatible demo hashing)."""
    return sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish check (demo scheme; real prod would use bcrypt)."""
    return sha256(password.encode()).hexdigest() == password_hash


def _create_token(subject: str, role: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def create_access_token(user_id: int, role: str) -> str:
    return _create_token(
        str(user_id), role, timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: int, role: str) -> str:
    return _create_token(
        str(user_id), role, timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str) -> Optional[dict]:
    """Decode + validate a JWT; return its payload or None when invalid."""
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the Bearer token (raises 401)."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise unauthorized
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise unauthorized
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise unauthorized
    return user


def require_roles(*roles: str):
    """Return a dependency that allows only the given roles."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user

    return _checker


def authorize_token_for_order(user: User, order_owner_id: int, order_restaurant_id: int) -> None:
    """Raise 403 unless the user may view an order (owner/restaurant/admin)."""
    allowed = (
        user.role == "admin"
        or user.id == order_owner_id
        or (user.role == "restaurant" and user.id == order_restaurant_id)
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot access this order.",
        )
