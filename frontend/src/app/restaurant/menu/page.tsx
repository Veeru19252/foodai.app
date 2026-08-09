"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { restaurantApi } from "@/lib/api";
import type { MenuItem } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";

export default function RestaurantMenuPage() {
  const [items, setItems] = useState<MenuItem[]>([]);
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [prep, setPrep] = useState("15");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editPrice, setEditPrice] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    restaurantApi
      .myMenu()
      .then(setItems)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load menu")
      );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function addItem(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      await restaurantApi.addMenuItem({
        name: name.trim(),
        price: Number(price) || 0,
        prep_time_min: Number(prep) || 15,
      });
      setName("");
      setPrice("");
      setPrep("15");
      setNote("Menu item added");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add item");
    } finally {
      setBusy(false);
    }
  }

  async function savePrice(itemId: number) {
    setBusy(true);
    setError("");
    try {
      await restaurantApi.updateMenuItem(itemId, { price: Number(editPrice) || 0 });
      setEditingId(null);
      setNote("Price updated");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update item");
    } finally {
      setBusy(false);
    }
  }

  async function removeItem(itemId: number) {
    setBusy(true);
    setError("");
    try {
      await restaurantApi.deleteMenuItem(itemId);
      setNote("Menu item removed");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove item");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ProtectedRoute role="restaurant">
      <h1 className="mb-6 text-2xl font-bold">Menu management</h1>

      {error && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      {note && (
        <p className="mb-4 rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">
          {note}
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-gray-200 bg-white p-5">
          <h2 className="mb-3 font-semibold">Add menu item</h2>
          <form onSubmit={addItem} className="space-y-3">
            <div>
              <label className="mb-1 block text-sm font-medium">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                placeholder="e.g. Butter Chicken"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-sm font-medium">Price (₹)</label>
                <input
                  type="number"
                  min="0"
                  step="0.5"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                  placeholder="199"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">Prep (min)</label>
                <input
                  type="number"
                  min="0"
                  value={prep}
                  onChange={(e) => setPrep(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={busy || !name.trim()}
              className="rounded-lg bg-brand-600 px-4 py-2 font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
            >
              {busy ? "Adding…" : "Add item"}
            </button>
          </form>
        </section>

        <section className="rounded-2xl border border-gray-200 bg-white p-5">
          <h2 className="mb-3 font-semibold">
            Current menu ({items.length} items)
          </h2>
          <div className="divide-y divide-gray-100">
            {items.length === 0 && (
              <p className="py-4 text-sm text-gray-400">No items yet.</p>
            )}
            {items.map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between gap-3 py-2 text-sm"
              >
                <div>
                  <p className="font-medium">{item.name}</p>
                  <p className="text-xs text-gray-400">
                    ~{item.prep_time_min} min prep
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {editingId === item.id ? (
                    <>
                      <input
                        type="number"
                        min="0"
                        step="0.5"
                        value={editPrice}
                        onChange={(e) => setEditPrice(e.target.value)}
                        className="w-20 rounded-lg border border-gray-300 px-2 py-1 text-sm focus:border-brand-500 focus:outline-none"
                        aria-label={`Price for ${item.name}`}
                      />
                      <button
                        onClick={() => savePrice(item.id)}
                        disabled={busy}
                        className="rounded-lg bg-brand-600 px-2 py-1 text-xs font-semibold text-white hover:bg-brand-700"
                      >
                        Save
                      </button>
                    </>
                  ) : (
                    <>
                      <span className="font-semibold">₹{item.price.toFixed(0)}</span>
                      <button
                        onClick={() => {
                          setEditingId(item.id);
                          setEditPrice(String(item.price));
                        }}
                        className="text-xs font-medium text-brand-600 hover:underline"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => removeItem(item.id)}
                        disabled={busy}
                        className="text-xs font-medium text-red-600 hover:underline"
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </ProtectedRoute>
  );
}
