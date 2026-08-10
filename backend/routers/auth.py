"""
FoodAI backend - auth router
=============================
Register, login (JWT access + refresh), token refresh, the current-user
profile endpoint, and the phone OTP verification gate used at checkout.
Password hashing matches the legacy app (SHA-256) so seeded demo accounts
keep their passwords.
"""

import logging
import re
from datetime import datetime, timedelta
from hashlib import sha256
from random import SystemRandom
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend import config, security
from backend.db import get_db
from backend.models import OtpCode, User, VALID_ROLES
from backend.schemas import (
    LoginRequest,
    OtpRequest,
    OtpRequestResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    RegisterRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger("foodai.otp")

# Indian mobile numbers: 10 digits starting with 6-9.
_PHONE_RE = re.compile(r"^[6-9]\d{9}$")

_rng = SystemRandom()

# In-memory resend cooldown (phone -> last request timestamp). Good enough for
# the single-process demo; a multi-worker deployment would use Redis.
_otp_cooldowns: dict[str, datetime] = {}


def _normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits


def _validate_phone(phone: str) -> str:
    normalized = _normalize_phone(phone)
    if not _PHONE_RE.match(normalized):
        raise HTTPException(
            status_code=400,
            detail="Enter a valid 10-digit Indian mobile number.",
        )
    return normalized


def _generate_otp() -> str:
    return f"{_rng.randrange(0, 1_000_000):06d}"


def _hash_otp(code: str) -> str:
    return sha256(code.encode()).hexdigest()


def _dev_code_log(phone: str, code: str) -> None:
    # No SMS provider in the demo: log the code for manual testing and let the
    # response carry it so the UI + tests can complete the flow end to end.
    logger.info("OTP for %s: %s", phone, code)


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "phone": user.phone,
        "phone_verified_at": user.phone_verified_at.isoformat() if user.phone_verified_at else None,
    }


def _tokens_for(user: User) -> dict:
    return {
        "access_token": security.create_access_token(user.id, user.role),
        "refresh_token": security.create_refresh_token(user.id, user.role),
        "token_type": "bearer",
        "user": _user_dict(user),
    }


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {payload.role}")
    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(
        name=payload.name.strip(),
        email=payload.email.lower().strip(),
        password_hash=security.hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _tokens_for(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if user is None or not security.verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    return _tokens_for(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(refresh_token: str, db: Session = Depends(get_db)):
    payload = security.decode_token(refresh_token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid refresh token.")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    return _tokens_for(user)


@router.get("/me")
def me(user: User = Depends(security.get_current_user)):
    return _user_dict(user)


@router.post("/otp/request", response_model=OtpRequestResponse)
def otp_request(payload: OtpRequest, db: Session = Depends(get_db)):
    """Generate a 6-digit OTP for a phone number (checked at order time).

    Rate-limited per phone (default 60s cooldown). Demo returns the code in
    the response since there is no SMS provider wired up yet.
    """
    phone = _validate_phone(payload.phone)

    now = datetime.utcnow()
    last_sent = _otp_cooldowns.get(phone)
    if last_sent is not None:
        cooldown = config.OTP_RESEND_COOLDOWN_SECONDS
        elapsed = (now - last_sent).total_seconds()
        if elapsed < cooldown:
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {int(cooldown - elapsed)}s before requesting another OTP.",
            )

    code = _generate_otp()
    _dev_code_log(phone, code)

    otp = OtpCode(
        phone=phone,
        code_hash=_hash_otp(code),
        purpose="order_verify",
        expires_at=now + timedelta(minutes=config.OTP_CODE_EXPIRE_MINUTES),
        attempts=0,
        used=False,
        created_at=now,
    )
    db.add(otp)
    db.commit()
    _otp_cooldowns[phone] = now

    return OtpRequestResponse(
        ok=True,
        expires_in=config.OTP_CODE_EXPIRE_MINUTES * 60,
        test_mode=True,
        dev_code=code,
    )


@router.post("/otp/verify", response_model=OtpVerifyResponse)
def otp_verify(
    payload: OtpVerifyRequest,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(security.get_current_user_optional),
):
    """Validate an OTP code and mint a short-lived otp_token for the phone.

    The token is what the order router checks (it must match the order's
    delivery_phone) before placing an order. When a logged-in customer
    verifies, we also stamp their profile so checkout can pre-fill next time.
    """
    phone = _validate_phone(payload.phone)
    code = payload.code.strip()

    now = datetime.utcnow()
    otp = (
        db.query(OtpCode)
        .filter(
            OtpCode.phone == phone,
            OtpCode.used.is_(False),
            OtpCode.expires_at > now,
        )
        .order_by(OtpCode.id.desc())
        .first()
    )

    if otp is None:
        raise HTTPException(
            status_code=400,
            detail="No valid OTP found. Please request a new code.",
        )

    if otp.attempts >= config.OTP_MAX_ATTEMPTS:
        otp.used = True
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Too many attempts. Please request a new code.",
        )

    if _hash_otp(code) != otp.code_hash:
        otp.attempts += 1
        db.commit()
        remaining = config.OTP_MAX_ATTEMPTS - otp.attempts
        raise HTTPException(
            status_code=400,
            detail=f"Incorrect code. {remaining} attempt(s) remaining.",
        )

    otp.used = True
    otp.attempts += 1
    db.commit()

    if user is not None and user.role == "customer":
        if user.phone != phone or user.phone_verified_at is None:
            user.phone = phone
            user.phone_verified_at = now
            db.commit()

    token = security.create_otp_token(phone)
    return OtpVerifyResponse(ok=True, otp_token=token, phone=phone, message="Phone verified.")
