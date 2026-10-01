"""
FoodAI backend - security helpers
==================================
Password hashing (Argon2id, with transparent upgrade of legacy SHA-256
hashes), JWT access/refresh tokens, and FastAPI auth dependencies with
role-based access control for the four roles.
"""

import hmac
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend import config
from backend.db import get_db
from backend.models import User

# Use a single Depends-able HTTPBearer so Swagger shows the lock icon.
_bearer = HTTPBearer(auto_error=False)

ROLE_HIERARCHY = ("customer", "restaurant", "delivery", "admin")

# Argon2id with the library's defaults (time/memory/parallelism tuned for
# interactive logins). Each digest embeds a random salt, so identical
# passwords produce different hashes and rainbow tables are useless.
_password_hasher = PasswordHasher()


def _is_legacy_sha256(password_hash: str) -> bool:
    """True for the old unsalted SHA-256 hex digests (64 hex chars)."""
    return len(password_hash) == 64 and all(
        c in "0123456789abcdef" for c in password_hash.lower()
    )


def hash_password(password: str) -> str:
    """Hash a password with Argon2id (random salt embedded in the digest)."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against an Argon2id or legacy SHA-256 hash.

    Legacy hashes are still accepted so accounts seeded before the migration
    keep working; callers should call ``needs_rehash`` and upgrade on success.
    """
    if _is_legacy_sha256(password_hash):
        return hmac.compare_digest(
            sha256(password.encode()).hexdigest(), password_hash
        )
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when a stored hash should be upgraded (legacy or stale params)."""
    if _is_legacy_sha256(password_hash):
        return True
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def _create_token(
    subject: str,
    role: str,
    expires_delta: timedelta,
    token_type: str,
    jti: Optional[str] = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        # Distinguishes access from refresh tokens so a long-lived refresh
        # token can never be replayed as a short-lived access token.
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if jti is not None:
        # Refresh tokens carry a server-recorded id, so a presented token can
        # be traced to one login and revoked when it is replayed.
        payload["jti"] = jti
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def create_access_token(user_id: int, role: str) -> str:
    return _create_token(
        str(user_id),
        role,
        timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )


def create_refresh_token(user_id: int, role: str, jti: str) -> str:
    return _create_token(
        str(user_id),
        role,
        timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS),
        "refresh",
        jti=jti,
    )


def create_otp_token(phone: str) -> str:
    """Short-lived proof that a phone number passed OTP verification.

    The token's subject is the verified phone number; the order router checks
    it matches the order's delivery phone before accepting the order.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": phone,
        "type": "otp",
        "iat": now,
        "exp": now + timedelta(minutes=config.OTP_JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_otp_token(token: str) -> Optional[str]:
    """Return the verified phone number from an OTP JWT, or None if invalid."""
    payload = decode_token(token)
    if payload is None or payload.get("type") != "otp":
        return None
    phone = payload.get("sub")
    return phone if isinstance(phone, str) and phone else None


def decode_token(token: str) -> Optional[dict]:
    """Decode + validate a JWT; return its payload or None when invalid."""
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def decode_access_token(token: str) -> Optional[dict]:
    """Decode a JWT and require it to be an access token.

    Refresh tokens carry ``type="refresh"`` and are rejected here, so a stolen
    refresh token cannot be used directly against authenticated endpoints.
    """
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        return None
    return payload


def decode_refresh_token(token: str) -> Optional[dict]:
    """Decode a JWT and require it to be a refresh token."""
    payload = decode_token(token)
    if payload is None or payload.get("type") != "refresh":
        return None
    return payload


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
    payload = decode_access_token(credentials.credentials)
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


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Resolve the user when a Bearer token is present; otherwise return None.

    Used by endpoints like OTP verification that work for guests but can
    personalize behaviour (e.g. stamping the phone) when signed in.
    """
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    return db.query(User).filter(User.id == user_id).first()


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
