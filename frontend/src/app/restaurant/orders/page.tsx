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

type Nudge = {
  order_id: number;
  status: string;
  delay_min: number;
  risk: "LOW" | "MEDIUM" | "HIGH";
  message: string;
  eta_min: number | null;
};

export default function RestaurantOrdersPage() {
  const [orders, setOrders] = useState<RestaurantOrder[]>([]);
  const [drivers, setDrivers] = useState<DriverBrief[]>([]);
  const [selectedDriver, setSelectedDriver] = useState<Record<number, number>>({});
  const [nudges, setNudges] = useState<Record<number, Nudge>>({});
  const [autoReason, setAutoReason] = useState<Record<number, string>>({});
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

  // Fetch AI delay-prediction nudges for in-flight orders.
  useEffect(() => {
    if (orders.length === 0) return;
    const relevant = orders.filter((o) =>
      ["CONFIRMED", "PREPARING", "OUT_FOR_DELIVERY"].includes(o.status)
    );
    relevant.forEach((o) => {
      ordersApi
        .nudge(o.id)
        .then((n) => setNudges((prev) => ({ ...prev, [o.id]: n })))
        .catch(() => undefined);
    });
  }, [orders]);

  async function assignDriver(orderId: number) {
    const driverId = selectedDriver[orderId];
    if (!driverId) {
      setError("Select a driver first.");
      return;
    }
    setBusyId(orderId);
    try {
      await ordersApi.assign(orderId, driverId);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assign failed");
    } finally {
      setBusyId(null);
    }
  }

  async function autoAssign(orderId: number) {
    setBusyId(orderId);
    try {
      const res = await ordersApi.autoAssign(orderId);
      setAutoReason((prev) => ({ ...prev, [orderId]: res.reason }));
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Auto-assign failed");
    } finally {
      setBusyId(null);
    }
  }

  async function advance(orderId: number, nextStatus: string) {
    setBusyId(orderId);
    try {
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
          const needsDriver = next === "OUT_FOR_DELIVERY";
          const assigned = selectedDriver[o.id] ?? o.assigned_driver_id ?? 0;
          const nudge = nudges[o.id];
          return (
            <div
              key={o.id}
              data-testid={`restaurant-order-${o.id}`}
              className="rounded-2xl border border-gray-200 bg-white px-5 py-4 shadow-sm"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-semibold">
                    #{o.id} — {o.customer_name}
                  </p>
                  <p className="text-xs text-gray-500">
                    {new Date(o.created_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <span className="font-semibold">₹{o.total.toFixed(0)}</span>
                  <StatusBadge status={o.status} />
                </div>
              </div>

              {nudge && nudge.risk !== "LOW" && (
                <div
                  className={`mt-2 rounded-lg px-3 py-2 text-sm font-medium ${
                    nudge.risk === "HIGH"
                      ? "bg-red-50 text-red-700"
                      : "bg-amber-50 text-amber-700"
                  }`}
                >
                  ⚠ {nudge.message}
                </div>
              )}

              {o.assigned_driver_name && (
                <p className="mt-2 text-xs text-gray-500">
                  Assigned to{" "}
                  <span className="font-semibold">{o.assigned_driver_name}</span>
                  {autoReason[o.id] && (
                    <span className="text-gray-400"> — auto: {autoReason[o.id]}</span>
                  )}
                </p>
              )}

              {needsDriver && (
                <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-gray-100 pt-3">
                  <select
                    value={assigned}
                    onChange={(e) =>
                      setSelectedDriver((prev) => ({
                        ...prev,
                        [o.id]: Number(e.target.value),
                      }))
                    }
                    aria-label="Select delivery driver"
                    className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-brand-500 focus:outline-none"
                  >
                    <option value={0} disabled>
                      Select driver…
                    </option>
                    {drivers.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name} ({d.email})
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => assignDriver(o.id)}
                    disabled={busyId === o.id || !assigned || !!o.assigned_driver_id}
                    className="rounded-lg border border-gray-900 px-3 py-1.5 text-sm font-semibold text-gray-900 hover:bg-gray-100 disabled:opacity-50"
                  >
                    {busyId === o.id ? "Assigning…" : "Assign driver"}
                  </button>
                  <button
                    onClick={() => autoAssign(o.id)}
                    disabled={busyId === o.id || !!o.assigned_driver_id}
                    className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
                  >
                    {busyId === o.id ? "Matching…" : "⚡ Auto-assign"}
                  </button>
                  <button
                    onClick={() => advance(o.id, "OUT_FOR_DELIVERY")}
                    disabled={busyId === o.id || !o.assigned_driver_id}
                    className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-50"
                  >
                    Dispatch
                  </button>
                </div>
              )}

              {next && !needsDriver && (
                <div className="mt-3 border-t border-gray-100 pt-3">
                  <button
                    onClick={() => advance(o.id, next)}
                    disabled={busyId === o.id}
                    className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-gray-800 disabled:opacity-60"
                  >
                    {`Mark ${next.replaceAll("_", " ").toLowerCase()}`}
                  </button>
                </div>
              )}

              {o.status === "OUT_FOR_DELIVERY" && (
                <p className="mt-2 text-xs text-gray-400">
                  Dispatched — rider is on the way
                </p>
              )}
            </div>
          );
        })}
      </div>
    </ProtectedRoute>
  );
}
