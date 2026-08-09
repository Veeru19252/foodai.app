"""
FoodAI backend - FastAPI application
=====================================
Production-grade API server for FoodAI: auth (JWT), restaurant catalog,
orders + promo codes, live delivery tracking (REST + WebSocket with a
simulated rider fleet), ML ETA/forecast endpoints, and admin management.

Run:
    uvicorn backend.main:app --reload --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import config, simulation
from backend.db import Base, SessionLocal, engine
from backend import models  # noqa: F401  (register tables on Base.metadata)
from backend import seed
from backend.routers import (
    addresses,
    admin,
    auth,
    ml,
    orders,
    restaurants,
    reviews,
    tracking,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("foodai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables + seed demo data on startup (Alembic migrations later).
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed.seed_if_empty(db)
    finally:
        db.close()
    simulation.MAIN_LOOP = asyncio.get_running_loop()
    task = None
    try:
        task = asyncio.get_running_loop().create_task(simulation.simulation_loop())
    except Exception:
        logger.exception("simulation loop failed to start; continuing without it")
    yield
    if task is not None:
        task.cancel()


app = FastAPI(
    title="FoodAI API",
    version="0.1.0",
    description=(
        "Delivery platform API: JWT auth, restaurants, orders + promos, "
        "live tracking over WebSocket, and the XGBoost ETA/forecast pipeline."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(restaurants.router)
app.include_router(orders.router)
app.include_router(tracking.router)
app.include_router(tracking.ws_router)
app.include_router(ml.router)
app.include_router(admin.router)
app.include_router(reviews.router)
app.include_router(addresses.router)
app.include_router(addresses.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "foodai-backend"}
