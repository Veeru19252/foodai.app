# FoodAI Teaching Series — Layer 1: Database

> How to read this file: each **file path heading** is followed by the full code in a fenced block, then a **line-by-line explanation** using the three-part structure **What it does / Why this way / What breaks**, then a **How this connects** note. Patterns explained once are referenced later as "same pattern as …" instead of being repeated.
>
> Layer 1 changed two things in the repo: `backend/models.py` gained **payment fields** and **structured Indian address fields** on `orders`, and a new Alembic migration was added. The rest of this file explains the whole database layer so you understand what those changes connect to.

---

# `backend/db.py` — the engine and session factory (unchanged, explained because everything else builds on it)

```python
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
```

- `engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)` — **What:** makes the "connection pool" — a small set of always-ready database connections that requests borrow and return. **Why this way:** creating a brand-new connection per query is slow; a pool reuses them. `pool_pre_ping=True` runs a tiny "are you alive?" check before handing out a connection. **What breaks:** without the ping, if the database restarts, the pool hands out dead connections and the whole API returns 500s until the process is restarted.
- `SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)` — **What:** a factory that builds short-lived "sessions" (a conversation with the DB for one request's work). **Why this way:** `autocommit=False` means nothing touches the DB until you explicitly `commit()` — you control the transaction. **What breaks:** with autocommit on, a crash halfway through multi-row work leaves half-written data (an order without its items).
- `Base = declarative_base()` — **What:** creates the parent class every model in `models.py` inherits from, so SQLAlchemy can register all tables on one object. **Why this way:** it's the standard SQLAlchemy 2.x pattern for classic "declarative" models. **What breaks:** without a shared base, each model would register on its own and `create_all`/Alembic couldn't see all tables at once.
- `def get_db():` … `yield db` … `finally: db.close()` — **What:** a generator FastAPI calls per request to hand the route function a session, and closes it afterwards no matter what. **Why this way:** the `finally` guarantees closure even if the handler crashes (a generator can resume after the crash). **What breaks:** returning a session and closing it manually in every route means the first route you forget to close leaks a connection until the pool is exhausted.

**How this connects:** `backend/models.py` imports `Base` from here; every router imports `get_db` for its `db: Session = Depends(get_db)` parameter; `backend/config.py` supplies `DATABASE_URL`. If this file were deleted, nothing could talk to the database at all — every endpoint would fail with an import error.

---

# `backend/models.py` — every table, every column, every foreign key (modified)

The file starts with the allowed-values constants, then defines one class per table.

```python
VALID_ROLES = ("customer", "restaurant", "delivery", "admin")
VALID_ORDER_STATUSES = (
    "PLACED", "CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED",
)
VALID_PAYMENT_METHODS = ("COD", "RAZORPAY")          # NEW
VALID_PAYMENT_STATUSES = ("PENDING", "PAID", "FAILED", "REFUNDED")  # NEW
```

- **What:** tuples of the *only* allowed values for role, order status, payment method, and payment status. **Why this way:** they live in one shared place so no typo can invent a role or status; the routers and schemas import these same tuples and validate against them. **What breaks:** if these were magic strings written inline in 30 places, a single misspelling ("CONFIRM" instead of "CONFIRMED") would pass validation but never match any real status — an order that can't progress, with no error to tell you why.

## `User` — the `users` table

```python
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False)

    restaurants = relationship("Restaurant", back_populates="owner")
    deliveries = relationship("Delivery", back_populates="driver")
```

- `class User(Base)` + `__tablename__ = "users"` — **What:** turns this class into a table named `users`; each `Column` is a column of that table. **Why this way:** the ORM lets you write `db.query(User)` instead of hand-written `SELECT * FROM users`. **What breaks:** raw SQL strings (the old `database.py` way) have no type checking — a typo'd column name only fails at runtime, often in production.
- `id = Column(Integer, primary_key=True)` — **What:** the row's unique number; the database guarantees it's unique and auto-increments. **Why this way:** every row needs a stable identity that doesn't change (emails can change; ids don't). **What breaks:** using `email` as the key breaks the first time someone changes their email and all their linked orders stop resolving.
- `name = Column(String(255), nullable=False)` — **What:** a text column that may not be NULL. **Why this way:** `String(255)` is the standard "short text" length; `nullable=False` makes "you must provide a name" a *database* rule, not just a form rule. **What breaks:** if NULL were allowed, two code paths might each assume the other checked — you'd get "Hello, None" screens and broken greeting logic.
- `email = Column(String(255), nullable=False, unique=True)` — **What:** text column that must be unique. **Why this way:** `unique=True` creates a database unique index, *in addition to* the API's pre-check in `auth.py`. **What breaks:** the API-only check has a race: two simultaneous registrations with the same email both pass the check, then both insert. The DB constraint makes the duplicate impossible.
- `password_hash = Column(String(255), nullable=False)` — **What:** the scrambled password, never the raw one. **Why this way:** if the DB leaks, attackers get useless text. **What breaks:** storing plaintext passwords turns a DB leak into a headline — and users reuse passwords across sites.
- `role = Column(String(32), nullable=False)` — **What:** which of the four roles this user is. **Why this way:** a `String` with a shared `VALID_ROLES` constant is the simplest role system; an enum type is heavier but equivalent here. **What breaks:** if this were a free-form string, a signup bug could create role "Customer " (trailing space) that never matches `"customer"` — locking the user out with no error.
- `restaurants = relationship("Restaurant", back_populates="owner")` — **What:** tells SQLAlchemy "one user has many restaurants" so you can write `user.restaurants` and get them all. **Why this way:** the alternative is a hand-written JOIN query everywhere you need a user's restaurants. **What breaks:** every place repeating the JOIN by hand is a place where one typo silently returns wrong rows instead of an error.
- `deliveries = relationship("Delivery", back_populates="driver")` — **What:** same pattern, for the deliveries the user performs as a rider. Same reasoning as above.

