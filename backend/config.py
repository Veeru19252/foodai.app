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


# Local development PostgreSQL (see brew install postgresql@16, DB created with
# user foodai / password foodai_pass). Override with DATABASE_URL in prod.
DATABASE_URL = _normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://foodai:foodai_pass@127.0.0.1:5432/foodai",
    )
)

JWT_SECRET = os.getenv("JWT_SECRET", "foodai-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# CORS origins for the dev frontend (Next.js dev server) and the legacy
# Streamlit app while it still runs during the transition.
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:8501,http://127.0.0.1:3000,http://127.0.0.1:8501",
).split(",")
