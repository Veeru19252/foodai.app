"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { catalogApi, mlApi } from "@/lib/api";
import { useCart } from "@/lib/cart";
import type { MenuItem, Recommendation, Restaurant } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";
import RestaurantMenuModal from "@/components/RestaurantMenuModal";
import LocationPickerModal from "@/components/LocationPickerModal";
import { useDeliveryLocation } from "@/lib/location";

export default function RestaurantsPage() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [cuisines, setCuisines] = useState<string[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [cuisine, setCuisine] = useState("All");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Restaurant | null>(null);
  const [locationOpen, setLocationOpen] = useState(false);
  const { count, items } = useCart();
  const { location, setLocation } = useDeliveryLocation();

  useEffect(() => {
    catalogApi
      .cuisines()
      .then(setCuisines)
      .catch(() => setCuisines([]));
    // Personalized "Recommended for you" — hidden when the ML endpoint
    // has no order history to work with.
    mlApi
      .recommendations()
      .then((res) => setRecommendations(res.fallback ? [] : res.recommendations))
      .catch(() => setRecommendations([]));
  }, []);

  useEffect(() => {
    setError("");
    if (!location) return;
    catalogApi
      .restaurants(cuisine, location.city, location.lat, location.lng)
      .then(setRestaurants)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load restaurants")
      );
  }, [cuisine, location]);

  // Recommendations are only useful when they belong to the current city;
  // the ML endpoint is city-agnostic, so match them against the loaded list.
  const cityRecommendations = recommendations.filter((rec) =>
    restaurants.some((r) => r.id === rec.restaurant_id)
  );

  const cartSummary = items;

  return (
    <ProtectedRoute role="customer">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Restaurants near you</h1>
          <p className="text-sm text-muted">
            Track every order live with AI-predicted ETAs
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setCuisine("All")}
            className={`rounded-full px-3 py-1.5 text-sm font-medium ${
              cuisine === "All"
                ? "bg-brand-600 text-white"
                : "bg-card text-secondary ring-1 ring-line hover:bg-surface"
            }`}
          >
            All
          </button>
          {cuisines.map((c) => (
            <button
              key={c}
              onClick={() => setCuisine(c)}
              className={`rounded-full px-3 py-1.5 text-sm font-medium ${
                cuisine === c
                  ? "bg-brand-600 text-white"
                  : "bg-card text-secondary ring-1 ring-line hover:bg-surface"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {location && (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-card px-4 py-3">
          <p className="flex items-center gap-2 text-sm text-secondary">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4 text-brand-400"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 21s-6-5.1-6-10a6 6 0 1 1 12 0c0 4.9-6 10-6 10z"
              />
              <circle cx="12" cy="11" r="2" />
            </svg>
            Delivering to{" "}
            <span className="font-semibold text-foreground">
              {location.areaLabel}, {location.city}
            </span>
          </p>
          <button
            onClick={() => setLocationOpen(true)}
            className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-brand-300 transition hover:bg-elevated"
          >
            Change
          </button>
        </div>
      )}

      {!location ? (
        <div className="rounded-2xl border border-line bg-card p-12 text-center">
          <h2 className="mb-2 text-xl font-bold">Set your delivery location first</h2>
          <p className="mx-auto mb-6 max-w-md text-sm text-muted">
            Tell us where to deliver so we can show restaurants and delivery
            times near you.
          </p>
          <button
            onClick={() => setLocationOpen(true)}
            className="rounded-xl bg-brand-600 px-5 py-2.5 font-semibold text-white transition hover:bg-brand-700"
          >
            Choose delivery location
          </button>
        </div>
      ) : (
        <>
          {error && (
            <p className="mb-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {error}
            </p>
          )}

          {cityRecommendations.length > 0 && (
            <div className="mb-8">
              <div className="mb-1 flex items-center justify-between">
                <h2 className="font-semibold text-foreground">Recommended for you</h2>
                <span className="text-xs text-faint">
                  AI · based on your order history
                </span>
              </div>
              <p className="mb-3 text-xs text-muted">
                Personalized picks from your past orders and cuisine preferences.
              </p>
              <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {cityRecommendations.map((rec) => (
                  <button
                    key={rec.restaurant_id}
                    onClick={() =>
                      setSelected({
                        id: rec.restaurant_id,
                        name: rec.name,
                        address: rec.address,
                        cuisine: rec.cuisine,
                        rating: rec.rating,
                        review_count: rec.review_count,
                        reviews_rating: rec.reviews_rating,
                      })
                    }
                    className="press group rounded-2xl border border-brand-500/20 bg-gradient-to-br from-brand-500/10 to-surface p-4 text-left shadow-sm transition-shadow duration-200 hover:shadow-md hover:border-brand-500/40"
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <h3 className="font-semibold group-hover:text-brand-300">
                        {rec.name}
                      </h3>
                      <span className="rounded-lg bg-emerald-500/15 px-2 py-0.5 text-sm font-semibold text-emerald-300">
                        ★ {rec.rating.toFixed(1)}
                      </span>
                    </div>
                    <p className="text-xs text-muted">{rec.cuisine}</p>
                    <p className="mt-2 rounded-lg bg-surface px-2 py-1 text-xs font-medium text-brand-300 ring-1 ring-brand-500/20">
                      {rec.reason}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {restaurants.map((r) => (
              <button
                key={r.id}
                onClick={() => setSelected(r)}
                className="press card-premium group p-5 text-left"
              >
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-lg font-semibold group-hover:text-brand-300">
                    {r.name}
                  </h3>
                  <span className="rounded-lg bg-emerald-500/15 px-2 py-0.5 text-sm font-semibold text-emerald-300">
                    ★ {r.rating.toFixed(1)}
                  </span>
                </div>
                <p className="text-sm text-muted">{r.cuisine}</p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  {r.city && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-500/15 px-2 py-0.5 text-[11px] font-semibold text-brand-300 ring-1 ring-brand-500/20">
                      {r.city}
                    </span>
                  )}
                  {r.distance_km != null && r.eta_min != null && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-surface px-2 py-0.5 text-[11px] font-medium text-secondary ring-1 ring-line">
                      {r.distance_km.toFixed(1)} km · ~{Math.round(r.eta_min)} min
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-faint">{r.address}</p>
                {r.review_count > 0 && (
                  <p className="mt-2 text-xs text-muted">
                    ⭐ {r.reviews_rating.toFixed(1)} · {r.review_count} review
                    {r.review_count === 1 ? "" : "s"}
                  </p>
                )}
              </button>
            ))}
          </div>

          {restaurants.length === 0 && !error && (
            <p className="py-16 text-center text-faint">
              No restaurants in {location.city} yet. Try another city.
            </p>
          )}
        </>
      )}

      <LocationPickerModal
        open={locationOpen}
        initial={location}
        onConfirm={(loc) => {
          setLocation(loc);
          setLocationOpen(false);
        }}
        onClose={() => setLocationOpen(false)}
      />

      {selected && (
        <RestaurantMenuModal
          restaurant={selected}
          onClose={() => setSelected(null)}
        />
      )}

      {cartSummary.length > 0 && (
        <div className="fixed bottom-4 left-1/2 z-[70] w-[min(92vw,480px)] -translate-x-1/2 rounded-2xl border border-line bg-card/95 px-5 py-3 text-foreground shadow-2xl backdrop-blur-xl">
          <div className="flex items-center justify-between text-sm">
            <span>
              {count} item{count === 1 ? "" : "s"} in cart
            </span>
            <Link
              href="/checkout"
              className="press font-semibold text-brand-400 transition-colors duration-150 hover:text-brand-300"
            >
              View cart →
            </Link>
          </div>
        </div>
      )}
    </ProtectedRoute>
  );
}
