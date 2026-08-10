# FoodAI Teaching Guide — Part 4: The Frontend Layer

> **Prerequisites:** Parts 1–3. This part walks the whole Next.js frontend: how it talks to
> the FastAPI backend, how auth and cart state are managed, and — the part that ties the app
> together — the two "live" experiences the backend enables: **payments** (COD + test-mode
> Razorpay with a real HMAC signature check) and **live rider tracking** (Leaflet map + WebSocket
> positions + ML ETA).
>
> **The single most important design idea in this layer:** every page is a *thin client*.
> The frontend renders state that the API already computed — order totals, delivery fees, ETAs,
> demand forecasts, payment status. When something is expensive (ML prediction, routing, payment
> signature verification) it happens **server-side**; the browser just displays it and lets the
> user act. The one deliberate exception is the test-mode Razorpay signature, which we generate
> in the browser to prove the verify() endpoint really checks it.

---

## The frontend at a glance

```text
Next.js 14 (App Router) + TypeScript + Tailwind, all under frontend/src/

  lib/            ── plain TS, no React where possible
    api.ts        ── fetch wrapper (auto token refresh) + one typed group per backend router
    auth.tsx      ── AuthProvider context (login / register / logout / current user)
    cart.tsx      ── CartProvider context (multi-restaurant cart, grouped by restaurant)
    cn.ts         ── tiny class-name joiner (shadcn-style, dependency-free)
    types.ts      ── shared TypeScript interfaces mirroring the backend Pydantic schemas

  components/     ── reusable React pieces
    ProtectedRoute.tsx     role-gated wrapper (customer / restaurant / delivery / admin)
    StatusBadge.tsx        order-status pill (PLACED → CANCELLED colour map)
    Navbar.tsx             top navigation + NotificationBell
    LocationPicker.tsx     address preset chips + lat/lng for delivery
    RestaurantMenuModal.tsx  browsing a restaurant's menu without leaving the page
    ReviewModal.tsx        rating + comment for a delivered order
    TrackingMap.tsx        Leaflet map: route polyline, origin/dest markers, live rider
    PaymentMethodPicker.tsx  COD vs Razorpay radio cards (this layer)
    ui/                    dependency-free shadcn-style kit: button, card, badge

  app/            ── routes (one folder per path)
    page.tsx             landing/home
    login | register     auth forms
    restaurants/         customer catalog + recommendations
    checkout/            cart → order (payments + scheduling + surge fee)
    orders/              "My orders" list (timeline previews, receipts, reviews, payments)
    tracking/[orderId]/  LIVE map + ML ETA + "why this ETA" SHAP panel
    driver/              delivery dashboard (earnings, start delivery, Navigate)
    restaurant/{orders,menu,offers,analytics}  restaurant-side dashboards
    admin/               admin overview + user management
```

The golden rule in this codebase: **`"use client"` at the top of every interactive page**,
because all data fetching happens in the browser (the backend has no server-side rendering).
Next.js App Router still gives us file-based routing and code-splitting for free.

---

## File 1 — `src/lib/api.ts` (the typed API client)

> Every request in the app flows through one function. It stores the JWT in localStorage,
> attaches it as a Bearer token, and **refreshes it once automatically** if it expired, then
> retries the original request. That's why pages never handle "token expired" errors.

```ts
async function api<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const token = readStorage(ACCESS_KEY);
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (response.status === 401 && retry) {
    // expired access token → use the refresh token once, then retry
    const refreshed = await refreshTokens();
    if (refreshed) return api<T>(path, options, false);
  }
  if (!response.ok) throw new Error(...);   // surface the backend detail message
  return response.json();
}
```

The endpoint groups mirror the backend routers **one to one**:

| Group           | Backend router    | Example calls                                    |
| --------------- | ----------------- | ------------------------------------------------ |
| `authApi`       | auth.py           | login / register                                 |
| `catalogApi`    | restaurants.py    | list restaurants, cuisines, menu                 |
| `restaurantApi` | restaurants.py    | my restaurant, offers, analytics                 |
| `ordersApi`     | orders.py         | create / batch, cancel, reorder, surge, receipt  |
| `paymentsApi`   | payments.py       | payment status, COD confirm/cancel, Razorpay     |
| `reviewsApi`    | reviews.py        | create review, reviews for restaurant            |
| `addressesApi`  | addresses.py      | saved delivery addresses                         |
| `trackingApi`   | tracking.py       | tracking state (REST)                            |
| `mlApi`         | ml.py             | forecast series, recommendations, order ETA      |
| `adminApi`      | admin.py          | overview, users, role changes                    |

**The pattern to learn:** a plain object of closures — `api<T>(path, { method, body })`.
No axios, no react-query, no generated SDK. TypeScript is the only client-side contract.

---

## File 2 — `src/lib/auth.tsx` and `src/lib/cart.tsx` (context providers)

