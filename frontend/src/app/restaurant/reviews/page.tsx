"use client";

import { useCallback, useEffect, useState } from "react";
import { reviewsApi } from "@/lib/api";
import type { Review } from "@/lib/types";
import ProtectedRoute from "@/components/ProtectedRoute";

export default function RestaurantReviewsPage() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [replyText, setReplyText] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    reviewsApi
      .myRestaurantReviews()
      .then(setReviews)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load reviews")
      );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function reply(reviewId: number) {
    const text = (replyText[reviewId] ?? "").trim();
    if (!text) return;
    setBusyId(reviewId);
    setError("");
    try {
      await reviewsApi.reply(reviewId, text);
      setReplyText((prev) => ({ ...prev, [reviewId]: "" }));
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send reply");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <ProtectedRoute role="restaurant">
      <h1 className="mb-6 text-2xl font-bold">Customer reviews</h1>

      {error && (
        <p className="mb-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <div className="space-y-4">
        {reviews.length === 0 && (
          <div className="rounded-2xl border border-line bg-card p-10 text-center text-faint">
            No reviews yet — they appear here once customers rate your food.
          </div>
        )}
        {reviews.map((r) => (
          <div key={r.id} className="rounded-2xl border border-line bg-card p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-semibold">{r.user_name}</span>
                <span className="text-amber-400">
                  {"★".repeat(r.rating)}
                  <span className="text-faint">{"★".repeat(5 - r.rating)}</span>
                </span>
              </div>
              <span className="text-xs text-faint">
                {new Date(r.created_at).toLocaleDateString()}
              </span>
            </div>

            {r.comment && <p className="mt-2 text-sm text-secondary">{r.comment}</p>}

            {r.photo_url && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={r.photo_url}
                alt="Review"
                className="mt-3 h-32 w-32 rounded-xl object-cover"
              />
            )}

            {r.owner_reply ? (
              <div className="mt-3 rounded-xl bg-brand-500/10 px-3 py-2 text-sm">
                <p className="mb-1 text-xs font-semibold uppercase text-brand-300">
                  Your reply
                </p>
                <p className="text-secondary">{r.owner_reply}</p>
              </div>
            ) : (
              <div className="mt-3 flex gap-2">
                <input
                  type="text"
                  value={replyText[r.id] ?? ""}
                  onChange={(e) =>
                    setReplyText((prev) => ({ ...prev, [r.id]: e.target.value }))
                  }
                  placeholder="Thank the customer…"
                  className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-foreground placeholder:text-faint focus:border-brand-500 focus:outline-none"
                />
                <button
                  onClick={() => reply(r.id)}
                  disabled={busyId === r.id || !(replyText[r.id] ?? "").trim()}
                  className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
                >
                  {busyId === r.id ? "Replying…" : "Reply"}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </ProtectedRoute>
  );
}
