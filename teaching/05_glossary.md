# FoodAI Teaching Guide — Part 5: Glossary

> Every technical term the FoodAI codebase touches, in one place. Each entry says what it is,
> where it lives in this project, and why you should care. Skim it before Part 1 and keep it
> open while you read the other parts.

---

## Backend & API

| Term | Meaning | Where it lives in FoodAI |
| ---- | ------- | ------------------------ |
| **FastAPI** | Python web framework with automatic OpenAPI docs and type-based validation. | Every router under `backend/routers/*.py`; app entry in `backend/main.py`. |
| **Router** | A FastAPI module that groups related endpoints and is mounted on the app with a prefix. | `routers/auth.py`, `orders.py`, `restaurants.py`, `ml.py`, `tracking.py`, `payments.py`, … |
| **Pydantic** | Python library that validates request/response payloads against declared schemas. | `backend/schemas.py` — `OrderCreate`, `OrderOut`, `PaymentVerify`, … |
| **SQLAlchemy** | Python ORM — Python classes become database tables; rows become objects. | `backend/models.py` — `Order`, `Restaurant`, `MenuItem`, `Payment`-on-`Order`, … |
| **JWT** | JSON Web Token — the signed, self-contained auth token. | `backend/routers/auth.py` issues access + refresh tokens; frontend sends `Authorization: Bearer …`. |
| **OAuth2 / password flow** | The standard "username + password → token" dance FastAPI supports. | `auth.py` uses `OAuth2PasswordBearer` for login; `get_current_user` dependency protects routes. |
| **Dependency injection** | FastAPI resolves function parameters (e.g. `db: Session`) automatically per request. | `get_db()` everywhere; `get_current_user` used as a route dependency. |
| **WebSocket** | Full-duplex connection — server pushes updates without the client polling. | `routers/tracking.py` broadcasts rider positions over `ws/tracking/{order_id}`; the tracking page subscribes. |
| **Background task** | Work the API kicks off and returns immediately. | Scheduled-order `scheduled_for` kick-off; receipt email sending. |
| **CORS** | Browser security policy: which origins may call the API from a page. | Configured in `main.py` so the Next.js dev server can call `127.0.0.1:8000`. |

## Database

| Term | Meaning | Where it lives |
| ---- | ------- | -------------- |
| **ORM** | Object-Relational Mapping — tables ↔ objects. | SQLAlchemy models. |
| **Model / Table** | One class = one table. | `Order`, `Restaurant`, `MenuItem`, `User`, `Coupon`, `Address`, `Review`, `OrderItem`. |
| **Relationship** | A foreign-key link exposed as a Python attribute. | `order.items`, `order.restaurant`, `restaurant.menu_items`. |
| **Column constraints** | Rules on a column: nullable, default, max length. | `payment_status` default `"PENDING"`; `delivery_phone` max length 15. |
| **Migration / seed** | Scripts that create tables and fill starter data. | `backend/init_db.py`, `seed` scripts. |

## Machine Learning (Part 3)

| Term | Meaning | Where it lives |
| ---- | ------- | -------------- |
| **Training data** | Historical examples the model learns from. | `data/orders.csv`, synthesised by `scripts/simulate_orders.py`. |
| **Feature** | An input column the model reads: distance, prep time, hour, zone, … | Generated in the ETA/demand training scripts; listed in `forecast_meta.json`. |
| **Target** | The value the model predicts. | ETA: `delivery_min`. Forecast: order counts per zone per hour. |
| **XGBoost** | Gradient-boosted tree library — the workhorse model here. | `models/eta_model.joblib`, `forecast_model.joblib`. |
| **Regressor** | Model predicting a continuous number. | ETA model (minutes). |
| **Demand forecast** | Predicting future order counts. | `forecast_service.forecast_all_zones`; frontend restaurant/admin charts. |
| **SHAP** | Explains *why* a model gave a number — per-feature +/− impact. | `explain_service.explain_eta` → contributions → the "Why this ETA?" panel. |
| **Fallback** | A cheap rule used when the model/service is unavailable. | `"fallback": true` — distance formula, moving average, straight-line route. |
| **Joblib** | Python's save/load format for models. | `.joblib` model files loaded at startup. |
| **SHAP base value** | The average prediction before any feature pushes it. | Shown in `OrderPrediction.explanation.base_value`. |

