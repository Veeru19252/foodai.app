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
  AppNotification,
  AuthResponse,
  CreateOrderPayload,
  DriverBrief,
  ForecastSeries,
  ItemRecommendationResponse,
  MenuItem,
  OrderBrief,
  OrderDetail,
  OrderPrediction,
  OtpRequestResponse,
  OtpVerifyResponse,
  PaymentIntent,
  PaymentStatus,
  RazorpayVerifyPayload,
  Receipt,
  Recommendation,
  Restaurant,
  RestaurantOrder,
  Review,
  SavedAddress,
  SurgeState,
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
  otpRequest: (phone: string) =>
    api<OtpRequestResponse>("/auth/otp/request", {
      method: "POST",
      body: JSON.stringify({ phone }),
    }),
  otpVerify: (phone: string, code: string) =>
    api<OtpVerifyResponse>("/auth/otp/verify", {
      method: "POST",
      body: JSON.stringify({ phone, code }),
    }),
};

export const catalogApi = {
  restaurants: (
    cuisine?: string,
    city?: string,
    lat?: number,
    lng?: number
  ) => {
    const params: string[] = [];
    if (cuisine && cuisine !== "All") {
      params.push(`cuisine=${encodeURIComponent(cuisine)}`);
    }
    // City is included only when truthy; lat/lng only when both are provided.
    if (city) params.push(`city=${encodeURIComponent(city)}`);
    if (lat !== undefined && lng !== undefined) {
      params.push(`lat=${lat}`, `lng=${lng}`);
    }
    return api<Restaurant[]>(
      `/restaurants${params.length ? `?${params.join("&")}` : ""}`
    );
  },
  cuisines: () => api<string[]>("/restaurants/cuisines"),
  cities: () =>
    api<{ cities: string[] }>("/restaurants/cities").then((res) => res.cities),
  menu: (restaurantId: number) =>
    api<MenuItem[]>(`/restaurants/${restaurantId}/menu`),
};

export interface RestaurantOffer {
  id: number;
  code: string;
  description?: string | null;
  discount_type: string;
  discount_value: number;
  min_order_value: number;
  max_discount?: number | null;
  valid_until?: string | null;
  usage_limit?: number | null;
  times_used: number;
  active: boolean;
  scope: "restaurant" | "platform";
}

export interface RestaurantAnalytics {
  restaurant_id: number;
  restaurant_name: string;
  total_orders: number;
  revenue: number;
  orders_by_status: Record<string, number>;
  avg_rating: number | null;
  review_count: number;
  popular_items: { name: string; quantity: number }[];
  orders_last_7_days: number;
}

