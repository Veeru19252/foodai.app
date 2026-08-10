# FoodAI — A Beginner-Friendly, Complete Codebase Report

> Written as a mentor explaining a real project to a junior developer who knows basic Python but has never built a full-stack app or a machine-learning model. Every technical word is defined the first time it appears, and anything that looks odd is explained *why* it was done that way.
>
> **Big caveat up front:** this repository contains **two versions of the same app**. The root-level files (`app.py`, `database.py`, `seed_data.py`, …) are the *first version* — a Streamlit prototype. The `backend/` and `frontend/` folders are the *current version* — a proper client/server app with a REST API, a real database, and live WebSocket tracking. This report centres on the **current** build and explains the older files as the prototype that the current one replaced. If you run `streamlit run app.py` you'll get the old UI; if you run the backend + frontend you'll get the new one. Keep that in mind as you read — it explains why some things appear "twice."

---

# 1. Big-picture overview

## 1.1 What this app does, in one paragraph, with no technical words

FoodAI is a website that works like Swiggy or Zomato. A customer opens the site, sees a list of restaurants (Indian, Chinese, Italian, fast food), picks dishes, checks out with an address and an optional discount code, and then watches a little delivery-bot icon move across a map toward their house while a predicted arrival time counts down. Restaurants see incoming orders and can accept them. Delivery riders get notified when an order is assigned to them and can mark the delivery as started or complete. An admin sees a dashboard with money earned, number of orders, charts of which restaurants sell the most, and a map that shows which neighbourhoods (zones) are expected to get a lot of orders in the next hour. The clever part is that the arrival time and the neighbourhood forecasts are **not guessed — they're produced by a machine-learning model** that learned from past order data. So the project is really two things glued together: an ordinary delivery platform, plus an AI that makes predictions that make the platform feel smart.

## 1.2 The three big pieces

Imagine a restaurant that takes orders over the phone. Three roles exist: the **customer** (the caller), the **person answering the phone and writing things down** (this is the *frontend*), and the **chef + the paper register where orders are recorded** (the *backend* and the *database*).

- **Frontend = the part the user sees and clicks buttons on.** For the current version this is a website written with Next.js/React (a popular way to build web pages in JavaScript). For the older version it's Streamlit (a Python library that turns Python scripts into web pages). Either way, its only job is to show information and pass the user's clicks to the backend. It is *not* where orders are actually recorded — if you placed an order purely in the frontend and the frontend crashed, the order would be lost.
- **Backend = the part that does the thinking and talks to the database.** This is a FastAPI application (a Python library for building the server side of a website). It receives messages from the frontend ("please create an order"), checks them (is this person logged in? is the discount code valid? is the item actually on this restaurant's menu?), saves the result to the database, and sends a reply back. It also runs the machine-learning predictions and the simulated "live" delivery movement.
- **Database = where we store everything permanently.** When the backend records an order, it writes a row (one line of a table) into a PostgreSQL database. PostgreSQL is a "relational" database — think of a set of spreadsheets whose rows can point at each other. The database is the only place that remembers things after the user closes their browser tab.

There's a fourth piece that matters for this project: the **ML models**. A model is a file produced by training a machine-learning algorithm on old data. The backend loads these files and asks them "how long will this delivery take?" or "how many orders next hour in zone B?" and uses the answers in the UI.

```
┌──────────────┐   requests + WebSocket   ┌───────────────┐   SQL   ┌──────────┐
│  Frontend    │ ───────────────────────▶ │    Backend    │ ──────▶ │ Database │
│ (Next.js UI) │ ◀─────────────────────── │   (FastAPI)   │ ◀────── │ Postgres │
└──────────────┘      JSON / WS events    └───────┬───────┘         └──────────┘
                                                  │ loads
                                          ┌───────▼───────┐
                                          │  ML models    │  eta_model.joblib
                                          │  (XGBoost)    │  forecast_model.joblib
                                          └───────────────┘
```

## 1.3 What happens when a customer places an order — step by step

Let's trace one real order from click to delivered food. We'll name each layer as we pass through it.

1. **Customer's browser (frontend).** The customer has dishes in their cart (held in the browser's memory) and clicks **Place order** on the checkout page (`frontend/src/app/checkout/page.tsx`).
2. **Frontend builds a request.** The checkout page gathers the chosen dishes, the delivery address (lat/lng coordinates + a text address), and any discount code, and sends them to the backend as a message called an **HTTP request** (more on that in §3.1). It uses a small helper file, `frontend/src/lib/api.ts`, that knows the backend's address.
3. **Backend receives it.** The FastAPI app (`backend/main.py`) has a list of "routes" — rules that say "if a request like this arrives, call *that* Python function." A POST request to `/orders` (the URL that creates orders) is handled by `create_order` in `backend/routers/orders.py`.
4. **Backend checks identity.** The customer's request carries a **token** (a coded ticket proving they logged in). The backend verifies it and refuses if it's missing or fake — otherwise anyone could order as anyone else. It also checks the user is a *customer* role, not a rider or admin.
5. **Backend validates the order.** It loads the restaurant, confirms every requested item actually exists on *that* restaurant's menu (so the customer can't invent a price), computes the subtotal using the **server-side menu prices** (never the prices the browser sent — the browser could lie), and validates the discount code if one was given (is it active? not expired? above the minimum order? under the usage limit?).
6. **Backend writes to the database.** It inserts one row into `orders` and one row per dish into `order_items`, links them, increments the promo code's usage counter, and commits (saves) the transaction. Now the order *really exists*.
7. **Backend replies.** It returns JSON (a text format for structured data) containing the new order's id, total, and status `PLACED`. The frontend receives this and redirects the customer to the live tracking page for that order.
8. **Live tracking kicks in.** The tracking page opens a **WebSocket** (§3.8) — a permanently open two-way phone line to the backend — and the backend's *simulation engine* (a background loop that pretends to be the rider fleet, `backend/simulation.py`) starts moving the bot along a real road route from the restaurant to the customer's coordinates, sending position updates every 2 seconds. Meanwhile the ML service predicts the ETA, and the tracking page shows both the moving map pin and the countdown.
9. **Restaurant and rider act.** The restaurant owner sees the order in their panel and confirms it → `CONFIRMED` → `PREPARING`. The restaurant assigns a rider (or an admin does), and the rider (or restaurant) marks it `OUT_FOR_DELIVERY`, which stamps the pickup time and makes the simulation advance the rider along the route. When the simulated rider reaches 100% progress, the backend marks the order `DELIVERED`.
10. **After delivery.** The customer can leave a 1–5 star review (one per order). The admin dashboard's revenue numbers include the delivered order. And — quietly — the order is now part of the "history" the ML model would be retrained on later.