## `Restaurant` — the `restaurants` table

```python
class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True)                 # same pattern as User.id
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)             # same pattern as User.name
    address = Column(String(255), nullable=False)
    cuisine = Column(String(128), nullable=False)
    rating = Column(Float, default=0.0)

    owner = relationship("User", back_populates="restaurants")
    menu_items = relationship("MenuItem", back_populates="restaurant")
```

- `user_id = Column(Integer, ForeignKey("users.id"), nullable=False)` — **What:** a **foreign key** — this column holds the id of the user who owns this restaurant, and the database refuses values that don't exist in `users.id`. **Why this way:** FKs make the database itself enforce "you can't point a restaurant at a nonexistent owner." **What breaks:** without the FK, an orphaned `user_id` would pass silently and `restaurant.owner` would come back `None` — a bug you'd only discover in the UI.
- `rating = Column(Float, default=0.0)` — **What:** average rating; `default` fills it in at the ORM level when no value is given. **Why this way:** Float (not Integer) allows 4.3-star ratings; a default keeps new restaurants sensible. **What breaks:** if it were nullable and un-defaulted, the frontend's "★ 4.5" rendering would crash on `None` for brand-new restaurants.

## `MenuItem` — the `menu_items` table

```python
class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True)                 # same pattern as User.id
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    name = Column(String(255), nullable=False)             # same pattern as User.name
    price = Column(Float, nullable=False)
    prep_time_min = Column(Integer, nullable=False)

    restaurant = relationship("Restaurant", back_populates="menu_items")
```

- `price = Column(Float, nullable=False)` — **What:** price in ₹. **Why this way:** Float is the quick-and-dirty money type; real payment systems use Integer paise or Numeric to avoid floating-point rounding (`0.1 + 0.2 != 0.3`). **What breaks:** money as Float can drift by fractions of a rupee across many arithmetic steps — acceptable for a demo total, wrong for accounting. (Noted here so you can talk about it; not changed, to keep the diff small.)
- `prep_time_min = Column(Integer, nullable=False)` — **What:** how long this dish takes to cook; it feeds the ML ETA feature `prep_time_min`. **Why this way:** Integer minutes is the natural unit. **What breaks:** as a Float you'd invite 2.7-minute nonsense values; as NULL the ETA service would have to guess.

## `Order` — the `orders` table (the important one — it changed)

