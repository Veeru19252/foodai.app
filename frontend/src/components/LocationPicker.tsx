"use client";

import { useEffect, useRef, useState } from "react";

export interface DeliveryPoint {
  lat: number;
  lng: number;
  address: string;
}

export interface DeliveryPreset {
  label: string;
  city: string;
  address: string;
  lat: number;
  lng: number;
}

/** Leaflet picker: pick a city, choose a pan-India preset, or click the map. */
export default function LocationPicker({
  point,
  onChange,
  presets,
  cities,
  city,
  onCityChange,
  cityCenters,
}: {
  point: DeliveryPoint;
  onChange: (point: DeliveryPoint) => void;
  presets: DeliveryPreset[];
  cities: string[];
  city: string;
  onCityChange: (city: string) => void;
  cityCenters: Record<string, [number, number]>;
}) {
  const mapRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<L.Map | null>(null);

  const cityPresets = presets.filter((p) => p.city === city);

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

      const center = cityCenters[city] ?? [point.lat, point.lng];
      leafletMap = L.map(mapRef.current, {
        center,
        zoom: 12,
      });
      L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
          maxZoom: 19,
        }
      ).addTo(leafletMap);

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

  // Pan to the selected point whenever it changes (preset click or map click).
  useEffect(() => {
    if (!map) return;
    map.setView([point.lat, point.lng], map.getZoom());
  }, [point, map]);

  // Pan to the city centre when the city chip changes.
  useEffect(() => {
    if (!map) return;
    const center = cityCenters[city];
    if (center) map.setView(center, 12);
  }, [city, map, cityCenters]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {cities.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => onCityChange(c)}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
              city === c
                ? "bg-brand-600 text-white"
                : "bg-card text-muted ring-1 ring-line hover:bg-surface"
            }`}
          >
            {c}
          </button>
        ))}
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        {cityPresets.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => onChange({ lat: p.lat, lng: p.lng, address: p.address })}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              point.address === p.address
                ? "bg-brand-600 text-white"
                : "bg-card text-secondary ring-1 ring-line hover:bg-surface"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div ref={mapRef} className="h-64 w-full rounded-xl border border-line" />
      <p className="mt-2 text-xs text-muted">
        Selected: {point.address} ({point.lat.toFixed(5)}, {point.lng.toFixed(5)})
      </p>
    </div>
  );
}
