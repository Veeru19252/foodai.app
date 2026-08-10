"use client";

/**
 * LocationConfirm — explicit delivery-location confirmation before ordering.
 *
 * Shows the address the order will be delivered to and asks the customer to
 * confirm it (with an optional "use my current location" GPS cross-check that
 * reports the straight-line distance). The order endpoint refuses orders that
 * haven't been confirmed, so this is the single source of truth for
 * location_confirmed in the checkout flow.
 */

import { useState } from "react";

interface LocationConfirmProps {
  deliveryAddress?: string | null;
  deliveryCity?: string | null;
  deliveryState?: string | null;
  deliveryPincode?: string | null;
  deliveryLat?: number | null;
  deliveryLng?: number | null;
  /** Called with the confirmation state + any GPS cross-check coordinates. */
  onConfirm: (confirmed: boolean, gps?: { lat: number; lng: number }) => void;
}

function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export default function LocationConfirm({
  deliveryAddress,
  deliveryCity,
  deliveryState,
  deliveryPincode,
  deliveryLat,
  deliveryLng,
  onConfirm,
}: LocationConfirmProps) {
  const [confirmed, setConfirmed] = useState(false);
  const [gps, setGps] = useState<{ lat: number; lng: number } | null>(null);
  const [distanceKm, setDistanceKm] = useState<number | null>(null);
  const [locating, setLocating] = useState(false);
  const [gpsError, setGpsError] = useState("");

  const addressLine = [deliveryAddress, deliveryCity, deliveryState, deliveryPincode]
    .filter(Boolean)
    .join(", ");

  async function useCurrentLocation() {
    if (!("geolocation" in navigator)) {
      setGpsError("Location isn't supported by this browser.");
      return;
    }
    setLocating(true);
    setGpsError("");
    try {
      const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 10_000,
        });
      });
      const { latitude, longitude } = pos.coords;
      setGps({ lat: latitude, lng: longitude });
      if (deliveryLat != null && deliveryLng != null) {
        setDistanceKm(haversineKm(deliveryLat, deliveryLng, latitude, longitude));
      }
    } catch {
      setGpsError("Couldn't access your location. Check browser permissions.");
    } finally {
      setLocating(false);
    }
  }

  function toggle(checked: boolean) {
    setConfirmed(checked);
    onConfirm(checked, gps ?? undefined);
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-card p-5">
      <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-zinc-100">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-500/15 text-[11px] text-brand-300">
          1
        </span>
        Confirm your delivery location
      </div>
      <p className="mb-4 text-sm text-zinc-400">
        Let&apos;s make sure your food goes to the right place.
      </p>

      <div className="mb-4 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
        <p className="text-sm leading-relaxed text-zinc-200">
          {addressLine || "No delivery address set"}
        </p>
        {deliveryLat != null && deliveryLng != null && (
          <p className="mt-1 text-xs text-zinc-500">
            {deliveryLat.toFixed(4)}, {deliveryLng.toFixed(4)}
          </p>
        )}
      </div>

      <button
        onClick={useCurrentLocation}
        disabled={locating}
        className="mb-3 flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm font-medium text-zinc-200 transition hover:border-zinc-600 hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <svg
          className="h-4 w-4 text-brand-300"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
          <circle cx="12" cy="10" r="3" />
        </svg>
        {locating ? "Locating…" : "Use my current location"}
      </button>

      {gps && (
        <p className="mb-3 text-xs text-zinc-400">
          {distanceKm != null
            ? `You are ${distanceKm.toFixed(1)} km from the delivery address.`
            : "Current location captured."}
        </p>
      )}
      {gpsError && <p className="mb-3 text-xs text-red-400">{gpsError}</p>}

      <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => toggle(e.target.checked)}
          className="mt-0.5 h-4 w-4 accent-brand-400"
        />
        <span className="text-sm text-zinc-200">
          Yes, deliver to this address
        </span>
      </label>
    </div>
  );
}
