"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import ProtectedRoute from "@/components/ProtectedRoute";
import StatusBadge from "@/components/StatusBadge";
import TrackingMap from "@/components/TrackingMap";
import { trackingApi, WS_URL } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { TrackingState } from "@/lib/types";

export default function TrackingPage() {
  const params = useParams<{ orderId: string }>();
  const orderId = Number(params.orderId);
  const { user } = useAuth();
  const [state, setState] = useState<TrackingState | null>(null);
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

  // Fetch the initial state over REST (also covers the no-WS fallback).
  useEffect(() => {
    setError("");
    trackingApi
      .state(orderId)
      .then(applyState)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load tracking")
      );
  }, [orderId, applyState]);

  // Open the live WebSocket channel for this order.
  useEffect(() => {
    if (!user) return;
    const token = window.localStorage.getItem("foodai_access_token");
    if (!token) return;

    const ws = new WebSocket(`${WS_URL}/ws/tracking/${orderId}?token=${token}`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

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

    return () => {
      ws.close();
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

  const etaLabel =
    state.eta_min != null
      ? state.eta_source === "ml"
        ? `~${Math.ceil(state.eta_min)} min (AI)`
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
        <StatusBadge status={state.status} />
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