Both follow the same shape: a `createContext`, a provider component mounted once in
`app/layout.tsx`, and a `useX()` hook that throws if used outside the provider.

- **Auth** keeps `user`, `token`, `loading` in React state, hydrated once from localStorage.
  `ProtectedRoute` reads it and bounces the user to the right home for their role if they are
  not allowed on the current page:

```tsx
const ROLE_HOME = {
  customer: "/restaurants",
  restaurant: "/restaurant/orders",
  delivery: "/driver",
  admin: "/admin",
};
```

- **Cart** stores lines (`{ menu_item_id, restaurant_id, restaurant_name, name, price, qty }`)
  and derives `groups` — the cart **grouped by restaurant**, which is why checkout can place one
  order per restaurant via `ordersApi.createBatch`. Each group becomes its own `OrderDetail`
  with its own rider.

---

## File 3 — the UI kit (`components/ui/`)

> shadcn/ui is the most popular React component library on the web — and it is **just
> copy-paste source code**, no dependency required. FoodAI ships a tiny dependency-free
> version of its three workhorse components so the teaching code stays installable offline.

- `cn.ts` — `cn("a", cond && "b", { c: isC }, ["d"])` joins class names.
- `button.tsx` — `Button` with `variant` (`primary|secondary|outline|ghost|danger`) and `size`.
- `card.tsx` — `Card / CardHeader / CardTitle / CardContent / CardFooter`.
- `badge.tsx` — `Badge` with semantic variants (`success | warning | danger | ...`) used for
  **payment status**.

`PaymentMethodPicker` composes `Card` + `cn` into radio-style payment cards. It is the entry
point of this layer's payment UI:

```tsx
<Card className={cn("cursor-pointer p-4", active && "border-brand-600 bg-brand-50/40 ring-2 ring-brand-600")}>
  ...title, description, and a "Recommended" / "Test mode" pill per option...
</Card>
```

---

## The payment flow (this layer's star feature)

### Step 0 — where the money lives

The `Order` row itself is the payment record:

```
Order.payment_method    "COD" | "RAZORPAY"      (set at checkout)
Order.payment_status    "PENDING" | "PAID" | "FAILED" | "REFUNDED"
Order.payment_id        external ref (Razorpay payment id) when paid online
```

The customer-facing state machine:

```text
            ┌─────────────── COD ───────────────┐
            │  PENDING ──(driver collects)──► PAID
            │  PENDING ──(cancelled)────────► FAILED
checkout ───┤
            └─────────────── RAZORPAY ──────────────────────────┐
                 PENDING ──intent/verify/signature valid──► PAID
                 (verify fails or signature mismatch) ─────► FAILED
```

### Step 1 — checkout collects the choice (`checkout/page.tsx`)

The form gathers delivery details, then a `PaymentMethodPicker`, then contact + locality
(phone/city/state/pincode). `placeOrder` passes them straight into the create-batch payload:

```tsx
const res = await ordersApi.createBatch(
  groups.map((g, idx) => ({
    ...,
    payment_method: paymentMethod,          // "COD" | "RAZORPAY"
    delivery_phone: phone.trim() || undefined,
    delivery_city: city.trim() || undefined,
    delivery_state: stateName.trim() || undefined,
    delivery_pincode: pincode.trim() || undefined,
  }))
);
```

The backend validates `payment_method` against `{"COD", "RAZORPAY"}` and persists it (Part 2).
**COD orders are done at this point** — nothing else happens until the driver marks collection.

### Step 2 — Razorpay (test mode) runs a *real* verify

For `RAZORPAY` orders the checkout performs the exact three calls a production checkout would:

```tsx
// 1. create the payment intent server-side
const intent = await paymentsApi.razorpayOrder(order.id);
//    → { razorpay_order_id: "rp_order_...", amount_paise, key_id, test_mode: true }

// 2. simulate what the Razorpay Checkout SDK would do in the browser:
//    generate a payment id and sign `order_id|payment_id` with the demo secret
const mockPaymentId = `pay_${Math.random().toString(36).slice(2, 10)}`;
const signature = await simulateRazorpaySignature(intent.razorpay_order_id, mockPaymentId);

// 3. verify server-side — the backend recomputes the HMAC and compares
await paymentsApi.razorpayVerify({
  order_id: order.id,
  razorpay_order_id: intent.razorpay_order_id,
  razorpay_payment_id: mockPaymentId,
  razorpay_signature: signature,
});
```

The simulated signature is a real **HMAC-SHA256** using the same test secret the backend uses
(`foodai_demo_secret`, matching `RAZORPAY_KEY_SECRET` in `payments.py`):

```ts
async function simulateRazorpaySignature(orderId: string, paymentId: string) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(TEST_RAZORPAY_SECRET),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(`${orderId}|${paymentId}`));
  return [...new Uint8Array(signature)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
```

The backend's `razorpay/verify` does the **same** computation with the same secret and only
flips the order to `PAID` if they match — so the whole flow is real end to end, minus actual
money moving.

