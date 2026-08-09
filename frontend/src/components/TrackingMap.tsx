"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  route: number[][];
  riderLat: number;
  riderLng: number;
}

/** Leaflet map rendering the delivery route + live rider marker. */
export default function TrackingMap({ route, riderLat, riderLng }: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const riderMarkerRef = useRef<L.Marker | null>(null);
  const [map, setMap] = useState<L.Map | null>(null);

  useEffect(() => {
    if (!mapRef.current) return;
    let disposed = false;
    let leafletMap: L.Map | null = null;

    (async () => {
      const L = await import("leaflet");
      await import("leaflet/dist/leaflet.css");
      if (disposed || !mapRef.current) return;

      leafletMap = L.map(mapRef.current, {
        center: [riderLat, riderLng],
        zoom: 13,
      });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
      }).addTo(leafletMap);

      const bounds = L.latLngBounds(
        route.map(([lat, lng]) => L.latLng(lat, lng))
      );
      if (bounds.isValid()) leafletMap.fitBounds(bounds.pad(0.15));

      if (route.length > 1) {
        L.polyline(
          route.map(([lat, lng]) => L.latLng(lat, lng)),
          { color: "#ea580c", weight: 4, opacity: 0.9 }
        ).addTo(leafletMap);
      }

      L.circleMarker(route[0] as [number, number], {
        radius: 7,
        color: "#22c55e",
        fillColor: "#22c55e",
        fillOpacity: 1,
      }).addTo(leafletMap);
      L.circleMarker(route[route.length - 1] as [number, number], {
        radius: 7,
        color: "#ef4444",
        fillColor: "#ef4444",
        fillOpacity: 1,
      }).addTo(leafletMap);

      // Custom rider marker: a scooter-ish orange dot.
      const icon = L.divIcon({
        className: "",
        html: `<div style="width:26px;height:26px;border-radius:9999px;background:#ea580c;border:3px solid white;box-shadow:0 2px 6px rgba(0,0,0,.4);display:grid;place-items:center;font-size:12px;color:#fff;">🛵</div>`,
        iconSize: [26, 26],
        iconAnchor: [13, 13],
      });
      riderMarkerRef.current = L.marker([riderLat, riderLng], { icon }).addTo(
        leafletMap
      );

      setMap(leafletMap);
    })();

    return () => {
      disposed = true;
      if (leafletMap) leafletMap.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Follow the rider on updates.
  useEffect(() => {
    if (!map || !riderMarkerRef.current) return;
    riderMarkerRef.current.setLatLng([riderLat, riderLng]);
    map.setView([riderLat, riderLng], map.getZoom());
  }, [riderLat, riderLng, map]);

  return <div ref={mapRef} className="h-[420px] w-full" />;
}
