"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import ProtectedRoute from "@/components/ProtectedRoute";
import StatusBadge from "@/components/StatusBadge";
import TrackingMap from "@/components/TrackingMap";
import { mlApi, trackingApi, WS_URL } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { OrderPrediction, TrackingState } from "@/lib/types";

const FEATURE_LABELS: Record<string, string> = {
  distance_km: "Distance",
  prep_time_min: "Prep time",
  hour_of_day: "Time of day",
  day_of_week: "Day of week",
  is_weekend: "Weekend",
  traffic_factor: "Traffic",
  zone_A: "Zone A",
  zone_B: "Zone B",
  zone_C: "Zone C",
  zone_D: "Zone D",
  zone_E: "Zone E",
};

export default function TrackingPage() {
  const params = useParams<{ orderId: string }>();
  const orderId = Number(params.orderId);
  const { user } = useAuth();
  const [state, setState] = useState<TrackingState | null>(null);
  const [prediction, setPrediction] = useState<OrderPrediction | null>(null);
  const [showExplain, setShowExplain] = useState(false);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const applyState = useCallback((s: TrackingState) => {
    setState((prev) => {
      // Keep the route/restaurant name; use whichever source is freshest.
      return {
        ...s,
        route: s.route?.length ? s.route : prev?.route ?? [],
      };
    });
  }, []);

  // Poll the REST state as an authoritative fallback: it covers the initial
  // load AND keeps the map live when the WebSocket drops (dev servers close
  // sockets on hot reload), so the tracking page never freezes.
  useEffect(() => {
    let cancelled = false;
    const poll = () =>
      trackingApi
        .state(orderId)
        .then((s) => {
          if (!cancelled) applyState(s);
        })
        .catch((err) => {
          if (!cancelled)
            setError(
              err instanceof Error ? err.message : "Failed to load tracking"
            );
        });
    poll();
    const timer = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [orderId, applyState]);

  // Fetch the ML prediction + SHAP explanation for the "Why this ETA?" panel.
  useEffect(() => {
    if (!user) return;
    mlApi
      .orderPrediction(orderId)
      .then((pred) => setPrediction(pred))
      .catch(() => setPrediction(null)); // quietly hide the panel on any error
  }, [orderId, user]);

  // Open the live WebSocket channel for this order, reconnecting on drops.
  useEffect(() => {
    if (!user) return;
    const token = window.localStorage.getItem("foodai_access_token");
    if (!token) return;

    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let ws: WebSocket | null = null;

    const connect = () => {
      if (cancelled) return;
      ws = new WebSocket(`${WS_URL}/ws/tracking/${orderId}?token=${token}`);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!cancelled) reconnectTimer = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws?.close();

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "state") applyState(msg.data);
          if (msg.type === "position") {
            setState((prev) =>
              prev
                ? {
                    ...prev,
                    rider_lat: msg.lat,
                    rider_lng: msg.lng,
                    progress: msg.progress,
                    status: msg.status,
                  }
                : prev
            );
          }
          if (msg.type === "delivered") {
            setState((prev) =>
              prev
                ? { ...prev, rider_lat: msg.lat, rider_lng: msg.lng, progress: 1, status: "DELIVERED" }
                : prev
            );
          }
          if (msg.type === "pong") return;
        } catch {
          /* ignore malformed frames */
        }
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
      wsRef.current = null;
    };
  }, [orderId, user, applyState]);

  if (error) {
    return (
      <ProtectedRoute>
        <div className="rounded-2xl border border-gray-200 bg-white p-10 text-center">
          <p className="mb-4 text-red-600">{error}</p>
          <Link
            href="/orders"
            className="rounded-lg bg-brand-600 px-4 py-2 font-semibold text-white"
          >
            Back to my orders
          </Link>
        </div>
      </ProtectedRoute>
    );
  }

  if (!state) {
    return (
      <ProtectedRoute>
        <div className="flex h-64 items-center justify-center text-gray-500">
          Loading tracking…
        </div>
      </ProtectedRoute>
    );
  }

  const liveSuffix = state.position_source === "live" ? " · live GPS" : "";
  const etaLabel =
    state.eta_min != null
      ? state.eta_source === "ml"
        ? `~${Math.ceil(state.eta_min)} min (AI${liveSuffix})`
        : `~${Math.ceil(state.eta_min)} min`
      : "—";

  const progressPct = Math.round(state.progress * 100);

  return (
    <ProtectedRoute>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Live tracking</h1>
          <p className="text-sm text-gray-500">
            Order #{state.order_id} · {state.restaurant_name}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {state.status === "OUT_FOR_DELIVERY" && state.position_source && (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${
                state.position_source === "live"
                  ? "bg-green-50 text-green-700"
                  : "bg-gray-100 text-gray-500"
              }`}
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  state.position_source === "live"
                    ? "animate-pulse bg-green-500"
                    : "bg-gray-400"
                }`}
              />
              {state.position_source === "live" ? "LIVE GPS" : "SIMULATED"}
            </span>
          )}
          <StatusBadge status={state.status} />
        </div>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">AI ETA</p>
          <p className="text-2xl font-bold">{etaLabel}</p>
        </div>
        <div className="rounded-2xl border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">Distance</p>
          <p className="text-2xl font-bold">{state.route_distance_km} km</p>
        </div>
        <div className="rounded-2xl border border-gray-200 bg-white p-4">
          <p className="text-xs text-gray-500">Delivery to</p>
          <p className="truncate text-sm font-medium">
            {state.delivery_address ?? "—"}
          </p>
        </div>
      </div>

      {prediction && prediction.eta_min != null && (
        <div className="mb-4 rounded-2xl border border-gray-200 bg-white p-4">
          <button
            type="button"
            onClick={() => setShowExplain((v) => !v)}
            className="flex w-full items-center justify-between text-left"
          >
            <span className="text-sm font-semibold text-brand-700">
              Why this ETA? <span className="text-xs font-normal text-gray-500">(AI explainability)</span>
            </span>
            <span className="text-gray-400">{showExplain ? "▲" : "▼"}</span>
          </button>

          {showExplain && (
            <div className="mt-3">
              {prediction.explanation ? (
                <ExplainPanel prediction={prediction} />
              ) : (
                <p className="text-sm text-gray-500">
                  The explainer model isn&apos;t available right now — the ETA
                  is still the ML model&apos;s best estimate.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <div className="mb-4 h-2 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className="h-full rounded-full bg-brand-600 transition-all"
          style={{ width: `${progressPct}%` }}
        />
      </div>
      <p className="mb-4 text-sm text-gray-500">
        {state.status === "DELIVERED"
          ? "Delivered! Enjoy your meal 🎉"
          : state.status === "OUT_FOR_DELIVERY"
            ? `Your rider is ${progressPct}% of the way`
            : `Order ${state.status.replaceAll("_", " ").toLowerCase()}`}
      </p>

      <TrackingMap route={state.route} riderLat={state.rider_lat} riderLng={state.rider_lng} />

      <div className="mt-4 flex items-center justify-between text-xs text-gray-400">
        <span>
          {connected ? "● live updates connected" : "○ polling fallback"}
        </span>
        <Link href="/orders" className="font-medium text-brand-600 hover:underline">
          My orders →
        </Link>
      </div>
    </ProtectedRoute>
  );
}

function ExplainPanel({ prediction }: { prediction: OrderPrediction }) {
  const contributions = prediction.explanation?.contributions ?? [];
  const visible = contributions
    .filter((c) => !c.feature.startsWith("zone_") || c.value === 1)
    .slice(0, 5);
  const maxAbs = Math.max(
    1,
    ...visible.map((c) => Math.abs(c.shap))
  );

  return (
    <div>
      <p className="mb-3 text-sm text-gray-600">
        The model scores <strong>11 factors</strong> (distance, prep time, time
        of day, weekend, traffic and your delivery zone) against historical
        deliveries. These are the biggest influences on the{" "}
        <strong>~{Math.ceil(prediction.eta_min ?? 0)} min</strong> estimate:
      </p>
      <div className="space-y-2">
        {visible.map((c) => {
          const label = FEATURE_LABELS[c.feature] ?? c.feature;
          const width = Math.round((Math.abs(c.shap) / maxAbs) * 100);
          const slower = c.shap > 0;
          return (
            <div key={c.feature} className="flex items-center gap-3">
              <div className="w-32 shrink-0 text-xs text-gray-500">{label}</div>
              <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-gray-200">
                <div
                  className={
                    slower ? "h-full rounded-full bg-amber-500" : "h-full rounded-full bg-emerald-500"
                  }
                  style={{ width: `${width}%` }}
                />
              </div>
              <div
                className={`w-20 shrink-0 text-right text-xs font-semibold ${
                  slower ? "text-amber-600" : "text-emerald-600"
                }`}
              >
                {slower ? "+" : "−"}
                {Math.abs(c.shap).toFixed(1)} min
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
