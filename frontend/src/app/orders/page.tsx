"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ordersApi } from "@/lib/api";
import type { OrderBrief } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";
import StatusBadge from "@/components/StatusBadge";

export default function OrdersPage() {
  const [orders, setOrders] = useState<OrderBrief[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    ordersApi
      .mine()
      .then(setOrders)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load orders")
      )
      .finally(() => setLoading(false));
  }, []);

  return (
    <ProtectedRoute role="customer">
      <h1 className="mb-6 text-2xl font-bold">My orders</h1>

      {error && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {loading ? (
        <p className="py-16 text-center text-gray-400">Loading…</p>
      ) : orders.length === 0 ? (
        <div className="rounded-2xl border border-gray-200 bg-white p-10 text-center">
          <p className="mb-4 text-gray-500">No orders yet.</p>
          <Link
            href="/restaurants"
            className="rounded-lg bg-brand-600 px-4 py-2 font-semibold text-white hover:bg-brand-700"
          >
            Order food
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          {orders.map((o) => (
            <Link
              key={o.id}
              href={`/tracking/${o.id}`}
              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-gray-200 bg-white px-5 py-4 shadow-sm transition hover:shadow-md"
            >
              <div>
                <p className="font-semibold">{o.restaurant_name}</p>
                <p className="text-xs text-gray-500">
                  #{o.id} ·{" "}
                  {new Date(o.created_at).toLocaleString()}
                </p>
              </div>
              <div className="flex items-center gap-4">
                <span className="font-semibold">₹{o.total.toFixed(0)}</span>
                <StatusBadge status={o.status} />
                {o.status !== "CANCELLED" && (
                  <span className="text-xs font-semibold text-brand-600">
                    Track →
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </ProtectedRoute>
  );
}