That one path touches the frontend, the backend, the database, and the ML layer, in that order. Everything else in this report is a zoom-in on one of those steps.

---

# 2. Folder & file structure explained

## 2.1 The layout at a glance

```
foodai.app/
├── backend/            ← CURRENT: FastAPI server (the "brain" of the API)
├── frontend/           ← CURRENT: Next.js website (what the user clicks)
├── models/             ← Trained ML model files (.joblib)
├── scripts/            ← ML training + data-generation scripts
├── data/               ← The CSV used to train the models
├── outputs/            ← Charts + metric files from training
├── notebooks/          ← Jupyter notebook experiments (Person B's scratch work)
├── tests/              ← Automated backend tests
├── [root files]        ← LEGACY: the old Streamlit prototype + shared ML modules
├── docker-compose.yml  ← Runs Postgres + backend + frontend in one command
└── README.md           ← The project's own documentation (worth reading!)
```

**Why there are files at the root AND in `backend/`?** Because of the history: the project started as a single-file Streamlit app at the root, and when the team re-platformed it, they created a proper `backend/` package and a `frontend/` folder — but kept the trained models and the pure ML/geo helper modules at the root so both the old and new app could import them. This is the single most confusing thing about this repo, so if anything looks duplicated, ask "is this the old version or the new version?" first.

Before reading on, one rule that explains a *lot* of this layout: **separation of concerns** — "each file should do one job, so you can change one part without breaking the others." That's why the database code isn't shoved inside the API code, why the ML code is in its own files, and why the UI is a separate folder.

## 2.2 The current backend (`backend/`)

This folder is a Python **package** (a folder with an `__init__.py` that Python treats as one importable unit — that file is just an empty marker, nothing interesting happens in it).

