"use client";

import { useEffect, useState } from "react";
import { adminApi, mlApi } from "@/lib/api";
import type { AdminOverview, AdminUser, ForecastSeries, Role } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";
import StatusBadge from "@/components/StatusBadge";

const ZONE_COLORS: Record<string, string> = {
  A: "bg-brand-600",
  B: "bg-emerald-500",
  C: "bg-amber-500",
  D: "bg-violet-500",
  E: "bg-sky-500",
};

const ROLE_COLORS: Record<string, string> = {
  customer: "bg-blue-500/15 text-blue-300",
  restaurant: "bg-amber-500/15 text-amber-300",
  delivery: "bg-violet-500/15 text-violet-300",
  admin: "bg-red-500/15 text-red-300",
};

export default function AdminPage() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [forecast, setForecast] = useState<ForecastSeries | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [userFilter, setUserFilter] = useState("");
  const [orders, setOrders] = useState<
    {
      id: number;
      customer_name: string;
      restaurant_name: string;
      status: string;
      total: number;
      created_at: string;
    }[]
  >([]);
  const [error, setError] = useState("");
  const [retrainBusy, setRetrainBusy] = useState(false);
  const [retrainResult, setRetrainResult] = useState<{
    samples: { corpus: number; live: number; total: number };
    metrics: {
      moving_average: { mae: number; rmse: number; mape: number };
      xgboost: { mae: number; rmse: number; mape: number };
    };
    retrained_at: string;
  } | null>(null);
  const [retrainError, setRetrainError] = useState("");

  useEffect(() => {
    adminApi
      .overview()
      .then(setOverview)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load dashboard")
      );
    adminApi.orders().then(setOrders).catch(() => setOrders([]));
    adminApi.users().then(setUsers).catch(() => setUsers([]));
    mlApi
      .forecastSeries(6)
      .then(setForecast)
      .catch(() => setForecast(null));
  }, []);

  async function changeRole(userId: number, role: Role) {
    setError("");
    try {
      await adminApi.updateUserRole(userId, role);
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, role } : u))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update role");
    }
  }

  async function runRetrain() {
    setRetrainBusy(true);
    setRetrainError("");
    setRetrainResult(null);
    try {
      const result = await mlApi.retrainForecast();
      setRetrainResult(result);
      // The model changed under the forecast view — refresh it.
      mlApi
        .forecastSeries(6)
        .then(setForecast)
        .catch(() => undefined);
    } catch (err) {
      setRetrainError(
        err instanceof Error ? err.message : "Retraining failed"
      );
    } finally {
      setRetrainBusy(false);
    }
  }

  const filteredUsers = users.filter((u) =>
    `${u.name} ${u.email} ${u.role}`
      .toLowerCase()
      .includes(userFilter.trim().toLowerCase())
  );

  const statCards = overview
    ? [
        { label: "Total orders", value: overview.total_orders },
        { label: "Revenue", value: `₹${overview.revenue.toFixed(0)}` },
        { label: "Active deliveries", value: overview.active_deliveries },
        { label: "Restaurants", value: overview.restaurants },
      ]
    : [];

  return (
    <ProtectedRoute role="admin">
      <h1 className="mb-6 text-2xl font-bold">Admin dashboard</h1>

      {error && (
        <p className="mb-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {statCards.map((s) => (
          <div key={s.label} className="rounded-2xl border border-line bg-card p-5">
            <p className="text-xs text-muted">{s.label}</p>
            <p className="text-2xl font-bold">{s.value}</p>
          </div>
        ))}
      </div>

      {overview && (
        <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="rounded-2xl border border-line bg-card p-5">
            <h2 className="mb-3 font-semibold">Users by role</h2>
            <div className="flex gap-3">
              {Object.entries(overview.users).map(([role, count]) => (
                <div key={role} className="rounded-lg bg-surface px-3 py-2 text-sm">
                  <span className="font-semibold">{count}</span>{" "}
                  <span className="text-muted">{role}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-2xl border border-line bg-card p-5">
            <h2 className="mb-3 font-semibold">Orders by status</h2>
            <div className="flex flex-wrap gap-2">
              {Object.entries(overview.orders_by_status).map(([status, count]) => (
                <span key={status} className="flex items-center gap-2">
                  <StatusBadge status={status} />
                  <span className="text-sm font-semibold">{count}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {forecast && (
        <div className="mb-6 rounded-2xl border border-line bg-card p-5">
          <div className="mb-1 flex items-center justify-between">
            <h2 className="font-semibold">Demand forecast (next 6 hours)</h2>
            <span className="text-xs text-faint">
              AI · XGBoost demand model
            </span>
          </div>
          <p className="mb-4 text-xs text-muted">
            Predicted orders per delivery zone, per hour.
            {forecast.fallback &&
              " (using the moving-average fallback — the trained model is unavailable)"}
          </p>

          <div className="space-y-2">
            {forecast.series.map((item) => {
              const maxTotal = Math.max(
                1,
                ...forecast.series.map((s) =>
                  Object.values(s.zones).reduce((a, b) => a + b, 0)
                )
              );
              const total = Object.values(item.zones).reduce((a, b) => a + b, 0);
              return (
                <div key={item.label} className="flex items-center gap-3">
                  <div className="w-14 shrink-0 text-right text-xs text-muted">
                    {item.label}
                  </div>
                  <div className="flex h-6 flex-1 overflow-hidden rounded-full bg-line">
                    {Object.entries(item.zones).map(([zone, count]) => (
                      <div
                        key={zone}
                        className={`${ZONE_COLORS[zone] ?? "bg-elevated"} h-full`}
                        style={{ width: `${(count / maxTotal) * 100}%` }}
                        title={`Zone ${zone}: ${count}`}
                      />
                    ))}
                  </div>
                  <div className="w-14 shrink-0 text-xs font-semibold text-secondary">
                    {total.toFixed(1)}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-3 flex flex-wrap gap-3">
            {Object.entries(ZONE_COLORS).map(([zone, color]) => (
              <span key={zone} className="flex items-center gap-1.5 text-xs text-muted">
                <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
                Zone {zone}
              </span>
            ))}
          </div>

          <div className="mt-4 border-t border-line pt-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-foreground">
                  Retrain demand model
                </p>
                <p className="text-xs text-faint">
                  Re-runs the XGBoost training on the historical corpus plus
                  every live order, then swaps the model the forecast reads.
                </p>
              </div>
              <button
                onClick={runRetrain}
                disabled={retrainBusy}
                className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
              >
                {retrainBusy ? "Training…" : "Retrain model"}
              </button>
            </div>

            {retrainError && (
              <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {retrainError}
              </p>
            )}

            {retrainResult && (
              <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="rounded-xl bg-surface p-3">
                  <p className="text-xs text-muted">Samples</p>
                  <p className="text-sm font-semibold">
                    {retrainResult.samples.total.toLocaleString()} orders
                  </p>
                  <p className="text-xs text-faint">
                    {retrainResult.samples.corpus.toLocaleString()} historical ·{" "}
                    {retrainResult.samples.live.toLocaleString()} live
                  </p>
                </div>
                <div className="rounded-xl bg-surface p-3">
                  <p className="text-xs text-muted">XGBoost MAE</p>
                  <p className="text-sm font-semibold">
                    {retrainResult.metrics.xgboost.mae.toFixed(3)}
                  </p>
                  <p className="text-xs text-faint">
                    baseline (moving avg):{" "}
                    {retrainResult.metrics.moving_average.mae.toFixed(3)}
                  </p>
                </div>
                <div className="rounded-xl bg-surface p-3">
                  <p className="text-xs text-muted">XGBoost MAPE</p>
                  <p className="text-sm font-semibold">
                    {(retrainResult.metrics.xgboost.mape * 100).toFixed(1)}%
                  </p>
                  <p className="text-xs text-faint">
                    baseline:{" "}
                    {(retrainResult.metrics.moving_average.mape * 100).toFixed(1)}%
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="mb-6 rounded-2xl border border-line bg-card p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-semibold">Users</h2>
          <input
            type="text"
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value)}
            placeholder="Filter by name, email or role"
            className="w-56 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-foreground placeholder:text-faint focus:border-brand-500 focus:outline-none"
          />
        </div>
        <div className="max-h-80 divide-y divide-line overflow-y-auto">
          {filteredUsers.length === 0 ? (
            <p className="py-4 text-sm text-faint">No users match.</p>
          ) : (
            filteredUsers.map((u) => (
              <div
                key={u.id}
                className="flex items-center justify-between gap-3 py-2 text-sm"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium">{u.name}</p>
                  <p className="truncate text-xs text-muted">{u.email}</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      ROLE_COLORS[u.role] ?? "bg-surface text-muted"
                    }`}
                  >
                    {u.role}
                  </span>
                  <select
                    value={u.role}
                    onChange={(e) => changeRole(u.id, e.target.value as Role)}
                    className="rounded-lg border border-line bg-surface px-2 py-1 text-xs text-foreground focus:border-brand-500 focus:outline-none"
                    aria-label={`Change role for ${u.name}`}
                  >
                    <option value="customer">customer</option>
                    <option value="restaurant">restaurant</option>
                    <option value="delivery">delivery</option>
                    <option value="admin">admin</option>
                  </select>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="rounded-2xl border border-line bg-card p-5">
        <h2 className="mb-3 font-semibold">Recent orders</h2>
        <div className="divide-y divide-line">
          {orders.slice(0, 10).map((o) => (
            <div key={o.id} className="flex items-center justify-between py-2 text-sm">
              <span>
                #{o.id} · {o.customer_name} ← {o.restaurant_name}
              </span>
              <span className="flex items-center gap-3">
                <span className="font-semibold">₹{o.total.toFixed(0)}</span>
                <StatusBadge status={o.status} />
              </span>
            </div>
          ))}
        </div>
      </div>
    </ProtectedRoute>
  );
}
