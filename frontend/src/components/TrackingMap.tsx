"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  route: number[][];
  riderLat: number;
  riderLng: number;
}

/** Premium Leaflet map: CARTO Voyager tiles, layered route stroke, labeled
 *  pickup/delivery pins and a pulsing live-rider marker. Renders client-side
 *  only (leaflet requires the DOM). */
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
        zoomControl: true,
      });
      L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
          maxZoom: 19,
        }
      ).addTo(leafletMap);

      const latlngs = route.map(([lat, lng]) => L.latLng(lat, lng));

      const bounds = L.latLngBounds(latlngs);
      if (bounds.isValid()) leafletMap.fitBounds(bounds.pad(0.15));

      // Layered stroke: white casing under the brand line reads premium.
      if (latlngs.length > 1) {
        L.polyline(latlngs, {
          color: "#ffffff",
          weight: 9,
          opacity: 0.9,
          lineCap: "round",
          lineJoin: "round",
        }).addTo(leafletMap);
        L.polyline(latlngs, {
          color: "#ea580c",
          weight: 4,
          opacity: 0.95,
          lineCap: "round",
          lineJoin: "round",
        }).addTo(leafletMap);
      }

      if (latlngs.length > 0) {
        L.marker(latlngs[0], {
          icon: L.divIcon({
            className: "",
            html: `<div class="leaflet-pin" style="border:2px solid #22c55e">🍽️</div>`,
            iconSize: [30, 30],
            iconAnchor: [15, 15],
          }),
        }).addTo(leafletMap);
        L.marker(latlngs[latlngs.length - 1], {
          icon: L.divIcon({
            className: "",
            html: `<div class="leaflet-pin" style="border:2px solid #ef4444">📍</div>`,
            iconSize: [30, 30],
            iconAnchor: [15, 15],
          }),
        }).addTo(leafletMap);
      }

      const riderIcon = L.divIcon({
        className: "",
        html: `<div class="leaflet-rider-pin"><span class="leaflet-rider-halo"></span><span class="leaflet-rider-dot">🛵</span></div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 17],
      });
      riderMarkerRef.current = L.marker([riderLat, riderLng], { icon: riderIcon }).addTo(
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

  // Follow the rider on updates — pan (not snap) unless motion is reduced.
  useEffect(() => {
    if (!map || !riderMarkerRef.current) return;
    riderMarkerRef.current.setLatLng([riderLat, riderLng]);
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    map.panTo([riderLat, riderLng], { animate: !reduceMotion, duration: 0.5 });
  }, [riderLat, riderLng, map]);

  return <div ref={mapRef} className="h-[420px] w-full shadow-[0_8px_24px_-12px_rgba(16,24,40,0.2)]" />;
}
