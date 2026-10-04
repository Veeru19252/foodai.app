# FoodAI — Render Deploy Checklist

Operational checklist for shipping `foodai.app` (FastAPI + Next.js + Postgres 16)
to Render via the blueprint in [`render.yaml`](./render.yaml).

## 1. Pre-deploy validation (run locally, in order)

```bash
# Backend — unit/integration tests
.venv/bin/python -m pytest -q          # expect all to pass (329 at time of writing)

# Frontend — production build
cd frontend && npm run build            # expect "Compiled successfully", 14 pages + /_not-found

# E2E — Playwright flows (backend :8000 + frontend :3000 running)
# CI uses --grep-invert so it never needs the seeded screenshots run.
cd frontend && npx playwright test --grep-invert "@screenshots"   # expect 4 passed

# Docs screenshots (regenerates docs/screenshots/*.png) — local only
cd frontend && npx playwright test e2e/screenshots.spec.ts
```

- [ ] `git status` shows a clean tree (model/metrics churn from test runs is
      expected and can be left uncommitted or re-committed on the next retrain)
- [ ] `main` is pushed to `origin` (`git push origin main`)

## 2. Deploy (one-click blueprint)

1. Go to [render.com](https://render.com) → **New** → **Blueprint**.
2. Connect the `Veeru19252/foodai.app` GitHub repo.
3. Render provisions three services from `render.yaml`:
   - `foodai-db` — PostgreSQL 16 (free plan)
   - `foodai-backend` — FastAPI, runs `alembic upgrade head` then uvicorn
   - `foodai-frontend` — Next.js, `npm ci && npm run build`, serves `npm run start`
4. Wait for the first deploy to finish (backend must be healthy before the
   frontend's build completes its API smoke checks, if any).
5. The form asks for `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` (they are
   `sync: false` in the blueprint). **Any non-empty placeholder works** — see
   the payments note below. You do not need a Razorpay account.

Steps 1–6 with the checks that usually catch people are scripted:

```bash
./scripts/render-deploy-wizard.sh
```

It walks the blueprint creation, tells you what to paste, compares the URLs
Render actually assigns against the ones the blueprint hardcodes, and reads
back `/api/health`.

Expected URLs (default service names):

| Service | URL |
|---|---|
| Frontend | `https://foodai-frontend.onrender.com` |
| Backend health | `https://foodai-backend.onrender.com/api/health` |
| API docs | `https://foodai-backend.onrender.com/docs` |

## 3. Post-deploy verification

- [ ] `GET /api/health` returns `200`. It runs a real `SELECT 1`, so a `503`
      means the database is unreachable rather than the app being broken; a
      `404` just means the service is not live yet (Render 404s a subdomain
      with no live service, which is normal mid-deploy).
- [ ] Backend logs show `alembic upgrade head` applying migrations.
- [ ] Frontend loads; `NEXT_PUBLIC_API_URL` points at the backend and the
      backend's `CORS_ORIGINS` matches the frontend origin exactly, scheme
      included. A mismatch fails at CORS rather than at build, so it presents
      as an unexplained network error.
- [ ] Place an order → live tracking page shows the ETA + map
- [ ] Driver flow: assign order → "Share live location" updates the customer's
      tracking badge to **LIVE GPS**
- [ ] WebSocket tracking reconnects after a dropped connection (REST poll kicks
      in within ~5s; WS auto-reconnects within ~2s)

### There are no demo accounts on a production deploy

`SEED_DEMO_DATA` defaults **off** when `ENVIRONMENT=production`, so the
`seed_if_empty()` call on startup returns without creating anything. The
database starts empty — no admin, no restaurant, no driver, no demo password.
Verify with accounts you register yourself:

- [ ] Sign up as a **customer** → add to cart → check out → tracking updates
- [ ] Sign up as a **restaurant** owner → the new order appears
- [ ] Sign up as a **driver** → only your own deliveries are visible

`SELF_REGISTER_ROLES` in `backend/routers/auth.py` allows `customer`,
`restaurant` and `delivery`, so all three flows work on a fresh instance.

Admin screens are **not** reachable on a fresh deploy: role promotion is
`PATCH /admin/users/{user_id}/role`, which itself requires an admin. To get one,
set these on `foodai-backend` and redeploy:

```
SEED_DEMO_DATA=1
DEMO_USER_PASSWORD=<a strong password>    # seeding refuses the default in production
```

Note that the accounts persist afterwards — `seed_if_empty` only runs against
an empty user table — so change that password or delete those users rather than
assuming removing the flag removes them.

### Payments: Cash on Delivery only

Razorpay is deliberately unavailable on a public deploy.
`backend/routers/payments.py` mints its own `razorpay_order_id` and never calls
Razorpay's Orders API, so with `PAYMENTS_TEST_MODE` off (the production default)
the intent comes back `test_mode: false` and the frontend raises *"Razorpay live
mode is not configured in this build"*. Cash on Delivery is unaffected and needs
no keys.

Setting `PAYMENTS_TEST_MODE=1` would make the simulated checkout work, but it
selects a secret hardcoded in `frontend/src/app/checkout/page.tsx` — public, in
the shipped JS bundle — which would let anyone forge a payment signature for any
order. Keep it off in production.

## 4. Rollback

- Push a revert commit (or an earlier commit) to `main` — Render auto-deploys.
- To roll back a specific service: Render dashboard → service → **Manual
      Deploy** → **Deploy previous commit**.

## 5. Maintenance notes

- Free web services spin down after ~15 min idle; the first request after
  idle takes a few seconds to wake.
- Free Postgres data **expires after 30 days** — upgrade `foodai-db` to a paid
  plan for a persistent demo.
- If Render assigns different service URLs, update `NEXT_PUBLIC_API_URL`
  (frontend env) and `CORS_ORIGINS` (backend env) and redeploy.
- Live GPS columns are covered by migration `b1f4e5d00ff0`; the blueprint runs
  `alembic upgrade head` on every deploy, so schema changes apply automatically.