```python
class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)                 # same pattern as User.id
    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    delivery_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(32), nullable=False, default="PLACED")
    total = Column(Float, nullable=False, default=0.0)
    coupon_code = Column(String(255), nullable=True)
    discount_amount = Column(Float, nullable=False, default=0.0)
    payment_method = Column(String(16), nullable=False, default="COD")      # NEW
    payment_status = Column(String(16), nullable=False, default="PENDING")  # NEW
    payment_id = Column(String(64), nullable=True)                          # NEW
    delivery_lat = Column(Float, nullable=True)
    delivery_lng = Column(Float, nullable=True)
    delivery_address = Column(String(255), nullable=True)
    delivery_phone = Column(String(15), nullable=True)      # NEW
    delivery_city = Column(String(64), nullable=True)       # NEW
    delivery_state = Column(String(64), nullable=True)      # NEW
    delivery_pincode = Column(String(10), nullable=True)    # NEW
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    customer = relationship("User", foreign_keys=[customer_id])
    restaurant = relationship("Restaurant")
    assigned_driver = relationship("User", foreign_keys=[delivery_id])
    items = relationship("OrderItem", back_populates="order")
```

- `delivery_id = Column(..., nullable=True)` — **What:** the id of the rider assigned to this order — nullable because a fresh order has no rider yet. **Why this way:** an order *must* have a customer, but *may* not have a rider. **What breaks:** if this were `nullable=False`, you couldn't create an order until a rider existed — breaking the whole checkout flow.
- `status = Column(String(32), nullable=False, default="PLACED")` — **What:** lifecycle state, validated against `VALID_ORDER_STATUSES` at the API layer. **Why this way:** a default of `PLACED` means code that forgets to set it still creates a sensible order. **What breaks:** without a default and a shared constant, an unset status would be NULL and every `if order.status == ...` comparison would silently be false.
- `payment_method = Column(String(16), nullable=False, default="COD")` — **What (NEW):** "COD" or "RAZORPAY". **Why this way:** `String(16)` + the `VALID_PAYMENT_METHODS` constant mirrors the existing status/role pattern — consistent, no migration of types. **What breaks:** as a free string, a frontend bug sending "Cash On Delivery" would never match `"COD"` and payments would break invisibly.
- `payment_status = Column(String(16), nullable=False, default="PENDING")` — **What (NEW):** lifecycle of the money: PENDING → PAID, or PENDING → FAILED, or REFUNDED. **Why this way:** separate from `status` because an order can be PAID and still CANCELLED (needs a refund decision). **What breaks:** cramming payment state into `status` would make "delivered but unpaid" impossible to represent.
- `payment_id = Column(String(64), nullable=True)` — **What (NEW):** the gateway's transaction id (e.g. a Razorpay payment id) for lookup/reconciliation. **Why this way:** nullable because COD has no gateway id; String because gateway ids aren't integers. **What breaks:** without it you can't answer "which Razorpay transaction belongs to order 42?" when reconciling.
- `delivery_phone / delivery_city / delivery_state / delivery_pincode` — **What (NEW):** structured Indian address fields, because a single free-text `delivery_address` can't be validated or displayed in a standard Indian address card. **Why this way:** `pincode` is `String(10)` not Integer — pincodes start with 0 and must keep leading zeros, and integer columns would strip them. **What breaks:** an Integer pincode column silently turns `"560001"` into `560001` — and worse, `"000001"` into `1`.
- `created_at = Column(DateTime, nullable=False, default=datetime.utcnow)` — **What:** a timestamp stamp set at row creation. **Why this way:** `default=` runs in Python when the ORM inserts; it's the standard "created_at" pattern. **What breaks:** without it, ordering by "newest first" needs a column that doesn't exist.

## `OrderItem` — the `order_items` table

```python
class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)                 # same pattern as User.id
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem")
```

- `price = Column(Float, nullable=False)` — **What:** the unit price *snapshot at order time*. **Why this way:** it's copied from the menu into the order so a future menu price change doesn't rewrite history. **What breaks:** if you only linked to `menu_items.price` live, a restaurant raising prices would retroactively change past orders' totals.

## `Delivery` — the `deliveries` table (the brief's "riders" — kept as `deliveries` by design decision)

