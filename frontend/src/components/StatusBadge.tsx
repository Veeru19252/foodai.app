const STATUS_STYLES: Record<string, string> = {
  PLACED: "bg-blue-500/15 text-blue-300",
  CONFIRMED: "bg-indigo-500/15 text-indigo-300",
  PREPARING: "bg-amber-500/15 text-amber-300",
  OUT_FOR_DELIVERY: "bg-orange-500/15 text-orange-300",
  DELIVERED: "bg-emerald-500/15 text-emerald-300",
  CANCELLED: "bg-red-500/15 text-red-300",
};

export default function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${
        STATUS_STYLES[status] ?? "bg-surface text-muted"
      }`}
    >
      {status.replaceAll("_", " ")}
    </span>
  );
}
