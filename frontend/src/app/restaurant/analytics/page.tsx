"use client";

import { useCallback, useEffect, useState } from "react";
import { restaurantApi, reviewsApi, type RestaurantAnalytics } from "@/lib/api";
import type { Review } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";
import StatusBadge from "@/components/StatusBadge";

export default function RestaurantAnalyticsPage() {
  const [data, setData] = useState<RestaurantAnalytics | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [replies, setReplies] = useState<Record<number, string>>({});
  const [replyingId, setReplyingId] = useState<number | null>(null);
  const [replyNote, setReplyNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    restaurantApi
      .analytics()
      .then(setData)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load analytics")
      );
  }, []);

  const loadReviews = useCallback(() => {
    reviewsApi
      .myRestaurantReviews()
      .then(setReviews)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    loadReviews();
  }, [loadReviews]);

  async function submitReply(review: Review) {
    const text = (replies[review.id] ?? "").trim();
    if (!text) return;
    setReplyingId(review.id);
    setReplyNote("");
    try {
      await reviewsApi.reply(review.id, text);
      setReplyNote(`Replied to ${review.user_name}`);
      setReplies((prev) => ({ ...prev, [review.id]: "" }));
      loadReviews();
    } catch (err) {
      setReplyNote(err instanceof Error ? err.message : "Could not reply");
    } finally {
      setReplyingId(null);
    }
  }

  const maxStatus = data
    ? Math.max(1, ...Object.values(data.orders_by_status))
    : 1;

  return (
    <ProtectedRoute role="restaurant">
      <h1 className="mb-6 text-2xl font-bold">Restaurant analytics</h1>

      {error && (
        <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {data ? (
        <>
          <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div className="rounded-2xl border border-gray-200 bg-white p-5">
              <p className="text-xs text-gray-500">Total orders</p>
              <p className="text-2xl font-bold">{data.total_orders}</p>
            </div>
            <div className="rounded-2xl border border-gray-200 bg-white p-5">
              <p className="text-xs text-gray-500">Revenue</p>
              <p className="text-2xl font-bold">₹{data.revenue.toFixed(0)}</p>
            </div>
            <div className="rounded-2xl border border-gray-200 bg-white p-5">
              <p className="text-xs text-gray-500">Orders (last 7 days)</p>
              <p className="text-2xl font-bold">{data.orders_last_7_days}</p>
            </div>
            <div className="rounded-2xl border border-gray-200 bg-white p-5">
              <p className="text-xs text-gray-500">Rating</p>
              <p className="text-2xl font-bold">
                {data.avg_rating != null
                  ? `${data.avg_rating.toFixed(1)} ★`
                  : "—"}
                <span className="ml-1 text-sm font-normal text-gray-400">
                  ({data.review_count})
                </span>
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border border-gray-200 bg-white p-5">
              <h2 className="mb-3 font-semibold">Orders by status</h2>
              <div className="space-y-2">
                {Object.entries(data.orders_by_status).length === 0 && (
                  <p className="text-sm text-gray-400">No orders yet.</p>
                )}
                {Object.entries(data.orders_by_status).map(([status, count]) => (
                  <div key={status} className="flex items-center gap-3">
                    <StatusBadge status={status} />
                    <div className="h-3 flex-1 overflow-hidden rounded-full bg-gray-100">
                      <div
                        className="h-full rounded-full bg-brand-600"
                        style={{ width: `${(count / maxStatus) * 100}%` }}
                      />
                    </div>
                    <span className="w-8 text-right text-sm font-semibold">
                      {count}
                    </span>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-2xl border border-gray-200 bg-white p-5">
              <h2 className="mb-3 font-semibold">Popular items</h2>
              <div className="divide-y divide-gray-100">
                {data.popular_items.length === 0 && (
                  <p className="py-2 text-sm text-gray-400">
                    No delivered orders yet — your best-sellers will appear here.
                  </p>
                )}
                {data.popular_items.map((item, i) => (
                  <div
                    key={item.name}
                    className="flex items-center justify-between py-2 text-sm"
                  >
                    <span>
                      <span className="mr-2 font-semibold text-gray-300">
                        #{i + 1}
                      </span>
                      {item.name}
                    </span>
                    <span className="font-semibold">
                      {item.quantity} sold
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </>
      ) : (
        !error && (
          <p className="py-16 text-center text-gray-400">Loading…</p>
        )
      )}
    </ProtectedRoute>
  );
}
