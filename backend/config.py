"""
FoodAI backend - configuration
================================
Environment-driven settings for the FastAPI service. Every secret has a
sensible local default so the service runs out of the box against the
local PostgreSQL instance; production overrides come from environment
variables (Render/Railway set these).

The JWT secret and DB password default to dev values and MUST be overridden
in any shared deployment.
"""

import os


def _normalize_database_url(url: str) -> str:
    """Normalize hosted-DB URLs for SQLAlchemy 2.x.

    Render/Railway/Heroku expose ``postgres://...`` URLs, but SQLAlchemy 2.x
    removed the bare ``postgres`` dialect. Rewrite to the psycopg2 dialect so
    the same DATABASE_URL works locally, in Docker and in the cloud.
    """
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable (``1``/``true``/``yes``/``on``)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# Deployment environment. Anything other than "production"/"prod" is treated as
# a development environment where the local defaults below are allowed. Set
# ENVIRONMENT=production on Render/Railway so the fail-fast guards engage.
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT in ("production", "prod")


# Local development PostgreSQL (see brew install postgresql@16, DB created with
# user foodai / password foodai_pass). Override with DATABASE_URL in prod.
DATABASE_URL = _normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://foodai:foodai_pass@127.0.0.1:5432/foodai",
    )
)

_DEFAULT_JWT_SECRET = "foodai-dev-secret-change-me"
JWT_SECRET = os.getenv("JWT_SECRET", _DEFAULT_JWT_SECRET)
JWT_ALGORITHM = "HS256"

# Fail fast rather than silently signing tokens with a public default. A
# deployment that forgets JWT_SECRET must not start with a forgeable secret.
if IS_PRODUCTION and (JWT_SECRET == _DEFAULT_JWT_SECRET or len(JWT_SECRET) < 32):
    raise RuntimeError(
        "JWT_SECRET must be set to a random value of at least 32 characters "
        "when ENVIRONMENT=production."
    )
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Phone OTP verification (pre-order gate). Codes are 6 digits, expire quickly,
# and are rate-limited per phone. OTP_JWT_EXPIRE_MINUTES bounds how long a
# verified phone number can be reused to place an order.
OTP_CODE_EXPIRE_MINUTES = int(os.getenv("OTP_CODE_EXPIRE_MINUTES", "5"))
OTP_JWT_EXPIRE_MINUTES = int(os.getenv("OTP_JWT_EXPIRE_MINUTES", "15"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60"))

# When on, /auth/otp/request returns the code in the response and logs it so
# the flow is usable without an SMS provider. MUST be off in production, where
# the code is only ever sent to the phone and never echoed or logged.
OTP_DEV_MODE = _env_flag("OTP_DEV_MODE", default=not IS_PRODUCTION)

# Login throttling (fixed window, DB-backed). Per-email is tight; per-IP is
# looser so a shared NAT does not lock out legitimate users.
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_IP_MAX_ATTEMPTS = int(os.getenv("LOGIN_IP_MAX_ATTEMPTS", "20"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "300"))

# OTP verification throttling per phone, on top of the per-code attempt cap.
OTP_VERIFY_MAX_ATTEMPTS = int(os.getenv("OTP_VERIFY_MAX_ATTEMPTS", "10"))
OTP_VERIFY_WINDOW_SECONDS = int(os.getenv("OTP_VERIFY_WINDOW_SECONDS", "300"))

# Demo data seeding. Off in production so a deployed database never receives
# the known demo accounts (including the admin). Local dev and tests opt in.
SEED_DEMO_DATA = _env_flag("SEED_DEMO_DATA", default=not IS_PRODUCTION)
# Password for the seeded demo accounts. Override in any shared environment;
# seeding refuses to run in production with the default value.
DEMO_USER_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "password123")

# --- Payments (Razorpay) ----------------------------------------------
# Test mode simulates the Razorpay Checkout SDK locally and is the default
# outside production. With it off, real keys are required and the app refuses
# to start without them, so a production deploy can never fall back to the
# public demo secret.
PAYMENTS_TEST_MODE = _env_flag("PAYMENTS_TEST_MODE", default=not IS_PRODUCTION)
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

if PAYMENTS_TEST_MODE:
    # Demo credentials so the local flow works with no external account. These
    # are deliberately public and only ever used while test mode is on.
    RAZORPAY_KEY_ID = RAZORPAY_KEY_ID or "rzp_test_FoodAI_demo"
    RAZORPAY_KEY_SECRET = RAZORPAY_KEY_SECRET or "foodai_demo_secret"
elif IS_PRODUCTION and (not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET):
    raise RuntimeError(
        "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are required when "
        "PAYMENTS_TEST_MODE is off in production."
    )

# CORS origins for the dev frontend (Next.js dev server) and the legacy
# Streamlit app while it still runs during the transition.
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:8501,http://127.0.0.1:3000,http://127.0.0.1:8501",
).split(",")

# --- Simulation --------------------------------------------------------
# How often the delivery simulator advances active deliveries (seconds).
# Lower is smoother for a demo, higher uses less CPU.
SIM_INTERVAL_SECONDS = float(os.getenv("SIM_INTERVAL_SECONDS", "2.0"))
