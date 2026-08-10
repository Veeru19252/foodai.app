"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { notificationApi } from "@/lib/api";
import type { AppNotification } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { WS_URL } from "@/lib/api";

export default function NotificationBell() {
  const { user, token: accessToken } = useAuth();
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  // Load persisted notifications once so the badge survives reloads.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const poll = () =>
      notificationApi
        .list()
        .then((res) => {
          if (cancelled) return;
          setNotifications(res.items);
          setUnread(res.unread);
        })
        .catch(() => undefined);
    poll();
    // The WebSocket gives instant delivery; polling keeps the badge
    // authoritative even if the socket briefly drops (e.g. dev hot reload).
    const timer = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [user]);

  useEffect(() => {
    if (!user || !accessToken) return;
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let ws: WebSocket | null = null;

    const connect = () => {
      if (cancelled) return;
      ws = new WebSocket(
        `${WS_URL}/ws/notifications?token=${encodeURIComponent(accessToken)}`
      );
      socketRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!cancelled) {
          reconnectTimer = setTimeout(connect, 2000);
        }
      };
      ws.onerror = () => ws?.close();
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "connected") return;
          const message: AppNotification = {
            id: Date.now(),
            type: data.type ?? "info",
            title: data.title ?? "Notification",
            message: data.message ?? "",
            order_id: data.order_id ?? null,
            read: false,
            created_at: new Date().toISOString(),
          };
          setNotifications((prev) => [message, ...prev]);
          setUnread((n) => n + 1);
        } catch {
          /* ignore malformed frames */
        }
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
      socketRef.current = null;
    };
  }, [user, accessToken]);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && unread > 0) {
      // Opening the tray acknowledges everything.
      setUnread(0);
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
      notificationApi.markAllRead().catch(() => undefined);
    }
  }

  return (
    <div className="relative">
      <button
        onClick={toggle}
        aria-label="Notifications"
        className={`relative grid h-9 w-9 place-items-center rounded-full transition ${
          connected ? "bg-brand-50 text-brand-600" : "bg-gray-100 text-gray-500"
        }`}
      >
        🔔
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 grid h-5 w-5 place-items-center rounded-full bg-red-500 text-[10px] font-bold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-50 w-80 rounded-2xl border border-gray-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <p className="font-semibold">Notifications</p>
            <button
              onClick={() => {
                setNotifications([]);
                setUnread(0);
                notificationApi.markAllRead().catch(() => undefined);
              }}
              className="text-xs font-medium text-brand-600 hover:underline"
            >
              Clear all
            </button>
          </div>
          {notifications.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-gray-400">
              {connected ? "No notifications yet" : "Reconnecting…"}
            </p>
          ) : (
            <ul className="max-h-72 divide-y divide-gray-100 overflow-y-auto">
              {notifications.map((n) => (
                <li
                  key={n.id}
                  className={`px-4 py-3 text-sm ${n.read ? "" : "bg-brand-50/40"}`}
                >
                  <p className="font-medium">{n.message || n.title}</p>
                  {n.order_id && (
                    <Link
                      href={`/tracking/${n.order_id}`}
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