| File | One-sentence purpose | What it does and why it exists |
|---|---|---|
| `backend/main.py` | The **entry point**: creates the FastAPI app and wires everything together. | When you run `uvicorn backend.main:app`, Python imports this file. It builds the `app` object, registers all the route-handlers ("routers"), sets up CORS (which browsers are allowed to talk to it), and runs startup code that creates database tables, seeds demo data, and launches the rider-simulation loop. It's the "front door" of the backend. |
| `backend/config.py` | Reads settings (database URL, JWT secret, CORS origins) from environment variables, with sensible defaults. | Keeps secrets and machine-specific settings out of the code. The same code runs locally, in Docker, and on Render with just different environment variables. It also has a small helper that rewrites `postgres://` URLs into `postgresql+psycopg2://` because SQLAlchemy 2.x dropped support for the short form. |
| `backend/db.py` | Creates the SQLAlchemy database **engine** and session factory. | SQLAlchemy is a Python library that lets you talk to the database using Python objects instead of raw SQL strings. This file makes one engine (the connection pool) and one way to open "sessions" (a short-lived conversation with the DB). Also defines `get_db()`, the function FastAPI calls to give every request its own session. |
| `backend/models.py` | Defines every database table as a Python class (the **ORM models**). | Each class (`User`, `Restaurant`, `Order`, …) is a table; each attribute is a column; `relationship(...)` describes how tables link. This file is the single source of truth for the database schema in the new backend. |
| `backend/schemas.py` | Defines the shape of data sent into and out of the API (**Pydantic models**). | Pydantic validates that incoming JSON has the right fields/types (e.g. a rating between 1 and 5) and documents what responses look like. It's the "contract" between frontend and backend. |
| `backend/security.py` | Password hashing, JWT token creation/verification, and role checks. | Implements login security: it hashes passwords so the raw password is never stored, creates signed tokens the frontend can send back as "proof of who I am," and provides `require_roles(...)` which blocks endpoints unless the caller has the right role. |
| `backend/seed.py` | Inserts demo users, restaurants, menus, and promo codes when the DB is empty. | A brand-new database has nothing in it, which makes the app boring to demo. This file makes sure the first boot gives you the 5 restaurants, 9 accounts, and 3 promo codes the README promises. It checks "is the users table empty?" first so it never double-seeds. |
| `backend/simulation.py` | Pretends there is a real delivery fleet: moves every active rider every 2 seconds and broadcasts positions over WebSockets. | There is no actual GPS hardware, so the backend *simulates* it. This file is the heart of the "live tracking" feature — a background loop that computes where each rider should be (based on elapsed time and route length), stores a `trip_logs` row, and pushes the new position to every connected browser. Also contains the pub/sub manager that routes WebSocket messages. |
| `backend/tracking_state.py` | Builds one consistent "tracking snapshot" (route, rider position, ETA) for an order. | Both the REST endpoint and the WebSocket use this same function so the two views can never disagree. It glues together the geo helpers (`tracking.py`), the road routing (`routing.py`), and the ML ETA (`eta_service.py`). |
| `backend/routers/__init__.py` | Empty package marker. | No logic; standard Python packaging. |
| `backend/routers/auth.py` | Login, register, refresh-token, and "who am I" endpoints. | The `router` objects inside these files are registered in `main.py`. Auth handles creating accounts, checking passwords, and issuing tokens. |
| `backend/routers/restaurants.py` | Public catalog endpoints: list restaurants, list cuisines, get a menu. | No login required (browsing is public). Includes search (`q=`) and cuisine filter, and merges in review averages per restaurant. |
| `backend/routers/orders.py` | All order logic: create single/batch orders, list them per role, update status, assign riders, cancel, validate promo codes. | This is the busiest router. It contains the promo-code math and the rules about *who may do what* (only the customer cancels; only the restaurant/admin confirms; the assigned rider can dispatch). |
| `backend/routers/tracking.py` | The REST tracking endpoint and the two WebSocket channels (order tracking + per-user notifications). | Shows how to send live data both ways: REST for a one-time snapshot, WebSocket for continuous updates. Also enforces that only the customer, the restaurant, the assigned rider, or an admin can watch an order's live location. |
| `backend/routers/ml.py` | Exposes the ML features as endpoints: ETA, SHAP explanation, forecast, forecast series, recommendations, per-order prediction. | This is the "AI differentiator" layer. Every endpoint *degrades gracefully* — if the model file is missing it returns `"fallback": true` instead of crashing, so the app keeps working. |
| `backend/routers/admin.py` | Admin-only endpoints: overview stats, user list, all orders, and create restaurants/menu items. | Powers the admin dashboard. Every endpoint here is guarded so only the `admin` role can call it. |
| `backend/routers/reviews.py` | Let customers rate a delivered order; list reviews for a restaurant. | Enforces the rules: only the customer who ordered may review, the order must be delivered, and one review per order. |
| `backend/alembic/` | Database **migration** tooling. | Migrations are versioned recipes for changing the database schema (adding the `reviews` table, etc.) so production databases can be updated safely without dropping data. `env.py` is the glue between Alembic and our models; `versions/*.py` are the actual recipes. This is the "grown-up" alternative to the legacy code's `CREATE TABLE IF NOT EXISTS`. |
| `backend/Dockerfile` | The recipe for building a Docker image of the backend. | Docker packages the app + Python + dependencies into one box that runs identically anywhere. The last line runs migrations then starts uvicorn. |

## 2.3 The current frontend (`frontend/`)

The frontend is a **Next.js 14** app — a framework for building websites with React and TypeScript. "TypeScript" is JavaScript with types — it catches many mistakes at save-time instead of at runtime.

