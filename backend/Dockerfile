# FoodAI backend — FastAPI + PostgreSQL
#
# Build from the repo root so the root-level service modules
# (eta_service.py, explain_service.py, forecast_service.py, tracking.py),
# trained models/ and backend/ all land under /app:
#
#   docker build -f backend/Dockerfile -t foodai-backend .

FROM python:3.9-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install Python dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code + trained ML models + Alembic migrations.
COPY backend/ backend/
COPY models/ models/
COPY eta_service.py explain_service.py forecast_service.py tracking.py alembic.ini ./

EXPOSE 8000

# Apply migrations, then start the API. The app seeds demo data on first boot
# and starts the delivery simulation. DATABASE_URL must be provided (e.g. via
# docker-compose or DATABASE_URL env var).
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