export const restaurantApi = {
  me: () =>
    api<
      Restaurant & { reviews_rating: number; review_count: number }
    >("/restaurants/me"),
  myMenu: () => api<MenuItem[]>("/restaurants/me/menu"),
  addMenuItem: (payload: {
    name: string;
    price: number;
    prep_time_min: number;
  }) =>
    api<{ id: number; name: string; price: number }>("/restaurants/me/menu", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateMenuItem: (
    itemId: number,
    payload: { name?: string; price?: number; prep_time_min?: number }
  ) =>
    api<{ id: number; name: string; price: number }>(
      `/restaurants/me/menu/${itemId}`,
      { method: "PATCH", body: JSON.stringify(payload) }
    ),
  deleteMenuItem: (itemId: number) =>
    api<{ ok: boolean }>(`/restaurants/me/menu/${itemId}`, {
      method: "DELETE",
    }),
  offers: () => api<RestaurantOffer[]>("/restaurants/me/offers"),
  createOffer: (payload: {
    code: string;
    description?: string;
    discount_type: string;
    discount_value: number;
    min_order_value?: number;
    max_discount?: number;
    valid_until?: string;
    usage_limit?: number;
  }) =>
    api<RestaurantOffer>("/restaurants/me/offers", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  toggleOffer: (offerId: number) =>
    api<RestaurantOffer>(`/restaurants/me/offers/${offerId}/toggle`, {
      method: "PATCH",
    }),
  analytics: () => api<RestaurantAnalytics>("/restaurants/me/analytics"),
};

export const ordersApi = {
  create: (payload: CreateOrderPayload) =>
    api<OrderDetail>("/orders", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createBatch: (orders: CreateOrderPayload[]) =>
    api<{ orders: OrderDetail[] }>("/orders/batch", {
      method: "POST",
      body: JSON.stringify({ orders }),
    }),
  surge: () => api<SurgeState>("/orders/surge"),
  receipt: (orderId: number) => api<Receipt>(`/orders/${orderId}/receipt`),
  emailReceipt: (orderId: number) =>
    api<{ emailed: boolean; to: string }>(`/orders/${orderId}/receipt/email`, {
      method: "POST",
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
  autoAssign: (orderId: number) =>
    api<{ delivery_id: number; driver_name: string; message: string; reason: string }>(
      `/orders/${orderId}/auto-assign`,
      { method: "POST" }
    ),
  nudge: (orderId: number) =>
    api<{
      order_id: number;
      status: string;
      delay_min: number;
      risk: "LOW" | "MEDIUM" | "HIGH";
      message: string;
      eta_min: number | null;
      progress: number;
      elapsed_min?: number;
    }>(`/orders/${orderId}/nudge`),
  driverEarnings: () =>
    api<{
      per_delivery_rate: number;
      per_km_rate: number;
      total_earnings: number;
      total_deliveries: number;
      completed_deliveries: number;
      active_deliveries: number;
      recent: {
        delivery_id: number;
        order_id: number;
        restaurant_name: string;
        customer_name: string;
        distance_km: number;
        earned: number;
        completed_at: string | null;
      }[];
    }>("/orders/driver/earnings"),
  updateStatus: (orderId: number, status: string) =>
    api<OrderDetail>(`/orders/${orderId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  updateDriverLocation: (orderId: number, lat: number, lng: number) =>
    api<{
      ok: boolean;
      order_id: number;
      driver_lat: number;
      driver_lng: number;
      updated_at: string;
    }>(`/orders/${orderId}/driver-location`, {
      method: "PUT",
      body: JSON.stringify({ lat, lng }),
    }),
  validatePromo: (code: string, orderTotal: number, restaurantId?: number) =>
    api<{ ok: boolean; message: string; discount: number }>(
      "/orders/promo/validate",
      {
        method: "POST",
        body: JSON.stringify({
          code,
          order_total: orderTotal,
          restaurant_id: restaurantId,
        }),
      }
    ),
};

export const reviewsApi = {
  create: (orderId: number, rating: number, comment?: string, photoUrl?: string) =>
    api<Review>("/reviews", {
      method: "POST",
      body: JSON.stringify({
        order_id: orderId,
        rating,
        comment: comment || null,
        photo_url: photoUrl || null,
      }),
    }),
  forRestaurant: (restaurantId: number) =>
    api<Review[]>(`/reviews/restaurant/${restaurantId}`),
  myRestaurantReviews: () => api<Review[]>("/reviews/me"),
  reply: (reviewId: number, reply: string) =>
    api<Review>(`/reviews/${reviewId}/reply`, {
      method: "POST",
      body: JSON.stringify({ reply }),
    }),
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

export const paymentsApi = {
  status: (orderId: number) =>
    api<PaymentStatus>(`/payments/orders/${orderId}`),
  codConfirm: (orderId: number) =>
    api<PaymentStatus>(`/payments/orders/${orderId}/cod/confirm`, {
      method: "POST",
    }),
  codCancel: (orderId: number) =>
    api<PaymentStatus>(`/payments/orders/${orderId}/cod/cancel`, {
      method: "POST",
    }),
  razorpayOrder: (orderId: number) =>
    api<PaymentIntent>(`/payments/razorpay/order`, {
      method: "POST",
      body: JSON.stringify({ order_id: orderId }),
    }),
  razorpayVerify: (payload: RazorpayVerifyPayload) =>
    api<PaymentStatus>(`/payments/razorpay/verify`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export const notificationApi = {
  list: () => api<{ items: AppNotification[]; unread: number }>("/notifications"),
  markRead: (id: number) =>
    api<AppNotification>(`/notifications/${id}/read`, { method: "POST" }),
  markAllRead: () =>
    api<{ ok: boolean }>("/notifications/read-all", { method: "POST" }),
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
  retrainForecast: () =>
    api<{
      ok: boolean;
      model_path: string;
      samples: { corpus: number; live: number; total: number };
      demand_buckets: number;
      metrics: {
        moving_average: { mae: number; rmse: number; mape: number };
        xgboost: { mae: number; rmse: number; mape: number };
      };
      retrained_at: string;
    }>("/ml/forecast/retrain", { method: "POST" }),
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
