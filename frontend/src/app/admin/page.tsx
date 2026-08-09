"use client";

import { useEffect, useState } from "react";
import { adminApi } from "@/lib/api";
import type { AdminOverview } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";
import StatusBadge from "@/components/StatusBadge";

export default function AdminPage() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
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

  useEffect(() => {
    adminApi
      .overview()
      .then(setOverview)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load dashboard")
      );
    adminApi.orders().then(setOrders).catch(() => setOrders([]));
  }, []);

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
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {statCards.map((s) => (
          <div key={s.label} className="rounded-2xl border border-gray-200 bg-white p-5">
            <p className="text-xs text-gray-500">{s.label}</p>
            <p className="text-2xl font-bold">{s.value}</p>
          </div>
        ))}
      </div>

      {overview && (
        <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="rounded-2xl border border-gray-200 bg-white p-5">
            <h2 className="mb-3 font-semibold">Users by role</h2>
            <div className="flex gap-3">
              {Object.entries(overview.users).map(([role, count]) => (
                <div key={role} className="rounded-lg bg-gray-50 px-3 py-2 text-sm">
                  <span className="font-semibold">{count}</span>{" "}
                  <span className="text-gray-500">{role}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-2xl border border-gray-200 bg-white p-5">
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

      <div className="rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="mb-3 font-semibold">Recent orders</h2>
        <div className="divide-y divide-gray-100">
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
