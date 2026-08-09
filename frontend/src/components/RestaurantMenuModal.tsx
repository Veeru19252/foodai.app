"use client";

import { useEffect, useState } from "react";
import { catalogApi } from "@/lib/api";
import { useCart } from "@/lib/cart";
import type { MenuItem, Restaurant } from "@/lib/types";

export default function RestaurantMenuModal({
  restaurant,
  onClose,
}: {
  restaurant: Restaurant;
  onClose: () => void;
}) {
  const [menu, setMenu] = useState<MenuItem[]>([]);
  const [error, setError] = useState("");
  const { addItem, setQuantity, restaurantId, items } = useCart();

  useEffect(() => {
    catalogApi
      .menu(restaurant.id)
      .then(setMenu)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load menu")
      );
  }, [restaurant.id]);

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
              restaurantId === restaurant.id
                ? items.find((i) => i.menu_item_id === item.id)?.quantity ?? 0
                : 0;
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
                      addItem(restaurant.id, {
                        menu_item_id: item.id,
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
                        addItem(restaurant.id, {
                          menu_item_id: item.id,
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
      </div>
    </div>
  );
}
