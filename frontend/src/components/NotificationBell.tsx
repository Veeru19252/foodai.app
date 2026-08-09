"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { WS_URL } from "@/lib/api";

interface Notification {
  id: number;
  message: string;
  orderId?: number;
  restaurantName?: string;
  customerName?: string;
  type: string;
}

let nextId = 1;

export default function NotificationBell() {
  const { user, token: accessToken } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!user || !accessToken) return;
    const ws = new WebSocket(
      `${WS_URL}/ws/notifications?token=${encodeURIComponent(accessToken)}`
    );
    socketRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "connected") return;
        if (data.type === "delivery_assigned") {
          setNotifications((prev) => [
            {
              id: nextId++,
              message: data.message ?? "New delivery assigned",
              orderId: data.order_id,
              restaurantName: data.restaurant_name,
              customerName: data.customer_name,
              type: data.type,
            },
            ...prev,
          ]);
        }
      } catch {
        /* ignore malformed frames */
      }
    };
    return () => {
      ws.close();
      socketRef.current = null;
    };
  }, [user, accessToken]);

  const unread = notifications.length;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Notifications"
        className={`relative grid h-9 w-9 place-items-center rounded-full transition ${
          connected ? "bg-brand-50 text-brand-600" : "bg-gray-100 text-gray-500"
        }`}
      >
        🔔
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 grid h-5 w-5 place-items-center rounded-full bg-red-500 text-[10px] font-bold text-white">
            {unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-50 w-80 rounded-2xl border border-gray-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <p className="font-semibold">Notifications</p>
            {unread > 0 && (
              <button
                onClick={() => setNotifications([])}
                className="text-xs font-medium text-brand-600 hover:underline"
              >
                Clear all
              </button>
            )}
          </div>
          {notifications.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-gray-400">
              {connected ? "No notifications yet" : "Reconnecting…"}
            </p>
          ) : (
            <ul className="max-h-72 divide-y divide-gray-100 overflow-y-auto">
              {notifications.map((n) => (
                <li key={n.id} className="px-4 py-3 text-sm">
                  <p className="font-medium">{n.message}</p>
                  {n.restaurantName && (
                    <p className="text-xs text-gray-500">{n.restaurantName}</p>
                  )}
                  {n.orderId && (
                    <Link
                      href={`/tracking/${n.orderId}`}
                      onClick={() => setOpen(false)}
                      className="mt-1 inline-block text-xs font-semibold text-brand-600 hover:underline"
                    >
                      View order →
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
