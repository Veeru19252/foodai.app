"use client";

import { useEffect, useRef, useState } from "react";

export interface DeliveryPoint {
  lat: number;
  lng: number;
  address: string;
}

const DEFAULT_CENTER: [number, number] = [12.9719, 77.6412];

/** Leaflet picker: click the map (or choose a preset) to set the delivery point. */
export default function LocationPicker({
  point,
  onChange,
  presets,
}: {
  point: DeliveryPoint;
  onChange: (point: DeliveryPoint) => void;
  presets: { label: string; address: string; lat: number; lng: number }[];
}) {
  const mapRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<L.Map | null>(null);

  // Initialise the map once (leaflet is imported client-side only).
  useEffect(() => {
    if (!mapRef.current) return;
    let disposed = false;
    let leafletMap: L.Map | null = null;
    let marker: L.Marker | null = null;

    (async () => {
      const L = await import("leaflet");
      await import("leaflet/dist/leaflet.css");
      if (disposed || !mapRef.current) return;

      leafletMap = L.map(mapRef.current, {
        center: [point.lat, point.lng],
        zoom: 13,
      });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
      }).addTo(leafletMap);

      const setMarker = (lat: number, lng: number) => {
        if (marker) marker.remove();
        marker = L.marker([lat, lng]).addTo(leafletMap!);
      };
      setMarker(point.lat, point.lng);

      leafletMap.on("click", (e: L.LeafletMouseEvent) => {
        setMarker(e.latlng.lat, e.latlng.lng);
        onChange({
          lat: e.latlng.lat,
          lng: e.latlng.lng,
          address: "Custom delivery point",
        });
      });

      setMap(leafletMap);
    })();

    return () => {
      disposed = true;
      if (leafletMap) leafletMap.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map || !point) return;
    map.setView([point.lat, point.lng], map.getZoom());
  }, [point, map]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        {presets.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() =>
              onChange({ lat: p.lat, lng: p.lng, address: p.address })
            }
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              point.address === p.address
                ? "bg-brand-600 text-white"
                : "bg-white text-gray-700 ring-1 ring-gray-200 hover:bg-gray-50"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div ref={mapRef} className="h-64 w-full rounded-xl border border-gray-200" />
      <p className="mt-2 text-xs text-gray-500">
        Selected: {point.address} ({point.lat.toFixed(5)}, {point.lng.toFixed(5)})
      </p>
    </div>
  );
}

export const DEFAULT_POINT: DeliveryPoint = {
  lat: DEFAULT_CENTER[0],
  lng: DEFAULT_CENTER[1],
  address: "MG Road / Indiranagar",
};
