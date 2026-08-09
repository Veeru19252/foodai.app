"""
FoodAI backend - database engine and session
=============================================
SQLAlchemy engine + session factory + declarative Base for PostgreSQL.
Mirrors the schema semantics of the legacy MySQL layer (database.py): same
tables, columns, and constraints so the API is drop-in equivalent.

Tables are created on startup (create_all) for local dev bootstrap; Alembic
migrations are provided under backend/alembic for managed environments.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yield a session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
