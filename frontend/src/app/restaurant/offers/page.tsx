"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { restaurantApi, type RestaurantOffer } from "@/lib/api";
import ProtectedRoute from "@/components/ProtectedRoute";

export default function RestaurantOffersPage() {
  const [offers, setOffers] = useState<RestaurantOffer[]>([]);
  const [code, setCode] = useState("");
  const [description, setDescription] = useState("");
  const [discountType, setDiscountType] = useState("percent");
  const [discountValue, setDiscountValue] = useState("10");
  const [minOrder, setMinOrder] = useState("0");
  const [maxDiscount, setMaxDiscount] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    restaurantApi
      .offers()
      .then(setOffers)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load offers")
      );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function createOffer(e: FormEvent) {
    e.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    setError("");
    try {
      await restaurantApi.createOffer({
        code: code.trim().toUpperCase(),
        description: description.trim() || undefined,
        discount_type: discountType,
        discount_value: Number(discountValue) || 0,
        min_order_value: Number(minOrder) || 0,
        max_discount: maxDiscount ? Number(maxDiscount) : undefined,
      });
      setCode("");
      setDescription("");
      setNote("Offer created");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create offer");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(offer: RestaurantOffer) {
    setBusy(true);
    setError("");
    try {
      await restaurantApi.toggleOffer(offer.id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not toggle offer");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ProtectedRoute role="restaurant">
      <h1 className="mb-6 text-2xl font-bold">Restaurant offers</h1>

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
          <h2 className="mb-3 font-semibold">Create offer</h2>
          <form onSubmit={createOffer} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-sm font-medium">Code</label>
                <input
                  type="text"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 uppercase focus:border-brand-500 focus:outline-none"
                  placeholder="SPICE20"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">Type</label>
                <select
                  value={discountType}
                  onChange={(e) => setDiscountType(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                >
                  <option value="percent">Percent (%)</option>
                  <option value="flat">Flat (₹)</option>
                </select>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">Description</label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                placeholder="20% off up to ₹60"
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="mb-1 block text-sm font-medium">
                  {discountType === "percent" ? "Percent" : "Amount"}
                </label>
                <input
                  type="number"
                  min="0"
                  value={discountValue}
                  onChange={(e) => setDiscountValue(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">Min order</label>
                <input
                  type="number"
                  min="0"
                  value={minOrder}
                  onChange={(e) => setMinOrder(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium">Max disc.</label>
                <input
                  type="number"
                  min="0"
                  value={maxDiscount}
                  onChange={(e) => setMaxDiscount(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                  placeholder="Optional"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={busy || !code.trim()}
              className="rounded-lg bg-brand-600 px-4 py-2 font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
            >
              {busy ? "Creating…" : "Create offer"}
            </button>
          </form>
        </section>

        <section className="rounded-2xl border border-gray-200 bg-white p-5">
          <h2 className="mb-3 font-semibold">Active &amp; platform offers</h2>
          <div className="divide-y divide-gray-100">
            {offers.length === 0 && (
              <p className="py-4 text-sm text-gray-400">No offers yet.</p>
            )}
            {offers.map((offer) => (
              <div
                key={offer.id}
                className="flex items-center justify-between gap-3 py-2 text-sm"
              >
                <div>
                  <p className="font-semibold">
                    {offer.code}{" "}
                    <span
                      className={`ml-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                        offer.scope === "restaurant"
                          ? "bg-brand-100 text-brand-700"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {offer.scope}
                    </span>
                  </p>
                  <p className="text-xs text-gray-400">
                    {offer.description ||
                      `${offer.discount_type} ${offer.discount_value}`}
                    {offer.times_used > 0 && ` · used ${offer.times_used}x`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      offer.active
                        ? "bg-green-100 text-green-700"
                        : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {offer.active ? "ACTIVE" : "PAUSED"}
                  </span>
                  {offer.scope === "restaurant" && (
                    <button
                      onClick={() => toggle(offer)}
                      disabled={busy}
                      className="text-xs font-medium text-brand-600 hover:underline"
                    >
                      {offer.active ? "Pause" : "Activate"}
                    </button>
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
