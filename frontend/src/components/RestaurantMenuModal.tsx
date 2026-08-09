"use client";

import { useEffect, useState } from "react";
import { catalogApi, mlApi, reviewsApi } from "@/lib/api";
import { useCart } from "@/lib/cart";
import type {
  ItemRecommendation,
  MenuItem,
  Restaurant,
  Review,
} from "@/lib/types";

export default function RestaurantMenuModal({
  restaurant,
  onClose,
}: {
  restaurant: Restaurant;
  onClose: () => void;
}) {
  const [menu, setMenu] = useState<MenuItem[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [recommended, setRecommended] = useState<ItemRecommendation[]>([]);
  const [error, setError] = useState("");
  const { addItem, setQuantity, items } = useCart();

  useEffect(() => {
    catalogApi
      .menu(restaurant.id)
      .then(setMenu)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load menu")
      );
    reviewsApi
      .forRestaurant(restaurant.id)
      .then(setReviews)
      .catch(() => setReviews([]));
    mlApi
      .itemRecommendations(restaurant.id)
      .then((res) => setRecommended(res.items))
      .catch(() => setRecommended([]));
  }, [restaurant.id]);

  const suggested = recommended.filter(
    (r) => !items.some((i) => i.menu_item_id === r.menu_item_id)
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-md overflow-y-auto rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-gray-100 bg-white px-5 py-4">
          <div>
            <h2 className="text-lg font-bold">{restaurant.name}</h2>
            <p className="text-xs text-gray-500">
              {restaurant.cuisine} · ★ {restaurant.rating.toFixed(1)}
            </p>
          </div>
          <button
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-full bg-gray-100 hover:bg-gray-200"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="divide-y divide-gray-100">
          {error && (
            <p className="px-5 py-3 text-sm text-red-600">{error}</p>
          )}
          {menu.map((item) => {
            const qty =
              items.find((i) => i.menu_item_id === item.id)?.quantity ?? 0;
            return (
              <div key={item.id} className="flex items-center justify-between px-5 py-4">
                <div>
                  <p className="font-medium">{item.name}</p>
                  <p className="text-sm text-gray-500">₹{item.price.toFixed(0)}</p>
                  <p className="text-xs text-gray-400">
                    ~{item.prep_time_min} min prep
                  </p>
                </div>
                {qty === 0 ? (
                  <button
                    onClick={() =>
                      addItem(restaurant.id, restaurant.name, {
                        menu_item_id: item.id,
                        restaurant_id: restaurant.id,
                        restaurant_name: restaurant.name,
                        name: item.name,
                        price: item.price,
                        quantity: 1,
                      })
                    }
                    className="rounded-full border-2 border-brand-600 px-4 py-1.5 text-sm font-semibold text-brand-600 hover:bg-brand-50"
                  >
                    ADD
                  </button>
                ) : (
                  <div className="flex items-center gap-3 rounded-full border-2 border-brand-600 px-2 py-1">
                    <button
                      onClick={() => setQuantity(item.id, qty - 1)}
                      className="h-6 w-6 text-brand-600"
                    >
                      −
                    </button>
                    <span className="w-4 text-center font-semibold">{qty}</span>
                    <button
                      onClick={() =>
                        addItem(restaurant.id, restaurant.name, {
                          menu_item_id: item.id,
                          restaurant_id: restaurant.id,
                          restaurant_name: restaurant.name,
                          name: item.name,
                          price: item.price,
                          quantity: 1,
                        })
                      }
                      className="h-6 w-6 text-brand-600"
                    >
                      +
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {suggested.length > 0 && (
          <div className="border-t border-brand-100 bg-brand-50/40 px-5 py-4">
            <p className="mb-1 text-sm font-semibold text-brand-900">
              People also order
            </p>
            <p className="mb-3 text-xs text-gray-500">
              AI picks based on popularity + your past orders
            </p>
            <div className="space-y-2">
              {suggested.slice(0, 3).map((r) => (
                <div
                  key={r.menu_item_id}
                  className="flex items-center justify-between rounded-xl bg-white px-3 py-2 shadow-sm"
                >
                  <div>
                    <p className="text-sm font-medium">{r.name}</p>
                    <p className="text-xs text-gray-400">{r.reason}</p>
                  </div>
                  <button
                    onClick={() =>
                      addItem(restaurant.id, restaurant.name, {
                        menu_item_id: r.menu_item_id,
                        restaurant_id: restaurant.id,
                        restaurant_name: restaurant.name,
                        name: r.name,
                        price: r.price,
                        quantity: 1,
                      })
                    }
                    className="rounded-full border-2 border-brand-600 px-3 py-1 text-xs font-semibold text-brand-600 hover:bg-brand-50"
                  >
                    ADD ₹{r.price.toFixed(0)}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {reviews.length > 0 && (
          <div className="border-t border-gray-100 px-5 py-4">
            <p className="mb-2 text-sm font-semibold">
              ⭐ {restaurant.reviews_rating.toFixed(1)} · {reviews.length} review
              {reviews.length === 1 ? "" : "s"}
            </p>
            <div className="max-h-40 space-y-2 overflow-y-auto">
              {reviews.slice(0, 5).map((r) => (
                <div key={r.id} className="text-sm">
                  <p className="font-medium">
                    {"★".repeat(r.rating)}
                    <span className="text-gray-300">{"★".repeat(5 - r.rating)}</span>{" "}
                    <span className="text-xs font-normal text-gray-500">
                      {r.user_name}
                    </span>
                  </p>
                  {r.comment && (
                    <p className="text-gray-600">{r.comment}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