| File | One-sentence purpose | What it does and why it exists |
|---|---|---|
| `frontend/package.json` | The list of the frontend's JavaScript dependencies and scripts. | `npm run dev` starts the dev server; `npm run build` compiles a production version. Dependencies include React, Next, Leaflet (for maps), and Playwright (for tests). |
| `frontend/src/lib/api.ts` | The single place the frontend talks to the backend. | Every page calls these typed functions (`authApi.login`, `ordersApi.createBatch`, …) instead of writing `fetch(...)` everywhere. It attaches the JWT token to every request, and if a request comes back `401` (not logged in) it automatically tries to refresh the token once and retries. Centralising this means auth logic lives in one spot. |
| `frontend/src/lib/auth.tsx` | React "context" that remembers who is logged in. | A context is a way to share state (like "the current user") across many screens without passing it down by hand. Any page can call `useAuth()` and get the user or log in/out. |
| `frontend/src/lib/cart.tsx` | React context that holds the shopping cart in the browser's memory. | Keeps the cart across screens (restaurants → checkout) without the server needing to remember it. It groups items by restaurant because the backend creates *one order per restaurant* in a multi-restaurant cart (a "batch order"). |
| `frontend/src/lib/types.ts` | TypeScript type definitions that mirror the backend's JSON. | Every backend response is described as a TypeScript interface (`OrderDetail`, `TrackingState`, …). This is the frontend's copy of the same "contract" that `backend/schemas.py` describes on the Python side. If a shape changes, TypeScript complains at build time. |
| `frontend/src/app/layout.tsx` | The shell every page lives in. | Wraps all pages with the providers (auth, cart) and the shared styling, and renders the Navbar. "Providers" are the React contexts we set up — they make auth and cart available everywhere. |
| `frontend/src/app/page.tsx` | The homepage. | Mostly a landing page that redirects logged-in users to the right role's view. |
| `frontend/src/app/login/page.tsx` + `register/page.tsx` | The login and registration screens. | Call `authApi.login` / `authApi.register` and store the returned tokens via `saveAuth`. Registration is how the demo shows off account creation (any new user gets the `customer` role by default). |
| `frontend/src/app/restaurants/page.tsx` | The restaurant browsing page. | Lists restaurants with cuisine filter and search; each has a menu modal to add dishes to the cart. Uses `catalogApi.restaurants` / `.menu`. |
| `frontend/src/app/checkout/page.tsx` | Checkout: delivery address, promo code, order summary, place order. | Sends the whole cart to `ordersApi.createBatch`, which becomes one order per restaurant. On success it redirects to the first order's live tracking page. |
| `frontend/src/app/orders/page.tsx` | "My orders" list for customers. | Calls `ordersApi.mine()`, shows each order's status/total, and links to tracking. |
| `frontend/src/app/tracking/[orderId]/page.tsx` | The live-tracking screen: map, AI ETA, "Why this ETA?" panel, WebSocket updates. | This is the showpiece. It opens a WebSocket to receive live rider positions, calls `/ml/order/{id}` for the prediction + SHAP explanation, and renders everything. `[orderId]` in the folder name means the URL `/tracking/42` passes `orderId = 42` into the page. |
| `frontend/src/app/restaurant/orders/page.tsx` | The restaurant owner's order-management panel. | Lists that restaurant's orders, lets the owner confirm/prepare orders and assign riders. Uses `ordersApi.restaurantOrders()`, `.updateStatus`, `.assign`. |
| `frontend/src/app/driver/page.tsx` | The delivery rider's panel. | Lists the rider's assigned deliveries, shows the route, and lets the rider start/deliver. Uses `ordersApi.driverOrders()` and the tracking/WS endpoints. |
| `frontend/src/app/admin/page.tsx` | The admin dashboard. | Calls `adminApi.overview()`, `adminApi.orders()`, and `mlApi.forecastSeries()` to show revenue/order metrics and the zone-demand forecast. (The legacy Streamlit `app.py` has a richer version with Plotly charts and a folium heatmap.) |
| `frontend/src/components/*.tsx` | Reusable UI pieces. | `Navbar`, `ProtectedRoute` (blocks a page unless you're logged in and optionally a given role), `LocationPicker` (map to choose the delivery point), `TrackingMap` (Leaflet map with route + rider pin), `StatusBadge`, `RestaurantMenuModal`, `ReviewModal`, `NotificationBell` (listens to the `/ws/notifications` channel so riders get "new delivery assigned" alerts). |
| `frontend/globals.css` + `tailwind.config.ts` | Styling. | Tailwind CSS classes plus a custom "brand" orange palette. |
| `frontend/e2e/*.spec.ts` | Playwright end-to-end browser tests. | Automatically drive a real browser: customer orders food, driver flow, and role access control. This is what runs in CI to prove the whole stack works together. |
| `frontend/Dockerfile` | Recipe for a Docker image of the frontend. | Multi-stage build: install deps → compile → slim production image. |
| `frontend/next.config.mjs`, `postcss.config.mjs`, `tsconfig.json`, `playwright.config.ts`, `next-env.d.ts`, `src/types/css.d.ts` | Framework configuration + type declarations. | Standard config files — the sort every Next.js app has; they tell the tooling how to build/lint/test and how to type custom CSS modules. |

## 2.4 The ML pipeline (Person B's work)

| File | One-sentence purpose | What it does and why it exists |
|---|---|---|
| `scripts/simulate_orders.py` | Generates 600 fake but realistic orders and saves them to `data/orders.csv`. | There is no real company order data, so this script *manufactures* it: random restaurant, zone, hour, distance, prep time, traffic factor, and a `delivery_min` target computed from a plausible formula plus noise. Using `random.seed(42)` makes the output reproducible — rerun it and you get the exact same CSV, which is essential for grading and for comparing models fairly. |
| `scripts/train_eta.py` | Trains the ETA models (baseline, linear, random forest, XGBoost), saves the best one, writes metrics + charts. | The full ML workflow in one script: load CSV → build features → split train/test → fit 3 models + a hand-written baseline → evaluate with MAE/RMSE → save `models/eta_model.joblib` → write `outputs/metrics_eta.json` and the PNG charts. It is the "training" half of the ETA story (the app itself is the "prediction" half). |
| `scripts/train_forecast.py` | Trains the demand-forecast model (XGBoost vs a moving-average baseline), saves model + schema metadata. | Same pattern as train_eta but for the forecasting problem: it aggregates orders into per-zone hourly counts, adds "lag" features (how many orders in the previous 1h / 3h), splits in time order, and saves `models/forecast_model.joblib` plus `models/forecast_meta.json` (which records the exact feature-column order so inference can stay in sync). |
| `data/orders.csv` | The training dataset: one row per simulated order. | Columns include `distance_km`, `hour`, `day_of_week`, `is_weekend`, `prep_time_min`, `traffic_factor`, `customer_zone`, and the target `delivery_min`. This file is the fuel for both training scripts. |
| `models/eta_model.joblib` | The trained XGBoost ETA model, serialized (saved to disk) with joblib. | A `.joblib` file is Python's way of saving a trained model object so it can be loaded later without retraining. `eta_service.py` loads this at runtime. |
| `models/forecast_model.joblib` | The trained XGBoost demand model. | Loaded by `forecast_service.py`. |
| `models/forecast_meta.json` | The feature-schema description for the forecast model. | A tiny JSON: `{"feature_columns": [...], "zones": [...]}`. It lets the prediction code build feature vectors in exactly the order the model expects, even if that order changes in a retraining run. |
| `outputs/metrics_eta.json` / `metrics_forecast.json` | The evaluation scores, saved as JSON. | E.g. ETA XGBoost MAE 2.03 min vs baseline 2.84 — this is the proof that "the AI beats a simple formula." |
| `outputs/charts/*.png` | Charts produced during training. | `eta_actual_vs_predicted.png`, `eta_feature_importance.png`, the forecast equivalents, etc. These are the pictures you'd put in a report or viva to show the model quality. |
| `notebooks/01_pandas_practice.ipynb` | Person B's Jupyter notebook. | A notebook is a mix of code + text + output, great for experimenting. This one is the recorded learning/tinkering history; the final, runnable logic lives in the scripts above. |

## 2.5 The shared root modules

These live at the root so **both** the legacy Streamlit app and the new FastAPI backend can import them. They are deliberately "pure" — they import nothing heavy (no Streamlit, no database), so they can be tested in isolation.

| File | One-sentence purpose | What it does and why it exists |
|---|---|---|
| `tracking.py` | Pure geo helpers: distances, routes, rider position interpolation, formula ETA. | Functions like `haversine_km` (great-circle distance), `interpolate_position` (where is the rider at 40% progress?), and `compute_eta` (remaining minutes = remaining distance ÷ speed). No database, no UI — the same maths is used by the old app and the new backend. |
| `routing.py` | Fetches real road routes from the free OSRM API, with a straight-line fallback. | "As the crow flies" routes look wrong on a map, so this asks an open routing service for points along actual roads. It caches results and falls back to a straight line if the service is unreachable, so the app never crashes on a bad network. |
| `maps.py` | Builds folium maps (the old app's maps): route line + restaurant/rider/customer markers + admin heatmap. | Legacy-only visual helper; the new frontend draws its own maps with Leaflet in JavaScript. Kept at the root because `app.py` (legacy) still uses it. |
| `eta_service.py` | Loads the ETA model and turns order details into a predicted ETA (minutes). | This is the bridge between raw data (distance, prep time, time of day, zone) and the XGBoost model's input. It also *falls back* to a simple speed formula if the model file is missing, so the app works even without the AI. §3.5 and §4.5 dig into it. |
| `forecast_service.py` | Loads the demand model and predicts next-hour order counts per zone. | Same idea for forecasting: build the 10-feature vector, ask XGBoost, clamp negative counts to 0, and fall back to a moving average when the model is absent. |
| `explain_service.py` | Explains an ETA prediction using SHAP values. | Answers "why did the model say 28 minutes?" by listing how much each factor (distance, prep time, …) pushed the number up or down. §3.7 explains SHAP. |
| `database.py` | LEGACY: the old MySQL schema + all query functions for the Streamlit app. | A big module of raw SQL. It defines the table layout in one `SCHEMA` string and provides helpers like `create_order`, `get_orders_for_customer`, `get_revenue_totals`. Its job is now performed by `backend/models.py` + `backend/db.py` (which mirror the same tables). |
| `app.py` | LEGACY: the entire Streamlit frontend (1,199 lines). | The original single-file app: login, restaurant listing, cart, checkout, tracking, delivery panel, admin dashboard. Replaced by the Next.js frontend, but kept for reference and because it still runs. |
| `config.py` | LEGACY: reads MySQL settings from `.env`. | The old app's config; the new backend uses `backend/config.py` instead. |
| `seed_data.py` | LEGACY: seeds demo data into MySQL (the old DB). | The old version of `backend/seed.py`. |
| `ui/theme.py` | The legacy app's design system: CSS tokens + pure HTML renderers. | A file of CSS plus functions that return HTML strings (status badge, stepper, cards) so the old app looks branded. Interesting pattern: the renderers are pure functions, and importing the module has no side effects — only `inject_css()` touches Streamlit, and it imports Streamlit lazily. |

## 2.6 Infrastructure, config, and tests

| File | One-sentence purpose | What it does and why it exists |
|---|---|---|
| `requirements.txt` | The Python dependency list. | One file installs everything: `pip install -r requirements.txt`. Covers Streamlit, FastAPI, SQLAlchemy, XGBoost, SHAP, pandas, etc. |
| `alembic.ini` | Alembic's configuration file. | Tells Alembic where its scripts live and how to connect; the `DATABASE_URL` is overridden from the environment in `backend/alembic/env.py`. |
| `docker-compose.yml` | Starts Postgres + backend + frontend with one command. | `docker compose up --build` brings up the whole stack. Docker "containers" are mini-computers; compose orchestrates several at once. Great for a demo that works on any machine. |
| `render.yaml` | Render (a cloud host) "Blueprint" config. | Declares the three services (Postgres, backend, frontend) so the app can be deployed to the cloud by connecting the GitHub repo. |
| `.github/workflows/ci.yml` | GitHub Actions **CI** (continuous integration). | On every push, GitHub runs this: backend pytest tests against a throwaway Postgres, a frontend build, and Playwright browser tests. "CI" means *every change is automatically checked*, so a broken commit is caught immediately. |
| `tests/conftest.py` | Test setup: forces tests onto an isolated `foodai_test` database and provides fixtures. | Pytest's config hook. It sets the `DATABASE_URL` env var *before* any backend module is imported (because config is read at import time), drops/creates the schema, seeds it, and hands tests an in-memory `client` that mimics real HTTP calls. |
| `tests/test_api_e2e.py` | End-to-end API tests: login, order + promo, assignment, tracking access control, ML endpoints, reviews, batch orders. | The project's 40+ automated tests. Each test does a real HTTP round-trip against the API and asserts on the response. |
| `tests/test_helpers_unit.py` | Unit tests for the pure helper modules. | Tests the small pure functions (e.g. geo distance, feature-building) in isolation. |
| `.env` | Local secrets file (gitignored — not in git). | Holds real MySQL/Postgres credentials on the developer's machine. **Never commit this file.** |
| `.gitignore` | Tells git which files to ignore. | Keeps `.venv`, `.env`, `__pycache__`, `node_modules`, `*.db` out of the repository. |
| `.dockerignore` | Tells Docker which files to ignore when building. | Stops Docker from copying `.venv`, `node_modules`, etc. into the image. |
| `.streamlit/config.toml` | The legacy app's Streamlit theme. | Colours and fonts for `streamlit run app.py`; also needed for the Hugging Face Spaces deployment. |
| `setup.sh` | Hugging Face Spaces build hook. | On that hosting platform, this runs `pip install -r requirements.txt` before launching the Streamlit app. |
| `foodai.db` | A leftover SQLite database file from the very first prototype. | The project moved from SQLite → MySQL → PostgreSQL, so this file is a fossil. Worth knowing about because a beginner might otherwise assume it's "the" database. |
| `.vscode/settings.json` | Editor settings. | e.g. formatting preferences for VS Code users. |
| `.tmp/` | Agent task-tracking scratch (JSON files). | Generated by the development assistant that helped build this; not part of the app. Safe to ignore. |
| `README.md` | The project's own documentation. | 600+ lines covering features, setup, architecture, API, metrics, roadmap, and deployment. Read it — this report is a deeper companion to it. |

---

# 3. Concept explainers

> These are the ideas you need **before** reading the code. Each one is defined in plain language and then tied to a real spot in this project.

## 3.1 What an API is, and what FastAPI specifically does

An **API** (Application Programming Interface) is a rulebook for how two programs talk to each other. Imagine a waiter: the kitchen (backend) doesn't let you walk in and shout, but the waiter has a fixed list of ways to communicate ("I'd like a paneer butter masala, please" → the waiter brings it). An API is exactly that: a set of agreed messages ("create an order", "give me this restaurant's menu") plus the format for those messages (JSON). The frontend is the diner; the backend is the kitchen; the API is the waiter.

**FastAPI** is a Python library that makes it very easy to *be* the waiter — to declare these agreed messages and define what happens for each one. You write a normal Python function, decorate it with a line like `@router.post("/orders")`, and FastAPI handles all the plumbing: it receives the HTTP request, checks the incoming data matches the declared format, calls your function, and turns whatever it returns into the response. It also generates interactive API docs at `/docs` automatically, which is one reason students love it.

## 3.2 What a REST endpoint is (GET vs POST, with real examples)

**REST** is a style of designing APIs where the messages are "verbs" (HTTP methods) applied to "nouns" (URLs). The two verbs you'll see constantly are:

- **GET** = "give me data, change nothing." Like asking a question. Example in this repo: `GET /restaurants` returns the list of restaurants. `GET /ml/eta?distance_km=5` asks the model to predict a delivery time for a 5 km trip — nothing is saved, it's just a question.
- **POST** = "here is new data, do something with it." Example: `POST /orders` with a JSON body listing the dishes creates an order and *stores* it.

Each URL + verb combination is called an **endpoint**. The rule of thumb: if it changes stored data, use POST (or PATCH/PUT for partial/full updates); if it only reads, use GET. In this repo you can see the pattern everywhere — `GET /tracking/{id}` reads a snapshot, while `POST /orders/{id}/cancel` changes an order's status. The `{id}` is a placeholder meaning "any number", e.g. `/orders/42/cancel`.

## 3.3 What a database table / schema is, using this project's actual tables

A **database table** is like one spreadsheet. A **schema** is the collection of all tables plus the rules about how they connect (the column types, the links between tables). This project has nine tables; here are the ones you'll meet most:

- `users` — everyone: customers, restaurant owners, riders, admins. Columns: `id`, `name`, `email`, `password_hash` (never the raw password!), `role`.
- `restaurants` — the 5 restaurants. Links to a `user_id` (the owner account).
- `menu_items` — one row per dish. Links to `restaurant_id`; has `price` and `prep_time_min`.
- `orders` — one row per order: `customer_id`, `restaurant_id`, `delivery_id` (assigned rider), `status`, `total`, `coupon_code`, `discount_amount`, `delivery_lat/lng/address`, `created_at`.
- `order_items` — the line items of an order (which dishes, how many, at what price). Links to `order_id` and `menu_item_id`.
- `deliveries` — the rider assignment for an order, plus `pickup_time` and `delivered_time`.
- `trip_logs` — a position history for a delivery (`lat`, `lng`, `timestamp`). This is the simulated rider's breadcrumb trail.
- `promo_codes` — discount codes with their rules (`discount_type`, `discount_value`, `min_order_value`, `max_discount`, `valid_until`, `usage_limit`, `times_used`, `active`).
- `reviews` — star ratings + comments, one per delivered order.

Two of these tables point at the same table: `orders.delivery_id` and `deliveries.driver_id` both reference `users.id`. That's normal — a "foreign key" (a column that points at another table's row) is how relational databases link data.

## 3.4 What Streamlit is, and how it differs from a normal website

**Streamlit** is a Python library where you write a normal Python script and Streamlit turns it into a web page. Every time the user clicks something, the *whole script runs again* from the top. It's brilliant for quick tools and demos (no JavaScript, no HTML) — which is exactly why the first version of this app was built with it. But it's a poor fit for a real multi-page product: every interaction reruns everything, real-time features need a polling hack, and it's hard to make polished per-role screens. A **normal website** (like the new `frontend/`, built with React/Next.js) is: HTML/CSS/JavaScript rendered in the browser, with the page updating itself in tiny bits, fetching only the data it needs from the API. The trade-off: the Next.js version needs a whole extra toolchain, but it behaves like a real product (Swiggy-style live updates, separate pages per role, real-time map).

## 3.5 What machine-learning "training" and "prediction" mean, using the ETA model as the running example

Machine learning is, at its heart: *find a pattern in past examples, then use the pattern on new examples.*

- **Training** happens once, offline, in `scripts/train_eta.py`. You take rows of past orders. For each row you have **features** (the inputs): `distance_km`, `prep_time_min`, `hour_of_day`, `day_of_week`, `is_weekend`, `traffic_factor`, and the delivery `zone` (one-hot, see §3.9). And you have the **target** (the answer you want to learn to predict): `delivery_min`. The algorithm studies thousands of (features → answer) pairs and tunes its internal rules to make the fewest mistakes. It cannot "see" new orders — it only learns the mapping.
- **Prediction** (a.k.a. inference) happens constantly, at runtime, in `eta_service.py`. A brand-new order comes in with its own features. We hand the model the *same kind* of vector of numbers it saw in training, and it outputs one number: predicted delivery minutes. It has never "seen" this order before, but it has seen thousands like it.

The pipeline for the ETA specifically: route length → `distance_km`; restaurant menu → `prep_time_min`; the clock → `hour_of_day`, `day_of_week`, `is_weekend`; the customer's location snapped to the nearest zone → the one-hot zone block. Those 11 numbers go in, one number comes out.

**Critical rule that beginners miss:** the feature vector at prediction time must be in the *exact same order and shape* as at training time. That's why `eta_service.py` repeats the column list `FULL_COLUMNS` — it's copying the training script's recipe by hand. If they drifted, the model would silently misbehave.

## 3.6 What XGBoost is, in one paragraph, no math

**XGBoost** (Extreme Gradient Boosting) is a machine-learning method that combines many small, simple decision rules ("if distance is more than 3 km and it's rush hour, add 4 minutes") into one strong predictor. You train thousands of these tiny rules, and each new rule focuses on the mistakes the previous ones made, so together they fix each other's errors. You can think of it as a crowd of weak guessers whose individual opinions are averaged into a wise group answer. For this project it's a "regressor" (predicts a continuous number like minutes) and it outperforms a simple formula and linear regression on the ETA task — with only a small dataset, tree-based models like XGBoost and Random Forest are usually the strongest, most beginner-forgiving choice.

## 3.7 What SHAP values are, and why the project uses them

Most ML models are **black boxes** — they give an answer but not a reason. **SHAP** (SHapley Additive exPlanations) is a technique that unpacks the answer: for one prediction, it says "the average delivery would be X minutes; *distance* added +6.2, *prep time* added +3.1, *hour of day* subtracted −1.5, …" — the contributions add up to the prediction. It does this by simulating what the model would have predicted if each feature were different, and fairly dividing the total effect among the features (the name comes from game theory's Shapley values). 

This project uses it for the **"Why this ETA?"** panel on the tracking page: the frontend shows each factor as a coloured bar ("Distance +6.2 min", "Weekend +2.0 min"), turning an unexplained AI number into a justifiable one. That's the "explainable AI" differentiator the README brags about — and it's exactly the kind of thing examiners ask about.

## 3.8 What a WebSocket / polling loop is, using `tracking.py` as the example

Two ways a page can get *live* data:

- **Polling:** the page asks "any news?" every 2 seconds and gets an answer each time. Simple, but wasteful (mostly empty answers), and there's up to 2 seconds of lag. This is how the *legacy* Streamlit app did it (`st_autorefresh(interval=2500)`).
- **WebSocket:** the browser and backend open **one** connection that stays open, and the backend *pushes* a message the instant something changes. Like a phone call instead of walkie-talkie beeping. The **new** app uses this: `frontend/src/app/tracking/[orderId]/page.tsx` opens `ws://.../ws/tracking/42` and just listens; `backend/simulation.py` pushes a `{type: "position", lat, lng, progress}` message every 2 seconds to everyone subscribed to that order's channel. No re-asking needed.

The backend's `ConnectionManager` keeps a list of which browser sockets care about which order ("pub/sub" = publish/subscribe: one publisher sends to many subscribers). When the simulation ticks, it publishes to the order's channel, and every connected browser's handler updates the map.

---

> **Continued in `report_2.md`.** Sections 4–9 of this report — the code walkthrough (§4), data-flow diagrams (§5), design-decision callouts (§6), glossary (§7), beginner Q&A (§8), and the reading guide (§9) — live in the companion file `report_2.md`.

