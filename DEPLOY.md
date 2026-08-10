# FoodAI — Render Deploy Checklist

Operational checklist for shipping `foodai.app` (FastAPI + Next.js + Postgres 16)
to Render via the blueprint in [`render.yaml`](./render.yaml).

## 1. Pre-deploy validation (run locally, in order)

```bash
# Backend — unit/integration tests
.venv/bin/python -m pytest -q          # expect 67 passed

# Frontend — production build
cd frontend && npm run build            # expect "Compiled successfully", 16/16 routes

# E2E — Playwright flows (backend :8000 + frontend :3000 running)
cd frontend && npx playwright test      # expect 4 passed
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

Expected URLs (default service names):

| Service | URL |
|---|---|
| Frontend | `https://foodai-frontend.onrender.com` |
| Backend health | `https://foodai-backend.onrender.com/api/health` |
| API docs | `https://foodai-backend.onrender.com/docs` |

## 3. Post-deploy verification

- [ ] `GET /api/health` returns `200` (wake the free web service on first hit)
- [ ] Backend logs show `alembic upgrade head` applying migrations, then seed
      data for demo accounts
- [ ] Frontend loads; `NEXT_PUBLIC_API_URL` points at the backend (check the
      backend `CORS_ORIGINS` matches the frontend origin)
- [ ] Login works with a seeded demo account
- [ ] Place an order → live tracking page shows the ETA + map
- [ ] Driver flow: assign order → "Share live location" updates the customer's
      tracking badge to **LIVE GPS**
- [ ] Admin → "Retrain model" returns a metrics summary (`outputs/metrics_forecast.json`)
- [ ] WebSocket tracking reconnects after a dropped connection (REST poll kicks
      in within ~5s; WS auto-reconnects within ~2s)

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
