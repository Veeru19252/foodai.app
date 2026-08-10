"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { addressesApi, ordersApi, paymentsApi } from "@/lib/api";
import type { SurgeState } from "@/lib/types";
import { useCart } from "@/lib/cart";
import type { SavedAddress } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";
import LocationPicker, {
  type DeliveryPoint,
} from "@/components/LocationPicker";
import {
  CITY_CENTERS,
  DELIVERY_CITIES,
  DELIVERY_PRESETS,
  DEFAULT_CITY,
  DEFAULT_POINT,
  STATE_BY_CITY,
  presetByLabel,
} from "@/lib/deliveryPresets";
import {
  PaymentMethodPicker,
  type PaymentMethod,
} from "@/components/PaymentMethodPicker";

// Test-mode Razorpay secret — matches backend/routers/payments.py
// RAZORPAY_KEY_SECRET fallback. In production the Razorpay Checkout SDK
// produces the signature; here we simulate it so verify() exercises the
// real HMAC-SHA256 algorithm end to end.
const TEST_RAZORPAY_SECRET = "foodai_demo_secret";

async function simulateRazorpaySignature(orderId: string, paymentId: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(TEST_RAZORPAY_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const data = encoder.encode(`${orderId}|${paymentId}`);
  const signature = await crypto.subtle.sign("HMAC", key, data);
  return Array.from(new Uint8Array(signature))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export default function CheckoutPage() {
  const router = useRouter();
  const { items, groups, subtotal, clear } = useCart();
  const [promo, setPromo] = useState("");
  const [promoMessage, setPromoMessage] = useState("");
  const [promoDiscount, setPromoDiscount] = useState(0);
  const [address, setAddress] = useState(DEFAULT_POINT.address);
  const [point, setPoint] = useState<DeliveryPoint>(DEFAULT_POINT);
  const [saved, setSaved] = useState<SavedAddress[]>([]);
  const [saveLabel, setSaveLabel] = useState("Home");
  const [saveNote, setSaveNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [surge, setSurge] = useState<SurgeState | null>(null);
  const [scheduleMode, setScheduleMode] = useState<"now" | "later">("now");
  const [scheduledFor, setScheduledFor] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("COD");
  const [phone, setPhone] = useState("");
  const [city, setCity] = useState(DEFAULT_CITY);
  const [stateName, setStateName] = useState(STATE_BY_CITY[DEFAULT_CITY] ?? "");
  const [pincode, setPincode] = useState("");

  useEffect(() => {
    ordersApi
      .surge()
      .then(setSurge)
      .catch(() => setSurge(null));
  }, []);

  useEffect(() => {
    addressesApi
      .list()
      .then(setSaved)
      .catch(() => setSaved([]));
  }, []);

  function applyAddress(s: SavedAddress) {
    setAddress(s.address);
    if (s.lat != null && s.lng != null) {
      setPoint({ address: s.address, lat: s.lat, lng: s.lng });
    }
  }

  async function saveCurrentAddress() {
    if (!address.trim()) return;
    setSaveNote("");
    try {
      await addressesApi.create({
        label: saveLabel.trim() || "Home",
        address: address.trim(),
        lat: point.lat,
        lng: point.lng,
      });
      setSaved(await addressesApi.list());
      setSaveNote("Address saved");
    } catch (err) {
      setSaveNote(err instanceof Error ? err.message : "Could not save address");
    }
  }

  async function validatePromo() {
    if (!promo.trim()) return;
    setPromoMessage("");
    // Promos apply to the first restaurant's order in a multi-restaurant cart.
    const primarySubtotal = groups[0]?.subtotal ?? 0;
    try {
      const res = await ordersApi.validatePromo(promo.trim(), primarySubtotal);
      setPromoMessage(res.message);
      setPromoDiscount(res.ok ? res.discount : 0);
    } catch (err) {
      setPromoMessage(err instanceof Error ? err.message : "Promo check failed");
      setPromoDiscount(0);
    }
  }

  async function placeOrder(e: FormEvent) {
    e.preventDefault();
    if (items.length === 0) return;
    setError("");
    setBusy(true);
    try {
      const res = await ordersApi.createBatch(
        groups.map((g, idx) => ({
          restaurant_id: g.restaurant_id,
          items: g.items.map((i) => ({
            menu_item_id: i.menu_item_id,
            quantity: i.quantity,
          })),
          coupon_code: idx === 0 ? promo.trim() || undefined : undefined,
          delivery_lat: point.lat,
          delivery_lng: point.lng,
          delivery_address: address || point.address,
          scheduled_for:
            scheduleMode === "later" && scheduledFor
              ? new Date(scheduledFor).toISOString()
              : undefined,
          payment_method: paymentMethod,
          delivery_phone: phone.trim() || undefined,
          delivery_city: city.trim() || undefined,
          delivery_state: stateName.trim() || undefined,
          delivery_pincode: pincode.trim() || undefined,
        }))
      );
      const order = res.orders[0];

      // Razorpay (test mode): create the intent, simulate the client-side
      // signature, then verify it against the backend (real HMAC-SHA256).
      if (paymentMethod === "RAZORPAY") {
        const intent = await paymentsApi.razorpayOrder(order.id);
        const mockPaymentId = `pay_${Math.random().toString(36).slice(2, 10)}`;
        const signature = await simulateRazorpaySignature(
          intent.razorpay_order_id,
          mockPaymentId
        );
        await paymentsApi.razorpayVerify({
          order_id: order.id,
          razorpay_order_id: intent.razorpay_order_id,
          razorpay_payment_id: mockPaymentId,
          razorpay_signature: signature,
        });
      }

      clear();
      // Land on the first order's live tracking page (others stay visible
      // under "My orders").
      router.push(`/tracking/${order.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to place order");
    } finally {
      setBusy(false);
    }
  }

  const deliveryFee = surge?.delivery_fee ?? 0;
  const total = Math.max(0, subtotal - promoDiscount);
  const grandTotal = total + deliveryFee;

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
                  const preset = presetByLabel(p.address);
                  if (preset) {
                    setCity(preset.city);
                    setStateName(STATE_BY_CITY[preset.city] ?? "");
                  }
                }}
                presets={DELIVERY_PRESETS}
                cities={DELIVERY_CITIES}
                city={city}
                onCityChange={(c) => {
                  setCity(c);
                  setStateName(STATE_BY_CITY[c] ?? "");
                  const first = DELIVERY_PRESETS.find((p) => p.city === c);
                  if (first) {
                    setPoint({ lat: first.lat, lng: first.lng, address: first.address });
                    if (!address.trim() || address === DEFAULT_POINT.address) {
                      setAddress(first.address);
                    }
                  }
                }}
                cityCenters={CITY_CENTERS}
              />
              <div className="mt-3 border-t border-gray-100 pt-3">
                <p className="mb-2 text-sm font-medium">Saved addresses</p>
                {saved.length > 0 && (
                  <div className="mb-2 flex flex-wrap gap-2">
                    {saved.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => applyAddress(s)}
                        className="rounded-full border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:border-brand-500 hover:text-brand-700"
                      >
                        {s.label}
                      </button>
                    ))}
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    value={saveLabel}
                    onChange={(e) => setSaveLabel(e.target.value)}
                    className="w-28 rounded-lg border border-gray-300 px-2 py-1.5 text-xs focus:border-brand-500 focus:outline-none"
                    placeholder="Label"
                  />
                  <button
                    type="button"
                    onClick={saveCurrentAddress}
                    className="rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-200"
                  >
                    Save current address
                  </button>
                  {saveNote && (
                    <span className="text-xs text-green-600">{saveNote}</span>
                  )}
                </div>
              </div>
            </section>

            <section className="rounded-2xl border border-gray-200 bg-white p-5">
              <h2 className="mb-3 font-semibold">Payment method</h2>
              <PaymentMethodPicker
                value={paymentMethod}
                onChange={setPaymentMethod}
                total={grandTotal}
              />
            </section>

            <section className="rounded-2xl border border-gray-200 bg-white p-5">
              <h2 className="mb-3 font-semibold">Contact & locality</h2>
              <div className="grid grid-cols-2 gap-3">
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  maxLength={15}
                  className="col-span-2 rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                  placeholder="Phone (10 digits)"
                />
                <input
                  type="text"
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  maxLength={64}
                  className="rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                  placeholder="City"
                />
                <input
                  type="text"
                  value={stateName}
                  onChange={(e) => setStateName(e.target.value)}
                  maxLength={64}
                  className="rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                  placeholder="State"
                />
                <input
                  type="text"
                  value={pincode}
                  onChange={(e) => setPincode(e.target.value)}
                  maxLength={10}
                  className="rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                  placeholder="Pincode"
                />
              </div>
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

            <section className="rounded-2xl border border-gray-200 bg-white p-5">
              <h2 className="mb-3 font-semibold">Schedule delivery</h2>
              <div className="mb-3 flex gap-2">
                <button
                  type="button"
                  onClick={() => setScheduleMode("now")}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm font-semibold ${
                    scheduleMode === "now"
                      ? "border-brand-600 bg-brand-50 text-brand-700"
                      : "border-gray-300 text-gray-600 hover:border-brand-500"
                  }`}
                >
                  Deliver now
                </button>
                <button
                  type="button"
                  onClick={() => setScheduleMode("later")}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm font-semibold ${
                    scheduleMode === "later"
                      ? "border-brand-600 bg-brand-50 text-brand-700"
                      : "border-gray-300 text-gray-600 hover:border-brand-500"
                  }`}
                >
                  Schedule later
                </button>
              </div>
              {scheduleMode === "later" && (
                <input
                  type="datetime-local"
                  value={scheduledFor}
                  onChange={(e) => setScheduledFor(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
                />
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
            <div className="space-y-3">
              {groups.map((g) => (
                <div
                  key={g.restaurant_id}
                  className="rounded-xl bg-gray-50 p-3"
                >
                  <p className="mb-1 text-sm font-semibold text-gray-700">
                    {g.restaurant_name}
                  </p>
                  <div className="divide-y divide-gray-100">
                    {g.items.map((i) => (
                      <div
                        key={i.menu_item_id}
                        className="flex justify-between py-1.5 text-sm"
                      >
                        <span>
                          {i.quantity} × {i.name}
                        </span>
                        <span className="font-medium">
                          ₹{(i.price * i.quantity).toFixed(0)}
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-1 text-right text-xs text-gray-500">
                    Group subtotal ₹{g.subtotal.toFixed(0)}
                  </p>
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
              {groups.length > 1 && promo.trim() && (
                <p className="text-xs text-gray-500">
                  Promo applies to {groups[0].restaurant_name}
                </p>
              )}
              {surge ? (
                <div className="flex justify-between">
                  <span className="text-gray-500">
                    Delivery fee
                    {surge.surge_multiplier > 1.0 && (
                      <span className="ml-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700">
                        {surge.surge_multiplier.toFixed(1)}× SURGE
                      </span>
                    )}
                  </span>
                  <span>₹{deliveryFee.toFixed(0)}</span>
                </div>
              ) : (
                <div className="flex justify-between">
                  <span className="text-gray-500">Delivery fee</span>
                  <span className="text-gray-400">calculating…</span>
                </div>
              )}
              {scheduleMode === "later" && (
                <p className="text-xs text-gray-500">
                  Scheduled order — kitchen prepares it at the chosen time.
                </p>
              )}
              <div className="flex justify-between text-lg font-bold">
                <span>Total</span>
                <span>₹{grandTotal.toFixed(0)}</span>
              </div>
            </div>
            <button
              type="submit"
              onClick={placeOrder}
              disabled={busy || items.length === 0}
              className="mt-4 w-full rounded-lg bg-brand-600 py-3 font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
            >
              {busy
                ? "Placing orders…"
                : `Place ${groups.length > 1 ? `${groups.length} orders` : "order"} · ₹${grandTotal.toFixed(0)}`}
            </button>
            <p className="mt-2 text-center text-xs text-gray-400">
              {groups.length > 1
                ? "Each restaurant receives its own order and rider"
                : "AI ETA + live rider tracking after ordering"}
            </p>
          </aside>
        </div>
      )}
    </ProtectedRoute>
  );
}
