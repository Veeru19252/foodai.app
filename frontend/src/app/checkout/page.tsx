"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ordersApi } from "@/lib/api";
import { useCart } from "@/lib/cart";
import ProtectedRoute from "@/components/ProtectedRoute";
import LocationPicker, {
  DEFAULT_POINT,
  type DeliveryPoint,
} from "@/components/LocationPicker";

const DELIVERY_PRESETS = [
  { label: "MG Road / Indiranagar", address: "Hostel Block C, MG Road", lat: 12.9719, lng: 77.6412 },
  { label: "Koramangala", address: "5th Block, Koramangala", lat: 12.9352, lng: 77.6245 },
  { label: "HSR Layout", address: "Sector 1, HSR Layout", lat: 12.9116, lng: 77.6387 },
  { label: "Whitefield", address: "ITPL Main Road, Whitefield", lat: 12.9698, lng: 77.75 },
  { label: "City Center", address: "MG Road Metro, City Center", lat: 12.977, lng: 77.596 },
];

export default function CheckoutPage() {
  const router = useRouter();
  const { items, restaurantId, subtotal, clear } = useCart();
  const [promo, setPromo] = useState("");
  const [promoMessage, setPromoMessage] = useState("");
  const [promoDiscount, setPromoDiscount] = useState(0);
  const [address, setAddress] = useState(DEFAULT_POINT.address);
  const [point, setPoint] = useState<DeliveryPoint>(DEFAULT_POINT);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (restaurantId === null) return;
  }, [restaurantId]);

  async function validatePromo() {
    if (!promo.trim()) return;
    setPromoMessage("");
    try {
      const res = await ordersApi.validatePromo(promo.trim(), subtotal);
      setPromoMessage(res.message);
      setPromoDiscount(res.ok ? res.discount : 0);
    } catch (err) {
      setPromoMessage(err instanceof Error ? err.message : "Promo check failed");
      setPromoDiscount(0);
    }
  }

  async function placeOrder(e: FormEvent) {
    e.preventDefault();
    if (!restaurantId || items.length === 0) return;
    setError("");
    setBusy(true);
    try {
      const order = await ordersApi.create({
        restaurant_id: restaurantId,
        items: items.map((i) => ({
          menu_item_id: i.menu_item_id,
          quantity: i.quantity,
        })),
        coupon_code: promo.trim() || undefined,
        delivery_lat: point.lat,
        delivery_lng: point.lng,
        delivery_address: address || point.address,
      });
      clear();
      router.push(`/tracking/${order.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to place order");
    } finally {
      setBusy(false);
    }
  }

  const total = Math.max(0, subtotal - promoDiscount);

  return (
    <ProtectedRoute role="customer">
      <h1 className="mb-6 text-2xl font-bold">Checkout</h1>

      {items.length === 0 ? (
        <div className="rounded-2xl border border-gray-200 bg-white p-10 text-center">
          <p className="mb-4 text-gray-500">Your cart is empty.</p>
          <Link
            href="/restaurants"
            className="rounded-lg bg-brand-600 px-4 py-2 font-semibold text-white hover:bg-brand-700"
          >
            Browse restaurants
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <form onSubmit={placeOrder} className="space-y-6 lg:col-span-3">
            <section className="rounded-2xl border border-gray-200 bg-white p-5">
              <h2 className="mb-3 font-semibold">Delivery details</h2>
              <label className="mb-1 block text-sm font-medium">Address</label>
              <input
                type="text"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                className="mb-4 w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                placeholder="Flat / street / landmark"
              />
              <LocationPicker
                point={point}
                onChange={(p) => {
                  setPoint(p);
                  if (!address.trim() || address === DEFAULT_POINT.address) {
                    setAddress(p.address);
                  }
                }}
                presets={DELIVERY_PRESETS}
              />
            </section>

            <section className="rounded-2xl border border-gray-200 bg-white p-5">
              <h2 className="mb-3 font-semibold">Promo code</h2>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={promo}
                  onChange={(e) => setPromo(e.target.value)}
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 uppercase focus:border-brand-500 focus:outline-none"
                  placeholder="WELCOME10"
                />
                <button
                  type="button"
                  onClick={validatePromo}
                  className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800"
                >
                  Apply
                </button>
              </div>
              {promoMessage && (
                <p
                  className={`mt-2 text-sm ${
                    promoDiscount > 0 ? "text-green-600" : "text-red-600"
                  }`}
                >
                  {promoMessage}
                </p>
              )}
            </section>

            {error && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            )}
          </form>

          <aside className="h-fit rounded-2xl border border-gray-200 bg-white p-5 lg:col-span-2">
            <h2 className="mb-3 font-semibold">Order summary</h2>
            <div className="divide-y divide-gray-100">
              {items.map((i) => (
                <div key={i.menu_item_id} className="flex justify-between py-2 text-sm">
                  <span>
                    {i.quantity} × {i.name}
                  </span>
                  <span className="font-medium">
                    ₹{(i.price * i.quantity).toFixed(0)}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-4 space-y-1 border-t border-gray-100 pt-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Subtotal</span>
                <span>₹{subtotal.toFixed(0)}</span>
              </div>
              {promoDiscount > 0 && (
                <div className="flex justify-between text-green-600">
                  <span>Promo discount</span>
                  <span>−₹{promoDiscount.toFixed(0)}</span>
                </div>
              )}
              <div className="flex justify-between text-lg font-bold">
                <span>Total</span>
                <span>₹{total.toFixed(0)}</span>
              </div>
            </div>
            <button
              type="submit"
              onClick={placeOrder}
              disabled={busy || items.length === 0}
              className="mt-4 w-full rounded-lg bg-brand-600 py-3 font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
            >
              {busy ? "Placing order…" : "Place order"}
            </button>
            <p className="mt-2 text-center text-xs text-gray-400">
              AI ETA + live rider tracking after ordering
            </p>
          </aside>
        </div>
      )}
    </ProtectedRoute>
  );
}