```python
class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True)                 # same pattern as User.id
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    pickup_time = Column(DateTime, nullable=True)
    delivered_time = Column(DateTime, nullable=True)

    driver = relationship("User", back_populates="deliveries")
    trip_logs = relationship("TripLog", back_populates="delivery")
```

- `pickup_time / delivered_time` nullable — **What:** the rider's timestamps, which only exist once the ride actually happens. **Why this way:** `nullable=True` represents "not yet" without inventing a fake date. **What breaks:** defaulting to epoch or `datetime.min` would break "was this delivered?" checks and time-since-pickup math.
- **Why `deliveries` and not `riders`:** the assignment is one row per *delivery task* (an order that gets delivered), not one row per rider; the rider is `driver_id`. Renaming to `riders` would have meant renaming columns and touching every query — decided to keep existing names and note the mapping.

## `TripLog` — the `trip_logs` table (the brief's "tracking_events")

```python
class TripLog(Base):
    __tablename__ = "trip_logs"

    id = Column(Integer, primary_key=True)                 # same pattern as User.id
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    delivery = relationship("Delivery", back_populates="trip_logs")
```

- **What:** the rider's breadcrumb trail — one row per simulated GPS fix. **Why this way:** `delivery_id` groups the trail to one trip; `lat`/`lng` are Float because coordinates are decimals. **What breaks:** without `timestamp`, you can't animate the map by time or replay a trip.

## `PromoCode` — the `promo_codes` table

```python
class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True)                 # same pattern as User.id
    code = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    discount_type = Column(String(16), nullable=False, default="percent")
    discount_value = Column(Float, nullable=False)
    min_order_value = Column(Float, nullable=False, default=0.0)
    max_discount = Column(Float, nullable=True)
    valid_until = Column(Date, nullable=True)
    usage_limit = Column(Integer, nullable=True)
    times_used = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

- `code ... unique=True` — **What:** no two promos share a code. **Why this way:** the code is looked up by users and must be unambiguous. **What breaks:** duplicate codes make `promo.by_code(code)` return two rows — either an error or a random pick.
- `discount_type = "percent" | "fixed"`, `discount_value`, `max_discount`, `min_order_value` — **What:** the promo rules. **Why this way:** storing rules as columns (not baked into code) means new promos need no code change. **What breaks:** hardcoding WELCOME10's math in the router means every new promo needs a code review + deploy.
- `valid_until = Column(Date, nullable=True)` — **What:** expiry; NULL = never expires. **Why this way:** Date (not DateTime) is fine for "expires end of day". **What breaks:** as a string, comparisons like `valid_until > today` would be lexicographic and silently wrong on "2026-9-1" vs "2026-10-1".

## `Review` — the `reviews` table

```python
class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)                 # same pattern as User.id
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    order = relationship("Order")
    user = relationship("User")
    restaurant = relationship("Restaurant")
```

- `rating = Column(Integer, nullable=False)` — **What:** 1–5 stars (validated to that range by the API's Pydantic schema). **Why this way:** Integer avoids 3.7-star reviews. **What breaks:** as Float, `sum(rating)/count` math gets messy, and the API range check is the only guard against 9.
- Three FKs on one row — **What:** the review links to the order, the reviewer, and the restaurant. **Why this way:** FKs enforce that all three must exist. **What breaks:** dropping any FK means a review can dangle and `review.restaurant` returns None in the UI.

## `SavedAddress` — the `saved_addresses` table (added by the concurrent process, explained because it's part of the layer)

```python
class SavedAddress(Base):
    __tablename__ = "saved_addresses"

    id = Column(Integer, primary_key=True)                 # same pattern as User.id
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    label = Column(String(64), nullable=False)
    address = Column(String(255), nullable=False)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User")
