"use client";

import { useCallback, useState } from "react";

/** Delivery location selected by the user, persisted across sessions. */
export interface DeliveryLocation {
  city: string;
  areaLabel: string;
  address: string;
  lat: number;
  lng: number;
}

export const LOCATION_STORAGE_KEY = "foodai_delivery_location";

/** Guard: a parsed value is a DeliveryLocation only when the required keys exist. */
function isDeliveryLocation(value: unknown): value is DeliveryLocation {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.city === "string" &&
    typeof candidate.lat === "number" &&
    typeof candidate.lng === "number"
  );
}

/** Read the persisted delivery location; returns null when absent or corrupt. */
export function loadDeliveryLocation(): DeliveryLocation | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LOCATION_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isDeliveryLocation(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Persist the delivery location, or clear it when null is passed. */
export function saveDeliveryLocation(location: DeliveryLocation | null): void {
  if (typeof window === "undefined") return;
  try {
    if (location) {
      window.localStorage.setItem(LOCATION_STORAGE_KEY, JSON.stringify(location));
    } else {
      window.localStorage.removeItem(LOCATION_STORAGE_KEY);
    }
  } catch {
    // Storage can be unavailable (private mode, quota); a saved location is optional.
  }
}

export interface DeliveryLocationState {
  location: DeliveryLocation | null;
  setLocation: (location: DeliveryLocation | null) => void;
}

/** React hook backed by localStorage for the user's delivery location. */
export function useDeliveryLocation(): DeliveryLocationState {
  const [location, setLocationState] = useState<DeliveryLocation | null>(
    loadDeliveryLocation
  );

  const setLocation = useCallback((next: DeliveryLocation | null) => {
    saveDeliveryLocation(next);
    setLocationState(next);
  }, []);

  return { location, setLocation };
}
