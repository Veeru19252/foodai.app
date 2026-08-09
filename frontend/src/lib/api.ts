/**
 * API client for the FoodAI backend.
 *
 * Tokens live in localStorage for the demo. The client transparently refreshes
 * an expired access token once using the stored refresh token, then retries
 * the original request.
 */

import type {
  AdminOverview,
  AdminUser,
  AuthResponse,
  DriverBrief,
  ForecastSeries,
  ItemRecommendationResponse,
  MenuItem,
  OrderBrief,
  OrderDetail,
  OrderPrediction,
  Recommendation,
  Restaurant,
  RestaurantOrder,
  Review,
  SavedAddress,
  TrackingState,
} from "@/lib/types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export const WS_URL = API_URL.replace(/^http/, "ws");

const ACCESS_KEY = "foodai_access_token";
const REFRESH_KEY = "foodai_refresh_token";
const USER_KEY = "foodai_user";

function readStorage(key: string): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(key);
}

function writeStorage(key: string, value: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, value);
}

function clearStorage() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
  retry = true
): Promise<T> {
  const token = readStorage(ACCESS_KEY);
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (res.status === 401 && retry) {
    const refreshed = await tryRefresh();
    if (refreshed) return api<T>(path, options, false);
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body.detail) message = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

async function tryRefresh(): Promise<boolean> {
  const refreshToken = readStorage(REFRESH_KEY);
  if (!refreshToken) return false;
  try {
    const res = await fetch(`${API_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      clearStorage();
      return false;
    }
    const data = (await res.json()) as AuthResponse;
    writeStorage(ACCESS_KEY, data.access_token);
    writeStorage(REFRESH_KEY, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

export function saveAuth(data: AuthResponse) {
  writeStorage(ACCESS_KEY, data.access_token);
  writeStorage(REFRESH_KEY, data.refresh_token);
  writeStorage(USER_KEY, JSON.stringify(data.user));
}

export function loadUser() {
  const raw = readStorage(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function logout() {
  clearStorage();
}

// ---- typed endpoints -------------------------------------------------------

export const authApi = {
  login: (email: string, password: string) =>
    api<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  register: (name: string, email: string, password: string, role: string) =>
    api<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ name, email, password, role }),
    }),
};

export const catalogApi = {
  restaurants: (cuisine?: string) =>
    api<Restaurant[]>(
      `/restaurants${cuisine && cuisine !== "All" ? `?cuisine=${encodeURIComponent(cuisine)}` : ""}`
    ),
  cuisines: () => api<string[]>("/restaurants/cuisines"),
  menu: (restaurantId: number) =>
    api<MenuItem[]>(`/restaurants/${restaurantId}/menu`),
};

export const ordersApi = {
  create: (payload: {
    restaurant_id: number;
    items: { menu_item_id: number; quantity: number }[];
    coupon_code?: string;
    delivery_lat?: number;
    delivery_lng?: number;
    delivery_address?: string;
  }) =>
    api<OrderDetail>("/orders", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createBatch: (
    orders: {
      restaurant_id: number;
      items: { menu_item_id: number; quantity: number }[];
      coupon_code?: string;
      delivery_lat?: number;
      delivery_lng?: number;
      delivery_address?: string;
    }[]
  ) =>
    api<{ orders: OrderDetail[] }>("/orders/batch", {
      method: "POST",
      body: JSON.stringify({ orders }),
    }),
  cancel: (orderId: number) =>
    api<OrderDetail>(`/orders/${orderId}/cancel`, { method: "POST" }),
  mine: () => api<OrderBrief[]>("/orders"),
  reorder: (orderId: number) =>
    api<OrderDetail>(`/orders/${orderId}/reorder`, { method: "POST" }),
  restaurantOrders: () => api<RestaurantOrder[]>("/orders/restaurant"),
  driverOrders: () =>
    api<
      {
        delivery_id: number;
        order_id: number;
        restaurant_name: string;
        customer_name: string;
        order_status: string;
        pickup_time?: string | null;
        delivered_time?: string | null;
      }[]
    >("/orders/driver"),
  drivers: () => api<DriverBrief[]>("/orders/drivers"),
  assign: (orderId: number, driverId: number) =>
    api<{ delivery_id: number; message: string }>(
      `/orders/${orderId}/assign`,
      { method: "POST", body: JSON.stringify({ driver_id: driverId }) }
    ),
  updateStatus: (orderId: number, status: string) =>
    api<OrderDetail>(`/orders/${orderId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  validatePromo: (code: string, orderTotal: number) =>
    api<{ ok: boolean; message: string; discount: number }>(
      "/orders/promo/validate",
      { method: "POST", body: JSON.stringify({ code, order_total: orderTotal }) }
    ),
};

export const reviewsApi = {
  create: (orderId: number, rating: number, comment?: string) =>
    api<Review>("/reviews", {
      method: "POST",
      body: JSON.stringify({ order_id: orderId, rating, comment: comment || null }),
    }),
  forRestaurant: (restaurantId: number) =>
    api<Review[]>(`/reviews/restaurant/${restaurantId}`),
};

export const addressesApi = {
  list: () => api<SavedAddress[]>("/addresses"),
  create: (payload: {
    label: string;
    address: string;
    lat?: number;
    lng?: number;
  }) =>
    api<SavedAddress>("/addresses", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  remove: (addressId: number) =>
    api<{ ok: boolean }>(`/addresses/${addressId}`, { method: "DELETE" }),
};

export const trackingApi = {
  state: (orderId: number) => api<TrackingState>(`/tracking/${orderId}`),
};

export const mlApi = {
  forecastSeries: (hours = 6) =>
    api<ForecastSeries>(`/ml/forecast/series?hours=${hours}`),
  recommendations: () => api<{ recommendations: Recommendation[]; fallback: boolean }>("/ml/recommendations"),
  itemRecommendations: (restaurantId: number) =>
    api<ItemRecommendationResponse>(
      `/ml/recommendations/items?restaurant_id=${restaurantId}`
    ),
  orderPrediction: (orderId: number) =>
    api<OrderPrediction>(`/ml/order/${orderId}`),
};

export const adminApi = {
  overview: () => api<AdminOverview>("/admin/overview"),
  users: () => api<AdminUser[]>("/admin/users"),
  updateUserRole: (userId: number, role: string) =>
    api<{ id: number; role: string }>(`/admin/users/${userId}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),
  orders: () =>
    api<
      {
        id: number;
        customer_name: string;
        restaurant_name: string;
        status: string;
        total: number;
        coupon_code?: string | null;
        created_at: string;
      }[]
    >("/admin/orders"),
};