```

- `label` — **What:** "Home", "Work", … so users can pick a saved place by name. **Why this way:** humans remember names better than coordinates. **What breaks:** without a label, the address picker is a wall of text.
- `lat/lng` nullable — **What:** stored coordinates for map placement. **Why this way:** a saved address *should* have coordinates, but an old row might not — nullable avoids a migration that forces backfill. **What breaks:** forcing non-null would break existing rows and require a guess.

---

# `backend/alembic/versions/b3e7c2a9f4d1_add_payment_and_address_fields.py` — the new migration (created)

```python
"""Add payment + structured address fields to orders

Revision ID: b3e7c2a9f4d1
Revises: 38b4adc0fd48
Create Date: 2026-08-09 12:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3e7c2a9f4d1'
down_revision: Union[str, None] = '38b4adc0fd48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('payment_method', sa.String(length=16), nullable=False, server_default='COD'))
    op.add_column('orders', sa.Column('payment_status', sa.String(length=16), nullable=False, server_default='PENDING'))
    op.add_column('orders', sa.Column('payment_id', sa.String(length=64), nullable=True))
    op.add_column('orders', sa.Column('delivery_phone', sa.String(length=15), nullable=True))
    op.add_column('orders', sa.Column('delivery_city', sa.String(length=64), nullable=True))
    op.add_column('orders', sa.Column('delivery_state', sa.String(length=64), nullable=True))
    op.add_column('orders', sa.Column('delivery_pincode', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'delivery_pincode')
    op.drop_column('orders', 'delivery_state')
    op.drop_column('orders', 'delivery_city')
    op.drop_column('orders', 'delivery_phone')
    op.drop_column('orders', 'payment_id')
    op.drop_column('orders', 'payment_status')
    op.drop_column('orders', 'payment_method')
```

- `revision` / `down_revision` — **What:** each migration has a unique id and records which migration it sits on top of; Alembic builds the chain from these. **Why this way:** `down_revision = '38b4adc0fd48'` (the previous head) keeps the chain linear and replayable. **What breaks:** two migrations claiming the same parent creates a fork Alembic refuses to auto-merge — the classic "multiple heads" error.
- `server_default='COD'` in `upgrade()` — **What:** this is the crucial detail. The column is `nullable=False`, but `orders` already has rows. `server_default` tells Postgres "fill every existing row with 'COD'." **Why this way:** adding a NOT NULL column to a non-empty table without a default fails on the existing rows. **What breaks:** without `server_default`, `alembic upgrade head` errors with "column ... contains null values" on any database that has orders.
- The `downgrade()` — **What:** reverses `upgrade()` so you can roll back. **Why this way:** migrations must be reversible; that's the whole point of Alembic over ad-hoc `ALTER TABLE`. **What breaks:** a one-way migration leaves you stuck on a broken schema with no undo.
- Columns are dropped in reverse order of addition — **What:** purely cosmetic; there's no dependency between the columns. **Why this way:** matches Alembic's own generated style. Nothing breaks either way here — called out honestly as not meaningful.

**How this connects:** `models.py` is the *source of truth* for the schema; the migration is the *replayable recipe* to make a real database match it. Alembic applies this file to a running Postgres with `alembic upgrade head` (the backend Dockerfile runs this on boot). If this migration were deleted after being applied, `alembic downgrade -1` couldn't roll back, and a fresh database would be missing the new columns — every insert of an order would fail with "column payment_method does not exist."

---

## How the whole layer connects

```
backend/config.py ──▶ backend/db.py ──▶ backend/models.py ──▶ (used by) backend/routers/*.py
                       │                     │
                       │                     └── matches ──▶ backend/alembic/versions/*.py
                       └── DATABASE_URL ──▶ PostgreSQL (Postgres, via Docker or Render)
```

- Routers import `get_db` and `models`; the ORM maps Python objects to rows; Alembic keeps the real database in sync with `models.py`.
- If `models.py` gained a column without a migration → runtime errors on insert. If a migration ran without `models.py` → the ORM ignores the extra column (harmless until code uses it). The rule: **change both together, in the same commit.**

## What we did and didn't do in this layer

- **Added:** `payment_method`, `payment_status`, `payment_id` and structured `delivery_phone/city/state/pincode` on `orders`, with a matching migration.
- **Decided:** kept `deliveries`/`trip_logs` names (brief's "riders"/"tracking_events") to avoid a risky rename migration.
- **Noted, not changed:** `price`/`total` as Float is fine for a demo but real money should be Integer paise — flag for the payments layer.