> **In production** you would load the official Razorpay Checkout SDK and never compute the
> signature yourself — the SDK signs on the customer's device after a genuine payment. The
> demo makes the signature visible *on purpose* so you can read how it works.

### Step 3 — status visible in "My orders" (`orders/page.tsx`)

Every order row shows a payment badge next to the delivery-status badge:

```tsx
{o.payment_status && (
  <Badge variant={o.payment_status === "PAID" ? "success"
            : o.payment_status === "FAILED" ? "danger" : "warning"}>
    {o.payment_method === "COD" ? "COD" : "Card/UPI"} · {o.payment_status}
  </Badge>
)}
```

And the action row lets the **customer** mark a COD payment collected (in a real deployment
this would be the rider's action; the endpoint is the same):

```tsx
{o.payment_method === "COD" && o.payment_status === "PENDING" && (
  <button onClick={() => markCodCollected(o.id)}>Mark COD collected</button>
)}
```

`markCodCollected` calls `paymentsApi.codConfirm(orderId)` → `POST /payments/orders/{id}/cod/confirm`
→ backend sets `payment_status = "PAID"`, then re-fetches the list so the badge flips to green.

---

## The rider navigation flow

> The customer-facing tracking page does double duty: the **driver** reaches it via the
> "Navigate" button in `driver/page.tsx`. One page, two audiences.

`driver/page.tsx` (role `delivery`):

- Polls `ordersApi.driverOrders()` every 5 seconds for assigned deliveries.
- Shows an **earnings dashboard** (per-order + per-km rates, totals, recent trips).
- Fetches **delay-prediction nudges** (`ordersApi.nudge(orderId)`) for in-flight orders and
  warns the driver when the ML says they are running late.
- "Start delivery" → `ordersApi.updateStatus(id, "OUT_FOR_DELIVERY")`.
- **"Navigate" → `/tracking/{orderId}`** — the map view described below.

`tracking/[orderId]/page.tsx`:

1. **REST bootstrap** — `trackingApi.state(orderId)` gives the route, rider position, ETA.
2. **Live WebSocket** — connects to `ws://…/ws/tracking/{id}?token=…`; each `position` frame
   moves the rider marker and advances the progress bar; a `delivered` frame closes the ride.
3. **ML explainability** — `mlApi.orderPrediction(orderId)` returns the ETA plus SHAP
   contributions; the collapsible "Why this ETA?" panel renders each feature's +/− minutes.

`TrackingMap.tsx` is a **lazy-loaded Leaflet** component (imported only in the browser):

```tsx
const L = await import("leaflet");            // dynamic import → smaller initial bundle
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map);
L.polyline(route, { color: "#ea580c", weight: 4 });   // road route from OSRM (Part 3)
L.circleMarker(start, green);  L.circleMarker(dest, red);
riderMarkerRef = L.marker([riderLat, riderLng], { icon: scooterDivIcon });
```

A follow-up effect simply calls `riderMarkerRef.current.setLatLng(...)` whenever the WebSocket
delivers a new position — Leaflet repaints; the React tree never re-renders on every move.

---

## Other pages worth a skim

- **`restaurants/page.tsx`** — catalog with cuisine filter + ML-driven recommendations
  (`mlApi.recommendations()`, each with a human-readable `reason`).
- **`restaurant/{orders,menu,offers,analytics}`** — the restaurant partner dashboard:
  incoming orders with driver assignment (manual + `auto-assign`), menu CRUD, offer management,
  and an analytics page (`/restaurants/me/analytics`) showing revenue + popular items.
- **`admin/page.tsx`** — `adminApi.overview()` stats grid + user role management.
- **`orders/page.tsx` receipt modal** — `ordersApi.receipt(orderId)` renders an itemised bill
  (food total, discount, delivery fee, surge, grand total, payment method) and can email it via
  `emailReceipt`.
- **`checkout/page.tsx` surge + scheduling** — `ordersApi.surge()` adds a dynamic delivery fee,
  and "Schedule delivery" sets `scheduled_for` so the kitchen starts at the chosen time.

---

## How the pieces fit together (one order, end to end)

```text
checkout/page.tsx  ──createBatch──►  /orders/batch  ──►  one Order per restaurant
   │  payment_method + structured address                 (status PLACED, payment PENDING)
   │
   ├─ COD        ─────────────────────────────────────────►  nothing until delivery
   └─ RAZORPAY   ──razorpayOrder──► intent ──► simulate signature
                   ──razorpayVerify──► /payments/razorpay/verify ──► payment PAID

orders/page.tsx   ──mine()──► payment badge + "Mark COD collected" per order
driver/page.tsx   ──driverOrders()──► Navigate ──► tracking/[orderId]
tracking page     ──state() + ws ──► TrackingMap (route + rider) + ML ETA + SHAP panel
```

The mental model to carry away: **the backend is the source of truth for money and movement;
the frontend is a stateless window into it.**
