<div align="center">

# 🍔 FoodAI

### AI-Powered Food Delivery Platform

A Swiggy-style food delivery platform with **real-time tracking** and **machine learning** — delivery-time (ETA) prediction and zone-wise demand forecasting.

![Next.js](https://img.shields.io/badge/Frontend-Next.js_14-black) ![FastAPI](https://img.shields.io/badge/Backend-FastAPI-green) ![PostgreSQL](https://img.shields.io/badge/DB-PostgreSQL_16-336791) ![XGBoost](https://img.shields.io/badge/ML-XGBoost-orange) ![Python](https://img.shields.io/badge/Python-3.9-blue) ![License](https://img.shields.io/badge/License-MIT-yellow)

**Status:** ✅ Complete · **Stack:** Next.js 14 + FastAPI + PostgreSQL 16 + XGBoost

</div>

---

## 📑 Table of Contents

- [Features](#-features)
- [Screenshots](#-screenshots)
- [Tech Stack](#-tech-stack)
- [Architecture](#-architecture)
- [Quickstart](#-quickstart)
- [Demo Accounts](#-demo-accounts)
- [Project Structure](#-project-structure)
- [API Reference](#-api-reference)
- [ML Models](#-ml-models)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Documentation](#-documentation)
- [Roadmap](#-roadmap)
- [Future Improvements](#-future-improvements)
- [Security Notes](#-security-notes)
- [Contributing](#-contributing)
- [License](#-license)
- [Authors](#-authors)

---

## ✨ Features

### 🖥️ Platform — 4 roles
- **Customer** — signup/login, browse restaurants, multi-restaurant cart, promo codes, checkout with address + phone OTP, live order tracking
- **Restaurant** — order inbox with accept/reject, menu management (CRUD), offers, review replies, per-restaurant analytics
- **Delivery Partner** — real-time assignment notifications, start/complete delivery, earnings dashboard, **live GPS sharing** from the device
- **Admin** — revenue/order metric cards, charts, demand-forecast panel, user management (role changes), one-click **model retraining**

### ⚡ Ordering & fulfilment
- **Full order flow** — browse → menu → cart → checkout → `PLACED → CONFIRMED → PREPARING → OUT_FOR_DELIVERY → DELIVERED`
- **Multi-restaurant batch orders** — one checkout, one delivery fee, orders split per restaurant
- **Promo codes** — `WELCOME10` (10%, min ₹100, cap ₹50) · `FLAT50` (₹50, min ₹200) · `FOODIE20` (20%, min ₹300, cap ₹150) — validated server-side and stored on the order
- **Payments** — Cash on Delivery (fully working; only the assigned driver or an admin marks cash collected, and only after `DELIVERED`) and a Razorpay test-mode interface implementing the real HMAC-SHA256 signature check
- **Phone OTP + delivery-location confirmation** gate before an order is accepted
- **Per-restaurant delivery fee**, computed from distance
- **Saved addresses**, order history and one-tap **re-order**
- **Reviews & ratings** with restaurant replies
- **Order scheduling** for later delivery
- **Live tracking** — Leaflet map, WebSocket push with REST-polling fallback, auto-reconnect
- **In-app notifications** — notification bell + per-user WebSocket channel
- **PWA** — installable, offline shell via service worker

### 🧠 AI / ML
- **ETA prediction (XGBoost)** — predicts delivery time in minutes from distance, prep time, hour, weekday, zone, traffic
- **Demand forecasting (XGBoost)** — predicts orders per zone for the next 6 hours; drives the admin demand panel and driver pre-positioning
- **Explainable AI (SHAP)** — the tracking page shows *"Why this ETA?"* with signed per-feature minute contributions
- **Personalized recommendations** — a "Recommended for you" row scored from order history (cuisine affinity, rating, familiarity, review volume) with a human-readable reason
- **Rigorous evaluation** — every model is compared against a baseline (MAE / RMSE / MAPE) on a held-out test set
- **Graceful degradation** — ML endpoints return `"fallback": true` instead of erroring when a model file is missing, so the app always works

---

## 📸 Screenshots

| Restaurant listing | Menu | Checkout |
|---|---|---|
| ![Restaurant listing](docs/screenshots/03-restaurant-listing.png) | ![Menu](docs/screenshots/04-menu.png) | ![Checkout](docs/screenshots/05-checkout.png) |

| Live tracking | "Why this ETA?" (SHAP) | Admin dashboard |
|---|---|---|
| ![Live tracking](docs/screenshots/06-live-tracking.png) | ![SHAP explainability](docs/screenshots/07-live-tracking-shap.png) | ![Admin dashboard](docs/screenshots/11-admin-dashboard.png) |

| Restaurant dashboard | Driver console | Restaurant analytics |
|---|---|---|
| ![Restaurant dashboard](docs/screenshots/08-restaurant-orders.png) | ![Driver console](docs/screenshots/10-driver-console.png) | ![Restaurant analytics](docs/screenshots/09-restaurant-analytics.png) |

> Regenerate them any time with `cd frontend && npx playwright test e2e/screenshots.spec.ts` (backend + frontend must be running).

---

## 🧱 Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | **Next.js 14** (App Router, React 18, TypeScript, Tailwind) | Real client/server app: routing, protected routes, PWA |
| Maps | **Leaflet + react-leaflet** via dynamic import | Free interactive map, no API key |
| Real-time | **WebSocket** + REST polling fallback | True push with graceful degradation |
| Backend | **FastAPI** (uvicorn) | Async, typed, auto OpenAPI docs at `/docs` |
| Auth | **JWT** (access + rotating refresh, PyJWT) + **Argon2id** | Role-scoped, revocable sessions |
| ORM / migrations | **SQLAlchemy 2.0** + **Alembic** | Typed models, versioned schema |
| Database | **PostgreSQL 16** | Real relational DB with FK constraints |
| ML | **XGBoost** · scikit-learn · pandas | Gradient boosting for ETA + demand |
| Explainability | **SHAP** TreeExplainer | Per-feature ETA contributions |
| Charts | **Recharts** (frontend) · matplotlib (offline) | Dashboards + saved evaluation plots |
| Payments | **Razorpay** test-mode + COD | Test-mode signature verification, working COD |
| Testing | **pytest** · **Playwright** · GitHub Actions | 84 backend tests + 4 e2e flows in CI |
| Deploy | **Render** (Blueprint) · Docker Compose | One-click full-stack deploy |

---

## 🏗️ Architecture

```
┌──────────────┐   REST + WebSocket   ┌───────────────┐   SQLAlchemy   ┌──────────────┐
│  Next.js 14  │─────────────────────▶│    FastAPI    │───────────────▶│  PostgreSQL  │
│  (React/TS)  │◀─────────────────────│   (uvicorn)   │                │     16       │
└──────────────┘   JSON + WS events   └───────┬───────┘                └──────────────┘
        │                                     │
        │ JWT in, role-scoped          ┌──────▼───────┐
        │ requests                     │  ML services │  eta_model.joblib
        ▼                              │  (XGBoost +  │  forecast_model.joblib
  ProtectedRoute                       │   SHAP)      │
                                       └──────────────┘
```

**Where the ML lives.** `eta_service.py`, `forecast_service.py` and `explain_service.py` sit at the repo root and are imported by the FastAPI routers — the trained XGBoost models are shared between the API and the offline training scripts, so the model that serves predictions is exactly the one `scripts/train_*.py` produces.

**Data flow for one order**

1. Customer places an order → validated and written to PostgreSQL (items, fees, promo, address, payment method)
2. Restaurant accepts → status moves to `CONFIRMED`, then `PREPARING`
3. An admin or the auto-dispatch logic assigns a delivery partner
4. The tracking service computes features for the order (distance, prep time, hour, zone, traffic) and asks the ETA model for a prediction
5. SHAP explains the prediction; the tracking page renders the map, the ETA and the *"Why this ETA?"* panel
6. The delivery simulation advances the rider every `SIM_INTERVAL_SECONDS` (default 2s) and pushes the new position over the WebSocket
7. On `DELIVERED`, the driver (or an admin) collects the COD payment

---

## 🚀 Quickstart

### Option A — local development

**Prerequisites:** Python 3.9+, Node 20+, PostgreSQL 16 running locally.

```bash
# 0. Create the role and database (once, needs a Postgres superuser login).
#    Keep the password as foodai_pass so it matches the DATABASE_URL default.
psql -d postgres -c "CREATE ROLE foodai LOGIN PASSWORD 'foodai_pass'" 2>/dev/null \
  || echo "role 'foodai' already exists — reusing it"
psql -d postgres -c "CREATE DATABASE foodai OWNER foodai" 2>/dev/null \
  || echo "database 'foodai' already exists — reusing it"

# 1. Backend dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Optional: copy the env template and load it
cp .env.example .env
set -a && source .env && set -a

# 3. Backend (creates the schema and seeds demo data on first boot)
uvicorn backend.main:app --reload --port 8000
#    → API docs at http://localhost:8000/docs

# 4. Frontend (separate terminal)
cd frontend && npm install && npm run dev
#    → app at http://localhost:3000
```

The database connection defaults to
`postgresql+psycopg2://foodai:foodai_pass@127.0.0.1:5432/foodai`; override it
with the `DATABASE_URL` environment variable. Demo data is seeded automatically
when the database is empty.

> **The backend does not read `.env` itself** — there is no `python-dotenv`
> dependency, so step 2 uses `set -a && source .env` to export the variables
> into the environment. Render injects the same variables automatically. Every
> setting is listed with its default in [`.env.example`](./.env.example).

### Option B — Docker Compose

```bash
docker compose up --build
# → frontend http://localhost:3000 · backend http://localhost:8000/docs · Postgres :5432
```

Brings up PostgreSQL 16 + FastAPI (runs Alembic migrations) + Next.js with no
local setup.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://foodai:foodai_pass@127.0.0.1:5432/foodai` | SQLAlchemy connection string (`postgres://` is auto-rewritten for Render/Railway) |
| `JWT_SECRET` | `foodai-dev-secret-change-me` | **Must be overridden in any shared deployment** |
| `CORS_ORIGINS` | `localhost:3000`, `8501` | Comma-separated allowed origins |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access-token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh-token lifetime |
| `SIM_INTERVAL_SECONDS` | `2` | Delivery-simulation tick (set `1.0` to speed up e2e) |
| `OTP_CODE_EXPIRE_MINUTES` | `5` | Phone OTP lifetime |
| `OTP_MAX_ATTEMPTS` / `OTP_RESEND_COOLDOWN_SECONDS` | `5` / `60` | OTP rate limiting |
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | Backend URL baked into the frontend build |

Every setting is listed with its default in [`.env.example`](./.env.example).

---

## 🔑 Demo Accounts

All demo accounts use the password **`password123`**.

| Role | Email | Lands on |
|---|---|---|
| Customer | `customer@foodai.com` | `/restaurants` |
| Restaurant (Spice Garden) | `spice@foodai.com` | `/restaurant/orders` |
| Restaurant (Dosa Plaza) | `dosa@foodai.com` | `/restaurant/orders` |
| Delivery partner | `rider@foodai.com`, `priya@foodai.com` | `/driver` |
| Admin | `admin@foodai.com` | `/admin` |

> The OTP step auto-fills the code in demo mode, so the checkout flow can be
> completed without a phone.

**Suggested demo path:** log in as the customer → order from *Spice Garden* and
*Dosa Plaza* (multi-restaurant cart) → apply `WELCOME10` at checkout → watch the
rider move live on the map → open *"Why this ETA?"* to see the SHAP breakdown →
log in as the driver and share live GPS → log in as the admin to see the
demand forecast and retrain the model.

---

## 📂 Project Structure

```
foodai.app/
├── backend/                  # ── FastAPI service (the live backend) ──
│   ├── main.py               # App factory, CORS, lifespan (migrate + seed)
│   ├── config.py             # Env-driven settings (DB, JWT, OTP, CORS)
│   ├── db.py                 # SQLAlchemy engine, session, Base
│   ├── models.py             # ORM models (User, Order, Restaurant, …)
│   ├── schemas.py            # Pydantic request/response schemas
│   ├── security.py           # Password hashing + JWT issue/verify
│   ├── seed.py               # Demo data seeding
│   ├── simulation.py         # Delivery simulation loop
│   ├── tracking_state.py     # In-memory rider positions
│   ├── ml_train.py           # Live retraining (admin endpoint)
│   ├── Dockerfile
│   ├── alembic/              # Versioned migrations
│   └── routers/              # auth · restaurants · orders · payments
│                              # tracking · reviews · admin · ml · addresses
│                              # notifications
├── frontend/                 # ── Next.js 14 app ──
│   ├── src/app/              # 14 routes (restaurants, checkout, tracking, …)
│   ├── src/components/       # Map, modals, gates, nav, UI primitives
│   ├── src/lib/              # api client, auth/cart/location contexts
│   ├── e2e/                  # Playwright specs (+ screenshot capture)
│   ├── Dockerfile
│   └── playwright.config.ts
├── eta_service.py            # ── ML services, shared by API + scripts ──
├── forecast_service.py
├── explain_service.py
├── tracking.py               # Tracking maths
├── routing.py                # Haversine distance / zone logic
├── scripts/
│   ├── train_eta.py          # Retrain ETA model + evaluation charts
│   ├── train_forecast.py     # Retrain demand model + evaluation charts
│   └── simulate_orders.py    # Generate synthetic order history
├── models/                   # eta_model.joblib · forecast_model.joblib
│                             # forecast_meta.json
├── outputs/                  # metrics_*.json + charts/*.png
├── data/orders.csv           # Synthetic order history
├── notebooks/                # ML learning notebooks
├── tests/                    # pytest suite (84 tests)
├── teaching/                 # Layer-by-layer teaching docs (see below)
├── docs/screenshots/         # README screenshots (generated)
├── docker-compose.yml
├── render.yaml               # Render Blueprint
├── alembic.ini
├── DEPLOY.md                 # Deploy checklist
├── REPORT.md / report_2.md   # Full codebase reports
└── README.md
```

---

## 📡 API Reference

Interactive docs: `http://localhost:8000/docs`.

> **Path prefix:** every route is served from the root (e.g. `/auth/login`),
> *except* the health check, which is `/api/health`. The tables below keep the
> `/api` prefix for readability — drop it when calling.

### Auth
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/auth/register` | Create an account. Self-registration is limited to `customer` / `restaurant` / `delivery`; `admin` is rejected with `403` |
| `POST` | `/api/auth/login` | Returns access + refresh tokens |
| `POST` | `/api/auth/refresh` | Exchange a refresh token. Rotates it; presenting a rotated token revokes every live token for that user (`401`) |
| `GET` | `/api/auth/me` | The currently authenticated user |
| `POST` | `/api/auth/otp/request` · `/verify` | Phone OTP for the pre-order gate |

### Restaurants & menu
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/restaurants` | List restaurants (city / cuisine / rating filters) |
| `GET` | `/api/restaurants/{id}/menu` | Menu items for one restaurant |
| `GET` | `/api/restaurants/cuisines` · `/api/restaurants/cities` | Filter option lists |
| `GET`/`POST`/`PATCH`/`DELETE` | `/api/restaurants/me/menu…` | The logged-in restaurant's own menu (CRUD) |
| `GET`/`POST`/`PATCH` | `/api/restaurants/me/offers…` | The restaurant's promo offers, incl. enable/disable |

### Orders
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/orders` | Single order |
| `POST` | `/api/orders/batch` | Multi-restaurant order |
| `GET` | `/api/orders` | Role-scoped order list |
| `GET` | `/api/orders/{id}` | One order with items, fees and payment state |
| `GET` | `/api/orders/driver` · `/api/orders/restaurant` | Role-specific order views |
| `GET` | `/api/orders/driver/earnings` | Driver earnings summary |
| `GET` | `/api/orders/drivers` | Available delivery partners (for assignment) |
| `GET` | `/api/orders/surge` | Current surge multiplier state |
| `GET` | `/api/orders/{id}/receipt` | Printable receipt |
| `POST` | `/api/orders/{id}/receipt/email` | Email the receipt |
| `POST` | `/api/orders/{id}/reorder` | One-tap re-order from history |
| `POST` | `/api/orders/promo/validate` | Validate a promo code before checkout |
| `POST` | `/api/orders/{id}/auto-assign` | Smart auto-dispatch to the best driver |
| `PATCH` | `/api/orders/{id}/status` | Advance the order lifecycle |
| `POST` | `/api/orders/{id}/assign` | Assign a delivery partner |
| `POST` | `/api/orders/{id}/cancel` | Cancel (guarded by status + role) |
| `POST` | `/api/reviews` · `GET` `/api/reviews/restaurant/{id}` | Reviews & ratings |
| `GET` | `/api/reviews/restaurant/{id}/rating` | Aggregate rating summary |
| `POST` | `/api/reviews/{id}/reply` | Restaurant replies to a review |

### Payments
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/payments/orders/{id}/cod/confirm` | Driver/admin collects cash (only after `DELIVERED`) |
| `POST` | `/api/payments/orders/{id}/cod/cancel` | Reverse an uncollected COD order |
| `POST` | `/api/payments/razorpay/order` · `/verify` | Razorpay test-mode intent + HMAC verification |
| `GET` | `/api/payments/orders/{id}` | Payment state for an order |

### Tracking
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/tracking/{id}` | Current rider position + ETA (REST poll) |
| `PUT` | `/api/orders/{id}/driver-location` | Driver shares live GPS |
| `WS` | `/api/ws/tracking/{id}` | Live position + status pushes |
| `WS` | `/api/ws/notifications` | Per-user notifications |

### ML
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/ml/eta` | Predict delivery minutes; `source` is `ml` or `formula`, `fallback` is `true` when the model is missing or worse than the formula |
| `POST` | `/api/ml/eta/explain` | SHAP contributions for a prediction (`explanation: null` + `fallback: true` when the explainer is unavailable) |
| `GET` | `/api/ml/order/{id}` | Per-order features + prediction + explanation |
| `GET` | `/api/ml/forecast` · `/api/ml/forecast/series` | Zone demand forecast (next 6 hours) |
| `GET` | `/api/ml/recommendations` | Personalized restaurant recommendations |
| `GET` | `/api/ml/recommendations/items` | Item-level recommendations |
| `GET` | `/api/ml/kitchen-load` | Predicted kitchen load per restaurant |

### Admin
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/admin/overview` · `/users` · `/orders` | Dashboard data |
| `PATCH` | `/api/admin/users/{id}/role` | Change a user's role |
| `POST` | `/api/admin/restaurants` | Create a restaurant (admin) |
| `POST` | `/api/admin/restaurants/{id}/menu` | Add a menu item to any restaurant (admin) |
| `POST` | `/api/ml/forecast/retrain` | Retrain models, return a metrics summary |

---

## 🤖 ML Models

### Model 1 — ETA prediction (regression)

| Field | Value |
|---|---|
| Algorithm | XGBoost (`XGBRegressor`) |
| Target | Delivery time in minutes |
| Features | distance_km, prep_time_min, hour_of_day, day_of_week, zone (one-hot), is_weekend, traffic_factor |
| Compared against | Distance-based baseline, Linear Regression, Random Forest |
| Artifact | `models/eta_model.joblib` |

| Model | MAE (min) | RMSE |
|---|---|---|
| Baseline (distance ÷ 20 km/h) | 2.84 | 3.63 |
| Linear Regression | 1.93 | 2.47 |
| Random Forest | 1.65 | 2.00 |
| **XGBoost** (deployed) | **2.03** | **2.61** |

*XGBoost beats the baseline by ~28% MAE. Random Forest scores slightly better on this
small synthetic dataset; it is reported honestly rather than hidden, and XGBoost is
deployed because it exposes feature importances cleanly and shares one codebase with
the demand model.*

Retrain: `.venv/bin/python scripts/train_eta.py`

### Model 2 — Demand forecasting

| Field | Value |
|---|---|
| Algorithm | XGBoost on lag features |
| Target | Orders per zone per hour |
| Features | hour, weekday, rolling 1h / 3h averages |
| Baseline | Moving average |
| Artifacts | `models/forecast_model.joblib`, `models/forecast_meta.json` |

| Model | RMSE (orders/hr/zone) | MAPE |
|---|---|---|
| Moving average | 0.76 | 40.4% |
| **XGBoost** | **0.66** | **32.9%** |

*XGBoost beats the moving-average baseline by ~18% lower MAPE.*

Retrain: `.venv/bin/python scripts/train_forecast.py`

Evaluation charts and the raw metrics JSON live in
[`outputs/`](./outputs/charts) — `eta_actual_vs_predicted.png`,
`eta_feature_importance.png`, `eta_metrics_comparison.png`,
`forecast_zone_demand.png`, and the equivalents for the forecast model.

### Dataset

Synthetic order history generated by `scripts/simulate_orders.py` and committed
as `data/orders.csv`. Real delivery data isn't public, so it is simulated to
control data quality and keep the pipeline reproducible; this limitation is
documented in the report rather than hidden.

---

## 🧪 Testing

```bash
# Backend — 84 tests (API integration + unit)
.venv/bin/python -m pytest -q

# Frontend — production build (14 routes)
cd frontend && npm run build

# E2E — 4 Playwright flows (needs backend :8000 + frontend :3000 running)
cd frontend && npx playwright test

# Documentation screenshots (regenerates docs/screenshots/)
cd frontend && npx playwright test e2e/screenshots.spec.ts
```

| Suite | Coverage |
|---|---|
| `tests/test_api_e2e.py` | Auth, restaurants, orders, batch orders, promos, receipts, admin, ML endpoints |
| `tests/test_helpers_unit.py` | Tracking maths, routing/Haversine, ML feature builders |
| `tests/test_payments_smoke.py` | COD lifecycle, Razorpay test-mode signature verification |
| `frontend/e2e/*.spec.ts` | Customer order journey, driver flow, restaurant + admin roles, auth failure |

**CI** — `.github/workflows/ci.yml` runs the backend tests (against a Postgres 16
service), the frontend build, and the full Playwright suite on every push and PR
to `main`.

---

## 🚀 Deployment

### Render (one-click, current)

[`render.yaml`](./render.yaml) is a Render Blueprint that provisions the whole
stack — PostgreSQL 16 + FastAPI + Next.js:

1. Push this repo to GitHub (`main`).
2. Render → **New** → **Blueprint** → connect the repo.
3. Render reads `render.yaml`, provisions `foodai-db`, `foodai-backend` and
   `foodai-frontend`, and auto-deploys on every push.

| Service | URL |
|---|---|
| Frontend | `https://foodai-frontend.onrender.com` |
| Backend API docs | `https://foodai-backend.onrender.com/docs` |
| Backend health | `https://foodai-backend.onrender.com/api/health` |

The backend runs `alembic upgrade head` on every deploy and seeds demo accounts
on first boot. The migration chain has been verified against an empty database:
it produces all 12 tables with no column drift versus the ORM models. If Render
assigns different service URLs, update `NEXT_PUBLIC_API_URL` (frontend) and
`CORS_ORIGINS` (backend) to match.

> **Free-tier caveats:** web services spin down after ~15 min idle (the first
> request takes a few seconds to wake), and free Postgres data expires after
> 30 days — upgrade the database plan for a persistent demo.

> **TODO (before submission):** once deployed, paste the live frontend URL into
> the *Demo* section below and in `DEPLOY.md`.

Full pre-deploy validation, post-deploy verification and rollback steps:
[`DEPLOY.md`](./DEPLOY.md).

---

## 📚 Documentation

| Document | What it is |
|---|---|
| [`REPORT.md`](./REPORT.md) | Beginner-friendly walkthrough of the whole codebase, every term defined |
| [`report_2.md`](./report_2.md) | Deeper report: architecture decisions, data model, trade-offs |
| [`teaching/01_database_layer.md`](./teaching/01_database_layer.md) | The PostgreSQL schema, table by table, with the reasoning |
| [`teaching/02_backend_layer.md`](./teaching/02_backend_layer.md) | Every FastAPI router, endpoint by endpoint |
| [`teaching/03_ml_layer.md`](./teaching/03_ml_layer.md) | The ML pipeline, feature engineering, evaluation, SHAP |
| [`teaching/04_frontend_layer.md`](./teaching/04_frontend_layer.md) | The Next.js app, routing, state, components |
| [`teaching/05_glossary.md`](./teaching/05_glossary.md) | Every technical term in one place |
| [`DEPLOY.md`](./DEPLOY.md) | Deploy checklist, verification, rollback |

> **A note on the two versions.** The root-level `app.py`, `database.py`,
> `maps.py`, `ui/`, `seed_data.py`, `.streamlit/` and `setup.sh` are the
> **original Streamlit prototype**, kept as a record of the first iteration.
> They are *not* part of the running system — the live app is `backend/` +
> `frontend/`, and neither the deploy nor the CI path ever touches them.
>
> The exception, and it matters: `eta_service.py`, `forecast_service.py`,
> `explain_service.py`, `tracking.py` and `routing.py` are **shared live
> modules** that the FastAPI routers import. Don't delete them thinking they
> belong to the prototype — doing so breaks the ML endpoints and tracking.

---

## 🎥 Demo

- 🔗 **Live demo URL:** *TODO — paste the Render URL after deploying*
- 📹 **Demo video:** *TODO — record a 3–5 minute walkthrough (customer order → live tracking → SHAP → admin dashboard)*

---

## 🗓️ Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| Learning | Python, pandas, ML fundamentals, Streamlit prototype | ✅ |
| Platform core | Auth, restaurants, cart, checkout, order lifecycle | ✅ |
| Live tracking | Map + simulated rider GPS | ✅ |
| ML #1 | XGBoost ETA model beating the baseline | ✅ |
| ML #2 | Zone demand forecasting + comparison table | ✅ |
| Admin + deploy | Admin dashboard, signup, driver GPS, model retrain, Render deploy | ✅ |
| Re-platform 1 | FastAPI + PostgreSQL backend (JWT, orders, WebSocket tracking, ML endpoints) | ✅ |
| Re-platform 2 | Next.js frontend (auth, multi-restaurant cart, checkout, live tracking) | ✅ |
| Re-platform 3 | Batch orders, cancellations, reviews, real-time driver notifications | ✅ |
| Re-platform 4 | AI differentiators: SHAP explainability, demand panel, recommendations | ✅ |
| Re-platform 5 | CI (GitHub Actions), Docker Compose, documentation | ✅ |
| Submission | Demo video + live URL | ☐ |

---

## 🔒 Security Notes

What the auth layer does, and the deliberate demo shortcuts — so the trade-offs
are visible rather than implied.

**Implemented**
- **JWT access + refresh tokens**, with the decode algorithm pinned to
  `HS256` (never taken from the token itself) and `exp` enforced on every read.
  Tokens carry a `type` claim, so a refresh token can never be replayed as an
  access token.
- **Refresh-token rotation with reuse detection.** Each refresh token is
  recorded server-side by its `jti` and is good for exactly one use. Presenting
  an already-rotated token means it leaked, so every live token for that user
  is revoked and a fresh login is required. The client serialises concurrent
  refreshes so parallel `401`s do not look like a replay.
- **Argon2id password hashing** (per-password salt), with transparent upgrade
  of legacy unsalted SHA-256 hashes on successful login.
- **Role-scoped authorization.** Admin-only routes depend on
  `security.require_roles("admin")` (bound to `admin_only` in the router), not
  on the client hiding links.
- **Self-registration is restricted to `customer` / `restaurant` / `delivery`.**
  The register endpoint is unauthenticated, so trusting a caller-supplied `role`
  would let anyone mint an admin; requesting `admin` returns `403`. Admins are
  created only by seeding or by an authenticated admin promoting a user via
  `PATCH /api/admin/users/{id}/role`. Covered by
  `test_register_cannot_escalate_to_admin`.
- **OTP rate limiting** — per-phone attempt cap and resend cooldown on the
  pre-order verification gate.
- **Razorpay signature verification** using the real HMAC-SHA256
  `order_id|payment_id` algorithm, compared with `hmac.compare_digest`
  (constant-time, so it resists timing attacks).
- **SQL injection** — every query goes through SQLAlchemy's parameter binding;
  no string-built SQL.

**Known demo shortcuts** (acceptable for a submitted demo, each a real
limitation rather than an oversight)
- **Passwords are hashed with unsalted SHA-256.** It is fast and unkeyed, so
  the hashes are rainbow-table reversible. Real deployments need `bcrypt` or
  `argon2`; the demo passwords are published in this README anyway. The scheme
  was kept identical to the legacy prototype so the seeded users keep working.
- **No rate limiting on `POST /auth/login`.** The OTP flow is rate-limited, but
  password login has no attempt counter or lockout, so it is brute-forceable.
- **Password comparison uses `==`** rather than a constant-time compare, so it
  is theoretically timing-observable.
- **In-memory OTP cooldowns.** Fine for a single process; a multi-worker
  deployment would need shared state (Redis).
- **`JWT_SECRET` has a committed default** (`foodai-dev-secret-change-me`) so
  the app runs with no setup. Render generates a real one via
  `generateValue: true`; anyone self-hosting must override it.

---

## 🔮 Future Improvements

- [ ] **Demo video** — record a walkthrough for the final submission
- [ ] **Live deployment** — deploy the Render Blueprint and record the URL
- [ ] **`bcrypt` / `argon2` password hashing** — replace the unsalted SHA-256
      scheme and re-seed the demo users (see [Security Notes](#-security-notes))
- [ ] **Login rate limiting** — attempt cap and lockout on `POST /auth/login`,
      matching what the OTP flow already does
- [ ] **Constant-time password comparison** — `hmac.compare_digest` in
      `verify_password`, as the Razorpay path already uses
- [ ] **Real open-dataset training** — retrain on a public Kaggle food-delivery dataset
- [ ] **Traffic-aware ETA** — ingest live traffic signals
- [ ] **LSTM / DeepAR** for demand forecasting, beyond XGBoost
- [ ] **Push notifications** — replace in-app-only notifications with Web Push
- [ ] **Real payment gateway** — swap the Razorpay test-mode path for live keys

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-idea`)
3. Commit your changes
4. Push and open a Pull Request

---

## 📝 License

Distributed under the **MIT License**. See [`LICENSE`](./LICENSE).

---

## 👥 Authors

| Name | Role | Work |
|---|---|---|
| *TODO — add name* | Web Developer | Next.js frontend, FastAPI backend, PostgreSQL schema, live tracking, deployment |
| *TODO — add name* | AI / ML Engineer | Synthetic data pipeline, XGBoost ETA + demand models, evaluation, SHAP explainability |

> **TODO (before submission):** replace both placeholders with the real names
> and roll numbers.

---

## 🙏 Acknowledgements

- **Swiggy / Zomato engineering blogs** — inspiration for the ETA and forecasting approaches
- **StatQuest (Josh Starmer)** — ML concepts made clear
- **XGBoost paper** (Chen & Guestrin, 2016) — the model we built on
- **fastapi.tiangolo.com** — excellent FastAPI documentation
