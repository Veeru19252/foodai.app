"use client";

import { useCallback, useEffect, useState } from "react";
import { ordersApi } from "@/lib/api";
import type { DriverBrief, RestaurantOrder } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";
import StatusBadge from "@/components/StatusBadge";

const NEXT_STATUS: Record<string, string> = {
  PLACED: "CONFIRMED",
  CONFIRMED: "PREPARING",
  PREPARING: "OUT_FOR_DELIVERY",
};

export default function RestaurantOrdersPage() {
  const [orders, setOrders] = useState<RestaurantOrder[]>([]);
  const [drivers, setDrivers] = useState<DriverBrief[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(() => {
    ordersApi.restaurantOrders().then(setOrders).catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load orders")
    );
    ordersApi.drivers().then(setDrivers).catch(() => setDrivers([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function advance(orderId: number, nextStatus: string) {
    setBusyId(orderId);
    try {
      if (nextStatus === "OUT_FOR_DELIVERY") {
        // Pick the first available driver (demo) and assign before dispatching.
        if (drivers.length > 0) {
          await ordersApi.assign(orderId, drivers[0].id);
        }
      }
      await ordersApi.updateStatus(orderId, nextStatus);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <ProtectedRoute role="restaurant">
      <h1 className="mb-6 text-2xl font-bold">Restaurant dashboard</h1>

      {error && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="space-y-3">
        {orders.length === 0 && (
          <p className="py-16 text-center text-gray-400">No orders yet.</p>
        )}
        {orders.map((o) => {
          const next = NEXT_STATUS[o.status];
          return (
            <div
              key={o.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-gray-200 bg-white px-5 py-4 shadow-sm"
            >
              <div>
                <p className="font-semibold">
                  #{o.id} — {o.customer_name}
                </p>
                <p className="text-xs text-gray-500">
                  {new Date(o.created_at).toLocaleString()}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <span className="font-semibold">₹{o.total.toFixed(0)}</span>
                <StatusBadge status={o.status} />
                {next && (
                  <button
                    onClick={() => advance(o.id, next)}
                    disabled={busyId === o.id}
                    className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-60"
                  >
                    {next === "OUT_FOR_DELIVERY" ? "Assign & dispatch" : `Mark ${next.replaceAll("_", " ").toLowerCase()}`}
                  </button>
                )}
                {o.status === "OUT_FOR_DELIVERY" && (
                  <span className="text-xs text-gray-400">Dispatched</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </ProtectedRoute>
  );
}
