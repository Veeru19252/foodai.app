"use client";

/**
 * LocationPickerModal — overlay wrapper around the checkout map picker.
 *
 * Lets the customer choose a delivery city + point without leaving the page.
 * The selected point is resolved to a human area label (preset label, address
 * text, or "Custom location") and confirmed as a full DeliveryLocation.
 */

import { useEffect, useState } from "react";

import LocationPicker from "./LocationPicker";
import type { DeliveryPoint } from "./LocationPicker";
import {
  CITY_CENTERS,
  DEFAULT_CITY,
  DEFAULT_POINT,
  DELIVERY_CITIES,
  DELIVERY_PRESETS,
} from "@/lib/deliveryPresets";
import type { DeliveryLocation } from "@/lib/location";

interface LocationPickerModalProps {
  open: boolean;
  initial: DeliveryLocation | null;
  onConfirm: (location: DeliveryLocation) => void;
  onClose: () => void;
}

/** Address LocationPicker sets when the user clicks the map directly. */
const CUSTOM_POINT_ADDRESS = "Custom delivery point";

/** Best human label for a point: preset label, address text, or fallback. */
export function resolveAreaLabel(point: DeliveryPoint, city: string): string {
  const preset = DELIVERY_PRESETS.find(
    (p) => p.city === city && p.address === point.address
  );
  if (preset) return preset.label;
  if (point.address && point.address !== CUSTOM_POINT_ADDRESS) {
    return point.address;
  }
  return "Custom location";
}

/** Picker point from the persisted location, or the default city's first preset. */
export function initialPoint(initial: DeliveryLocation | null): DeliveryPoint {
  return initial
    ? { lat: initial.lat, lng: initial.lng, address: initial.address }
    : { ...DEFAULT_POINT };
}

export default function LocationPickerModal({
  open,
  initial,
  onConfirm,
  onClose,
}: LocationPickerModalProps) {
  const [city, setCity] = useState(initial?.city ?? DEFAULT_CITY);
  const [point, setPoint] = useState<DeliveryPoint>(() => initialPoint(initial));

  // Re-seed from `initial` every time the modal opens.
  useEffect(() => {
    if (!open) return;
    setCity(initial?.city ?? DEFAULT_CITY);
    setPoint(initialPoint(initial));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Escape closes the modal.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  function handleConfirm() {
    onConfirm({
      city,
      areaLabel: resolveAreaLabel(point, city),
      address: point.address,
      lat: point.lat,
      lng: point.lng,
    });
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Choose delivery location"
    >
      <div
        className="flex max-h-[85vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-line bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line bg-card px-5 py-4">
          <div>
            <h2 className="text-lg font-bold">Choose delivery location</h2>
            <p className="text-xs text-muted">
              Pick a city, select a preset, or tap the map to drop a pin.
            </p>
          </div>
          <button
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-full bg-surface hover:bg-elevated"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <LocationPicker
            point={point}
            onChange={setPoint}
            presets={DELIVERY_PRESETS}
            cities={DELIVERY_CITIES}
            city={city}
            onCityChange={setCity}
            cityCenters={CITY_CENTERS}
          />
        </div>

        <div className="flex gap-2 border-t border-line bg-card px-5 py-4">
          <button
            onClick={onClose}
            className="flex-1 rounded-lg border border-line px-3 py-2 font-medium text-secondary hover:bg-surface"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!point}
            className="flex-1 rounded-lg bg-brand-600 px-3 py-2 font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          >
            Confirm location
          </button>
        </div>
      </div>
    </div>
  );
}
