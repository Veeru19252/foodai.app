"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ordersApi } from "@/lib/api";
import ProtectedRoute from "@/components/ProtectedRoute";
import StatusBadge from "@/components/StatusBadge";

interface DriverOrder {
  delivery_id: number;
  order_id: number;
  restaurant_name: string;
  customer_name: string;
  order_status: string;
  pickup_time?: string | null;
  delivered_time?: string | null;
}

export default function DriverPage() {
  const [deliveries, setDeliveries] = useState<DriverOrder[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    ordersApi.driverOrders().then(setDeliveries).catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load deliveries")
    );
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <ProtectedRoute role="delivery">
      <h1 className="mb-6 text-2xl font-bold">My deliveries</h1>

      {error && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {deliveries.length === 0 && (
        <p className="py-16 text-center text-gray-400">
          No deliveries assigned yet. Restaurants will assign you when orders
          are ready.
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {deliveries.map((d) => (
          <div
            key={d.delivery_id}
            className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm"
          >
            <div className="mb-2 flex items-center justify-between">
              <p className="font-semibold">Order #{d.order_id}</p>
              <StatusBadge status={d.order_status} />
            </div>
            <p className="text-sm text-gray-600">{d.restaurant_name}</p>
            <p className="text-sm text-gray-500">→ {d.customer_name}</p>
            <p className="mt-1 text-xs text-gray-400">
              {d.pickup_time
                ? `Picked up ${new Date(d.pickup_time).toLocaleTimeString()}`
                : "Not picked up yet"}
            </p>
            {d.order_status === "OUT_FOR_DELIVERY" && (
              <Link
                href={`/tracking/${d.order_id}`}
                className="mt-3 inline-block rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700"
              >
                Navigate
              </Link>
            )}
          </div>
        ))}
      </div>
    </ProtectedRoute>
  );
}
