"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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

interface Earnings {
  per_delivery_rate: number;
  per_km_rate: number;
  total_earnings: number;
  total_deliveries: number;
  completed_deliveries: number;
  active_deliveries: number;
  recent: {
    delivery_id: number;
    order_id: number;
    restaurant_name: string;
    customer_name: string;
    distance_km: number;
    earned: number;
    completed_at: string | null;
  }[];
}

interface Nudge {
  risk: "LOW" | "MEDIUM" | "HIGH";
  message: string;
}

export default function DriverPage() {
  const [deliveries, setDeliveries] = useState<DriverOrder[]>([]);
  const [earnings, setEarnings] = useState<Earnings | null>(null);
  const [nudges, setNudges] = useState<Record<number, Nudge>>({});
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(() => {
    ordersApi.driverOrders().then(setDeliveries).catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load deliveries")
    );
    ordersApi.driverEarnings().then(setEarnings).catch(() => setEarnings(null));
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  // Delay-prediction warnings for in-flight orders.
  useEffect(() => {
    const relevant = deliveries.filter((d) =>
      ["OUT_FOR_DELIVERY", "PREPARING", "CONFIRMED"].includes(d.order_status)
    );
    relevant.forEach((d) => {
      ordersApi
        .nudge(d.order_id)
        .then((n) => setNudges((prev) => ({ ...prev, [d.order_id]: n })))
        .catch(() => undefined);
    });
  }, [deliveries]);

  async function startDelivery(orderId: number) {
    setBusyId(orderId);
    try {
      await ordersApi.updateStatus(orderId, "OUT_FOR_DELIVERY");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start delivery");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <ProtectedRoute role="delivery">
      <h1 className="mb-6 text-2xl font-bold">My deliveries</h1>

      {error && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {earnings && (
        <div className="mb-6 rounded-2xl border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Earnings</h2>
            <span className="text-xs text-gray-400">
              ₹{earnings.per_delivery_rate}/order + ₹{earnings.per_km_rate}/km
            </span>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="text-xs text-gray-500">Total earned</p>
              <p className="text-2xl font-bold">
                ₹{earnings.total_earnings.toFixed(0)}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Delivered</p>
              <p className="text-2xl font-bold">
                {earnings.completed_deliveries}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Active</p>
              <p className="text-2xl font-bold">{earnings.active_deliveries}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">All-time trips</p>
              <p className="text-2xl font-bold">{earnings.total_deliveries}</p>
            </div>
          </div>
          {earnings.recent.some((r) => r.completed_at) && (
            <div className="mt-3 border-t border-gray-100 pt-3">
              <p className="mb-2 text-xs font-semibold text-gray-500">
                Recent trips
              </p>
              <div className="space-y-1">
                {earnings.recent
                  .filter((r) => r.completed_at)
                  .slice(0, 5)
                  .map((r) => (
                    <div
                      key={r.delivery_id}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-gray-600">
                        #{r.order_id} · {r.restaurant_name} ·{" "}
                        {r.distance_km.toFixed(1)} km
                      </span>
                      <span className="font-semibold">
                        +₹{r.earned.toFixed(0)}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}

      {deliveries.length === 0 && (
        <p className="py-16 text-center text-gray-400">
          No deliveries assigned yet. Restaurants will assign you when orders
          are ready — you&apos;ll get a notification.
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {deliveries.map((d) => {
          const nudge = nudges[d.order_id];
          return (
            <div
              key={d.delivery_id}
              data-testid={`driver-delivery-${d.order_id}`}
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

              {nudge && nudge.risk !== "LOW" && (
                <p
                  className={`mt-2 rounded-lg px-3 py-2 text-sm font-medium ${
                    nudge.risk === "HIGH"
                      ? "bg-red-50 text-red-700"
                      : "bg-amber-50 text-amber-700"
                  }`}
                >
                  ⚠ {nudge.message}
                </p>
              )}

              {(d.order_status === "PREPARING" ||
                d.order_status === "CONFIRMED") && (
                <button
                  onClick={() => startDelivery(d.order_id)}
                  disabled={busyId === d.order_id}
                  className="mt-3 rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
                >
                  {busyId === d.order_id ? "Starting…" : "Start delivery"}
                </button>
              )}

              {d.order_status === "OUT_FOR_DELIVERY" && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Link
                    href={`/tracking/${d.order_id}`}
                    className="inline-block rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700"
                  >
                    Navigate
                  </Link>
                  <ShareLocationButton orderId={d.order_id} />
                </div>
              )}

              {d.order_status === "DELIVERED" && (
                <p className="mt-3 text-sm font-medium text-green-600">
                  Delivered ✓
                </p>
              )}
            </div>
          );
        })}
      </div>
    </ProtectedRoute>
  );
}

/** Uploads the browser's GPS fix every few seconds for one in-flight order. */
function ShareLocationButton({ orderId }: { orderId: number }) {
  const [active, setActive] = useState(false);
  const [error, setError] = useState("");
  const [lastSent, setLastSent] = useState<string | null>(null);
  const aliveRef = useRef(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const sendOnce = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setError("Geolocation isn't supported by this browser.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        if (!aliveRef.current) return;
        try {
          const res = await ordersApi.updateDriverLocation(
            orderId,
            pos.coords.latitude,
            pos.coords.longitude
          );
          setLastSent(new Date(res.updated_at).toLocaleTimeString());
          setError("");
        } catch (err) {
          setError(
            err instanceof Error ? err.message : "Location upload failed"
          );
        }
      },
      (err) => setError(err.message || "Location unavailable"),
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 5_000 }
    );
  }, [orderId]);

  function start() {
    setError("");
    aliveRef.current = true;
    sendOnce();
    timerRef.current = setInterval(sendOnce, 8000);
    setActive(true);
  }

  function stop() {
    aliveRef.current = false;
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    setActive(false);
  }

  useEffect(
    () => () => {
      aliveRef.current = false;
      if (timerRef.current) clearInterval(timerRef.current);
    },
    []
  );

  return (
    <div className="flex items-center gap-2">
      {active ? (
        <>
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-green-50 px-3 py-1.5 text-sm font-medium text-green-700">
            <span className="h-2 w-2 animate-pulse rounded-full bg-green-500" />
            Sharing location{lastSent ? ` · ${lastSent}` : "…"}
          </span>
          <button
            onClick={stop}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50"
          >
            Stop
          </button>
        </>
      ) : (
        <button
          onClick={start}
          className="inline-block rounded-lg border border-brand-300 bg-white px-3 py-1.5 text-sm font-semibold text-brand-700 hover:bg-brand-50"
        >
          📍 Share live location
        </button>
      )}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
