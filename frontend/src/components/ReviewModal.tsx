"use client";

import { useState } from "react";
import { reviewsApi } from "@/lib/api";

export default function ReviewModal({
  orderId,
  restaurantName,
  onClose,
  onDone,
}: {
  orderId: number;
  restaurantName: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [photoUrl, setPhotoUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await reviewsApi.create(
        orderId,
        rating,
        comment.trim() || undefined,
        photoUrl.trim() || undefined
      );
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit review");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-2xl border border-line bg-card p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold">Rate {restaurantName}</h2>
        <p className="mb-3 text-xs text-muted">Order #{orderId}</p>

        <div className="mb-3 flex justify-center gap-1 text-3xl" role="radiogroup" aria-label="Star rating">
          {[1, 2, 3, 4, 5].map((star) => (
            <button
              key={star}
              type="button"
              onClick={() => setRating(star)}
              aria-label={`${star} star${star === 1 ? "" : "s"}`}
              className={star <= rating ? "text-amber-400" : "text-faint"}
            >
              ★
            </button>
          ))}
        </div>

        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="What did you like (or not)?"
          className="mb-3 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-foreground placeholder:text-faint focus:border-brand-500 focus:outline-none"
          rows={3}
        />

        <input
          type="url"
          value={photoUrl}
          onChange={(e) => setPhotoUrl(e.target.value)}
          placeholder="Photo URL (optional)"
          className="mb-3 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-foreground placeholder:text-faint focus:border-brand-500 focus:outline-none"
        />

        {error && (
          <p className="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </p>
        )}

        <div className="flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 rounded-lg border border-line px-3 py-2 font-medium text-secondary hover:bg-surface"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={busy}
            className="flex-1 rounded-lg bg-brand-600 px-3 py-2 font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {busy ? "Submitting…" : "Submit review"}
          </button>
        </div>
      </div>
    </div>
  );
}
