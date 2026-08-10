"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { catalogApi, mlApi } from "@/lib/api";
import { useCart } from "@/lib/cart";
import type { MenuItem, Recommendation, Restaurant } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";
import RestaurantMenuModal from "@/components/RestaurantMenuModal";

export default function RestaurantsPage() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [cuisines, setCuisines] = useState<string[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [cuisine, setCuisine] = useState("All");
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Restaurant | null>(null);
  const { count, items } = useCart();

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
    catalogApi
      .restaurants(cuisine)
      .then(setRestaurants)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load restaurants")
      );
  }, [cuisine]);

  const cartSummary = items;

  return (
    <ProtectedRoute role="customer">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Restaurants near you</h1>
          <p className="text-sm text-gray-500">
            Track every order live with AI-predicted ETAs
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setCuisine("All")}
            className={`rounded-full px-3 py-1.5 text-sm font-medium ${
              cuisine === "All"
                ? "bg-brand-600 text-white"
                : "bg-white text-gray-700 ring-1 ring-gray-200 hover:bg-gray-50"
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
                  : "bg-white text-gray-700 ring-1 ring-gray-200 hover:bg-gray-50"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {recommendations.length > 0 && (
        <div className="mb-8">
          <div className="mb-1 flex items-center justify-between">
            <h2 className="font-semibold text-gray-800">Recommended for you</h2>
            <span className="text-xs text-gray-400">
              AI · based on your order history
            </span>
          </div>
          <p className="mb-3 text-xs text-gray-500">
            Personalized picks from your past orders and cuisine preferences.
          </p>
          <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {recommendations.map((rec) => (
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
                className="press group rounded-2xl border border-brand-200 bg-gradient-to-br from-brand-50/80 to-white p-4 text-left shadow-sm transition-shadow duration-200 hover:shadow-md"
              >
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="font-semibold group-hover:text-brand-600">
                    {rec.name}
                  </h3>
                  <span className="rounded-lg bg-green-50 px-2 py-0.5 text-sm font-semibold text-green-700">
                    ★ {rec.rating.toFixed(1)}
                  </span>
                </div>
                <p className="text-xs text-gray-500">{rec.cuisine}</p>
                <p className="mt-2 rounded-lg bg-white px-2 py-1 text-xs font-medium text-brand-700 ring-1 ring-brand-100">
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
              <h3 className="text-lg font-semibold group-hover:text-brand-600">
                {r.name}
              </h3>
              <span className="rounded-lg bg-green-50 px-2 py-0.5 text-sm font-semibold text-green-700">
                ★ {r.rating.toFixed(1)}
              </span>
            </div>
            <p className="text-sm text-gray-500">{r.cuisine}</p>
            {r.city && (
              <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700 ring-1 ring-brand-100">
                {r.city}
              </span>
            )}
            <p className="mt-1 text-xs text-gray-400">{r.address}</p>
            {r.review_count > 0 && (
              <p className="mt-2 text-xs text-gray-500">
                ⭐ {r.reviews_rating.toFixed(1)} · {r.review_count} review
                {r.review_count === 1 ? "" : "s"}
              </p>
            )}
          </button>
        ))}
      </div>

      {restaurants.length === 0 && !error && (
        <p className="py-16 text-center text-gray-400">
          No restaurants in this category yet.
        </p>
      )}

      {selected && (
        <RestaurantMenuModal
          restaurant={selected}
          onClose={() => setSelected(null)}
        />
      )}

      {cartSummary.length > 0 && (
        <div className="fixed bottom-4 left-1/2 z-[70] w-[min(92vw,480px)] -translate-x-1/2 rounded-2xl bg-gray-900/90 px-5 py-3 text-white shadow-2xl backdrop-blur-xl">
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
