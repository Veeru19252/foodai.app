"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ordersApi, paymentsApi, trackingApi } from "@/lib/api";
import type { OrderBrief, Receipt, TrackingState } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";
import StatusBadge from "@/components/StatusBadge";
import ReviewModal from "@/components/ReviewModal";
import { Badge } from "@/components/ui/badge";

function fmtTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmtDateTime(iso?: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function OrdersPage() {
  const router = useRouter();
  const [orders, setOrders] = useState<OrderBrief[]>([]);
  const [timelines, setTimelines] = useState<Record<number, TrackingState>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [reviewTarget, setReviewTarget] = useState<OrderBrief | null>(null);
  const [reviewedIds, setReviewedIds] = useState<Set<number>>(new Set());
  const [receiptTarget, setReceiptTarget] = useState<OrderBrief | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [receiptError, setReceiptError] = useState("");
  const [emailNote, setEmailNote] = useState("");

  const load = useCallback(() => {
    ordersApi
      .mine()
      .then((rows) => {
        setOrders(rows);
        // Pull live tracking for a compact timeline preview (created → pickup → delivered).
        rows
          .filter((o) => o.status !== "CANCELLED")
          .forEach((o) => {
            trackingApi
              .state(o.id)
              .then((state) =>
                setTimelines((prev) => ({ ...prev, [o.id]: state }))
              )
              .catch(() => undefined);
          });
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load orders")
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function cancelOrder(orderId: number) {
    setBusyId(orderId);
    try {
      await ordersApi.cancel(orderId);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel order");
    } finally {
      setBusyId(null);
    }
  }

  async function reorder(orderId: number) {
    setBusyId(orderId);
    try {
      const order = await ordersApi.reorder(orderId);
      setError("");
      load();
      // Land on the fresh order's live tracking page.
      router.push(`/tracking/${order.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reorder");
      setBusyId(null);
    }
  }

  async function openReceipt(order: OrderBrief) {
    setReceiptTarget(order);
    setReceipt(null);
    setReceiptError("");
    setEmailNote("");
    try {
      setReceipt(await ordersApi.receipt(order.id));
    } catch (err) {
      setReceiptError(err instanceof Error ? err.message : "Could not load receipt");
    }
  }

  async function emailReceipt() {
    if (!receiptTarget) return;
    setEmailNote("");
    try {
      const res = await ordersApi.emailReceipt(receiptTarget.id);
      setEmailNote(`Receipt sent to ${res.to}`);
    } catch (err) {
      setEmailNote(err instanceof Error ? err.message : "Could not send receipt");
    }
  }

  const cancellable = (o: OrderBrief) =>
    o.status === "PLACED" || o.status === "CONFIRMED";

  async function markCodCollected(orderId: number) {
    setBusyId(orderId);
    try {
      await paymentsApi.codConfirm(orderId);
      setError("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update payment");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <ProtectedRoute role="customer">
      <h1 className="mb-6 text-2xl font-bold">My orders</h1>

      {error && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {loading ? (
        <p className="py-16 text-center text-gray-400">Loading…</p>
      ) : orders.length === 0 ? (
        <div className="rounded-2xl border border-gray-200 bg-white p-10 text-center">
          <p className="mb-4 text-gray-500">No orders yet.</p>
          <Link
            href="/restaurants"
            className="rounded-lg bg-brand-600 px-4 py-2 font-semibold text-white hover:bg-brand-700"
          >
            Order food
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          {orders.map((o) => {
            const reviewed = reviewedIds.has(o.id);
            const timeline = timelines[o.id];
            const steps = timeline
              ? [
                  { label: "Ordered", time: fmtTime(timeline.created_at) },
                  { label: "Picked up", time: fmtTime(timeline.pickup_time) },
                  { label: "Delivered", time: fmtTime(timeline.delivered_time) },
                ].filter((s) => s.time)
              : [];
            return (
              <div
                key={o.id}
                className="rounded-2xl border border-gray-200 bg-white px-5 py-4 shadow-sm"
              >
                <Link
                  href={`/tracking/${o.id}`}
                  className="flex flex-wrap items-center justify-between gap-3"
                >
                  <div>
                    <p className="font-semibold">{o.restaurant_name}</p>
                    <p className="text-xs text-gray-500">
                      #{o.id} · {new Date(o.created_at).toLocaleString()}
                      {o.delivery_city ? ` · ${o.delivery_city}` : ""}
                    </p>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="font-semibold">₹{o.total.toFixed(0)}</span>
                    {o.scheduled_for && (
                      <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700">
                        Scheduled · {fmtDateTime(o.scheduled_for)}
                      </span>
                    )}
                    {o.payment_status && (
                      <Badge
                        variant={
                          o.payment_status === "PAID"
                            ? "success"
                            : o.payment_status === "FAILED"
                            ? "danger"
                            : "warning"
                        }
                      >
                        {o.payment_method === "COD" ? "COD" : "Card/UPI"} ·{" "}
                        {o.payment_status}
                      </Badge>
                    )}
                    <StatusBadge status={o.status} />
                  </div>
                </Link>
                {steps.length > 0 && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                    {steps.map((s, i) => (
                      <span key={s.label} className="flex items-center gap-2">
                        {i > 0 && <span className="text-gray-300">→</span>}
                        <span>
                          {s.label}{" "}
                          <span className="font-medium text-gray-700">
                            {s.time}
                          </span>
                        </span>
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-3 flex gap-2 border-t border-gray-100 pt-3">
                  {o.status !== "CANCELLED" && (
                    <Link
                      href={`/tracking/${o.id}`}
                      className="text-sm font-semibold text-brand-600 hover:underline"
                    >
                      Track →
                    </Link>
                  )}
                  {o.status !== "CANCELLED" && (
                    <button
                      onClick={() => reorder(o.id)}
                      disabled={busyId === o.id}
                      className="text-sm font-semibold text-brand-600 hover:underline disabled:opacity-60"
                    >
                      {busyId === o.id ? "Reordering…" : "Order again"}
                    </button>
                  )}
                  {o.payment_method === "COD" &&
                    o.payment_status === "PENDING" && (
                      <button
                        onClick={() => markCodCollected(o.id)}
                        disabled={busyId === o.id}
                        className="text-sm font-semibold text-emerald-600 hover:underline disabled:opacity-60"
                      >
                        {busyId === o.id ? "Updating…" : "Mark COD collected"}
                      </button>
                    )}
                  <button
                    onClick={() => openReceipt(o)}
                    className="text-sm font-semibold text-gray-600 hover:underline"
                  >
                    Receipt
                  </button>
                  {cancellable(o) && (
                    <button
                      onClick={() => cancelOrder(o.id)}
                      disabled={busyId === o.id}
                      className="text-sm font-medium text-red-600 hover:underline disabled:opacity-60"
                    >
                      {busyId === o.id ? "Cancelling…" : "Cancel order"}
                    </button>
                  )}
                  {o.status === "DELIVERED" &&
                    (reviewed ? (
                      <span className="text-sm text-gray-400">✓ Reviewed</span>
                    ) : (
                      <button
                        onClick={() => setReviewTarget(o)}
                        className="text-sm font-semibold text-amber-600 hover:underline"
                      >
                        Rate order
                      </button>
                    ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {reviewTarget && (
        <ReviewModal
          orderId={reviewTarget.id}
          restaurantName={reviewTarget.restaurant_name}
          onClose={() => setReviewTarget(null)}
          onDone={() => {
            setReviewedIds((prev) => new Set(prev).add(reviewTarget.id));
            setReviewTarget(null);
          }}
        />
      )}

      {receiptTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => setReceiptTarget(null)}
        >
          <div
            className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl bg-white p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold">
              Receipt · {receiptTarget.restaurant_name}
            </h2>
            <p className="mb-4 text-xs text-gray-500">Order #{receiptTarget.id}</p>

            {receiptError && (
              <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {receiptError}
              </p>
            )}

            {receipt && (
              <>
                <div className="divide-y divide-gray-100">
                  {receipt.items.map((item, i) => (
                    <div
                      key={i}
                      className="flex justify-between py-1.5 text-sm"
                    >
                      <span>
                        {item.quantity} × {item.name}
                      </span>
                      <span className="font-medium">
                        ₹{(item.price * item.quantity).toFixed(0)}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-3 space-y-1 border-t border-gray-100 pt-3 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-500">Food total</span>
                    <span>₹{receipt.food_total.toFixed(0)}</span>
                  </div>
                  {receipt.discount_amount > 0 && (
                    <div className="flex justify-between text-green-600">
                      <span>Promo discount</span>
                      <span>−₹{receipt.discount_amount.toFixed(0)}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-gray-500">
                      Delivery fee
                      {receipt.surge_multiplier > 1.0 && (
                        <span className="ml-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700">
                          {receipt.surge_multiplier.toFixed(1)}×
                        </span>
                      )}
                    </span>
                    <span>₹{receipt.delivery_fee.toFixed(0)}</span>
                  </div>
                  <div className="flex justify-between text-base font-bold">
                    <span>Grand total</span>
                    <span>₹{receipt.grand_total.toFixed(0)}</span>
                  </div>
                </div>
                <p className="mt-3 text-xs text-gray-400">
                  Paid by {receipt.payment_method} · {receipt.payment_status}
                  {receipt.billed_to ? ` · ${receipt.billed_to}` : ""}
                </p>
                <div className="mt-4 flex gap-2">
                  <button
                    onClick={emailReceipt}
                    className="flex-1 rounded-lg bg-brand-600 px-3 py-2 font-semibold text-white hover:bg-brand-700"
                  >
                    Email receipt
                  </button>
                  <button
                    onClick={() => setReceiptTarget(null)}
                    className="flex-1 rounded-lg border border-gray-300 px-3 py-2 font-medium hover:bg-gray-100"
                  >
                    Close
                  </button>
                </div>
                {emailNote && (
                  <p
                    className={`mt-2 text-center text-xs ${
                      emailNote.startsWith("Receipt")
                        ? "text-green-600"
                        : "text-red-600"
                    }`}
                  >
                    {emailNote}
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </ProtectedRoute>
  );
}