## Geospatial & routing

| Term | Meaning | Where it lives |
| ---- | ------- | -------------- |
| **Lat/Lng** | Latitude/longitude coordinates. | `Restaurant.lat/lng`, order `delivery_lat/lng`, rider `rider_lat/lng`. |
| **Polyline** | A list of `[lat, lng]` points forming a path. | `TrackingState.route` — drawn by Leaflet on the tracking page. |
| **OSRM** | Open-Source Routing Machine — real road-path service. | `routing.get_route()` queries OSRM; falls back to a straight line. |
| **Haversine** | Great-circle distance formula between two coordinates. | Used for distance fallbacks and straight-line routing. |
| **Leaflet** | Browser map library. | `components/TrackingMap.tsx` (lazy-loaded). |
| **TMS / tile layer** | The background map image server. | OpenStreetMap tile layer URL in `TrackingMap.tsx`. |

## Payments (Part 4)

| Term | Meaning | Where it lives |
| ---- | ------- | -------------- |
| **COD** | Cash on Delivery — money collected when the food arrives. | `payment_method="COD"`; driver/customer calls `cod/confirm` to mark `PAID`. |
| **Payment intent** | A pre-authorised "I want to charge this much" record with an external id. | `POST /payments/razorpay/order` returns `razorpay_order_id`. |
| **Razorpay** | Indian payment gateway used in the demo. | `payments.py`; frontend `paymentsApi.razorpayOrder/Verify`. |
| **HMAC-SHA256** | Keyed hash — the signature algorithm Razorpay uses. | `verify` recomputes `hmac(order_id|payment_id, secret)` and compares. |
| **Signature** | A digest proving a payment came from the expected client. | `razorpay_signature` in `RazorpayVerifyPayload`. |
| **Key id / key secret** | The merchant credentials. | `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` env vars, with `foodai_demo_*` fallbacks. |
| **Refund** | Money returned to the customer. | `payment_status="REFUNDED"` (cancellation path after payment). |

## Frontend (Part 4)

| Term | Meaning | Where it lives |
| ---- | ------- | -------------- |
| **Next.js App Router** | File-based routing: each folder in `app/` is a route. | `frontend/src/app/**`. |
| **Client component** | A component marked `"use client"` that runs in the browser. | Every interactive page here. |
| **React Context** | Global state without prop drilling. | `AuthProvider`, `CartProvider` → `useAuth()`, `useCart()`. |
| **Hook** | A React function that adds state/effects. | `useState`, `useEffect`, `useCallback`, custom `useAuth`. |
| **Fetch wrapper** | One function centralising requests, headers, refresh, errors. | `api<T>()` in `lib/api.ts`. |
| **Token refresh** | Using a long-lived refresh token to mint a new access token. | `api()` retries once after a 401. |
| **shadcn/ui** | Copy-paste React component library (Tailwind only). | Our dependency-free `components/ui/` kit. |
| **Tailwind** | Utility-first CSS framework. | All styling: `bg-brand-600`, `rounded-2xl`, `flex`, … |
| **WebSocket in browser** | The browser's `WebSocket` API for live updates. | Tracking page's `ws.onmessage` handling `position`/`delivered` frames. |

---

## Cross-cutting ideas to remember

1. **Optional everything.** Models, routing, explainability — every external/mixed dependency
   has a fallback so the app never crashes (Parts 2–3).
2. **The backend owns money and movement.** Payment status and rider position are server
   truth; the frontend only renders and triggers actions (Parts 2–4).
3. **One client, one contract.** `types.ts` mirrors the Pydantic schemas; `api.ts` mirrors the
   routers. If a new endpoint appears, add its group in one place and the UI can use it (Part 4).
4. **Test-mode is real under the hood.** The Razorpay demo uses genuine intent + HMAC verify
   so the code you ship to production is the same — only the SDK and credentials change.
