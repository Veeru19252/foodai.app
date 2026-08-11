export type Role = "customer" | "restaurant" | "delivery" | "admin";

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  /** Verified mobile number (stamped after the first OTP verification). */
  phone?: string | null;
  phone_verified_at?: string | null;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

// ---- phone OTP (pre-order verification) ------------------------------------

export interface OtpRequestResponse {
  ok: boolean;
  expires_in: number;
  test_mode: boolean;
  /** Demo-only: the OTP is returned because no SMS provider is wired up. */
  dev_code?: string | null;
}

export interface OtpVerifyResponse {
  ok: boolean;
  otp_token?: string | null;
  phone?: string | null;
  message?: string;
  /** The verified user when a logged-in customer verifies, else null. */
  user?: User | null;
}

/** Body for a single /orders create (also used inside /orders/batch). */
export interface CreateOrderPayload {
  restaurant_id: number;
  items: { menu_item_id: number; quantity: number }[];
  coupon_code?: string;
  delivery_lat?: number;
  delivery_lng?: number;
  delivery_address?: string;
  payment_method?: string;
  delivery_phone?: string;
  delivery_city?: string;
  delivery_state?: string;
  delivery_pincode?: string;
  scheduled_for?: string;
  /** Pre-order gate fields — required before the order is accepted. */
  otp_token?: string;
  location_confirmed?: boolean;
  location_confirm_lat?: number;
  location_confirm_lng?: number;
}

export interface Restaurant {
  id: number;
  name: string;
  address: string;
  cuisine: string;
  rating: number;
  review_count: number;
  reviews_rating: number;
  city?: string | null;
  lat?: number | null;
  lng?: number | null;
  /** Distance to the requested lat/lng — null when no location was sent. */
  distance_km?: number | null;
  /** Estimated delivery time — null when no location was sent. */
  eta_min?: number | null;
}

export interface MenuItem {
  id: number;
  name: string;
  price: number;
  prep_time_min: number;
}

export interface CartLine {
  menu_item_id: number;
  restaurant_id: number;
  restaurant_name: string;
  name: string;
  price: number;
  quantity: number;
}

export interface CartGroup {
  restaurant_id: number;
  restaurant_name: string;
  items: CartLine[];
  subtotal: number;
}

export interface Review {
  id: number;
  restaurant_id: number;
  user_name: string;
  rating: number;
  comment?: string | null;
  photo_url?: string | null;
  owner_reply?: string | null;
  replied_at?: string | null;
  created_at: string;
}

export interface AppNotification {
  id: number;
  type: string;
  title: string;
  message?: string | null;
  order_id?: number | null;
  read: boolean;
  created_at: string;
}

export interface SurgeState {
  hour: number;
  total_load: number;
  surge_multiplier: number;
  delivery_fee: number;
}

export interface Receipt {
  order_id: number;
  restaurant_name: string;
  customer_name: string;
  billed_to?: string | null;
  items: OrderItemOut[];
  food_total: number;
  discount_amount: number;
  delivery_fee: number;
  surge_multiplier: number;
  grand_total: number;
  payment_method: string;
  payment_status: string;
  placed_at: string;
}

export interface OrderBrief {
  id: number;
  restaurant_id: number;
  restaurant_name: string;
  status: string;
  total: number;
  created_at: string;
  delivery_address?: string | null;
  delivery_city?: string | null;
  scheduled_for?: string | null;
  // Layer 4: payment info is returned on every order (list + detail).
  payment_method?: string;
  payment_status?: string;
}

export interface RestaurantOrder {
  id: number;
  customer_name: string;
  status: string;
  total: number;
  created_at: string;
  assigned_driver_id?: number | null;
  assigned_driver_name?: string | null;
}

export interface OrderItemOut {
  name: string;
  quantity: number;
  price: number;
}

export interface OrderDetail extends OrderBrief {
  customer_name: string;
  coupon_code?: string | null;
  discount_amount: number;
  delivery_lat?: number | null;
  delivery_lng?: number | null;
  payment_method?: string;
  payment_status?: string;
  delivery_fee?: number;
  surge_multiplier?: number;
  delivery_phone?: string | null;
  delivery_city?: string | null;
  delivery_state?: string | null;
  delivery_pincode?: string | null;
  /** Pre-order gate: the phone was OTP-verified and the location confirmed. */
  phone_verified?: boolean;
  location_confirmed?: boolean;
  location_confirm_lat?: number | null;
  location_confirm_lng?: number | null;
  items: OrderItemOut[];
}

export interface TrackingState {
  order_id: number;
  status: string;
  restaurant_name: string;
  restaurant_city?: string | null;
  customer_name: string;
  delivery_address?: string | null;
  delivery_city?: string | null;
  route: number[][];
  route_distance_km: number;
  rider_lat: number;
  rider_lng: number;
  progress: number;
  eta_min?: number | null;
  eta_source: string;
  /** "live" when the driver is sharing GPS, else "simulated". */
  position_source?: "live" | "simulated";
  created_at?: string | null;
  pickup_time?: string | null;
  delivered_time?: string | null;
}

export interface DriverBrief {
  id: number;
  name: string;
  email: string;
}

export interface AdminOverview {
  users: Record<string, number>;
  orders_by_status: Record<string, number>;
  total_orders: number;
  revenue: number;
  active_deliveries: number;
  restaurants: number;
  menu_items: number;
}

export interface ForecastSeriesItem {
  hour: number;
  label: string;
  zones: Record<string, number>;
}

export interface ForecastSeries {
  series: ForecastSeriesItem[];
  fallback: boolean;
}

export interface Contribution {
  feature: string;
  value: number;
  shap: number;
}

export interface OrderPrediction {
  order_id: number;
  restaurant_id: number;
  eta_min: number | null;
  fallback: boolean;
  features: Record<string, number>;
  explanation: {
    base_value: number;
    contributions: Contribution[];
  } | null;
}

export interface Recommendation {
  restaurant_id: number;
  name: string;
  cuisine: string;
  address: string;
  rating: number;
  reviews_rating: number;
  review_count: number;
  score: number;
  reason: string;
}

export interface ItemRecommendation {
  menu_item_id: number;
  name: string;
  price: number;
  prep_time_min: number;
  score: number;
  reason: string;
}

export interface ItemRecommendationResponse {
  items: ItemRecommendation[];
  fallback: boolean;
}

export interface SavedAddress {
  id: number;
  label: string;
  address: string;
  lat?: number | null;
  lng?: number | null;
  created_at: string;
}

export interface AdminUser {
  id: number;
  name: string;
  email: string;
  role: Role;
}

// ---- Layer 4: payments -----------------------------------------------------

export interface PaymentStatus {
  order_id: number;
  payment_method: string;
  payment_status: string;
  payment_id?: string | null;
  amount: number;
}

export interface PaymentIntent {
  order_id: number;
  amount: number;
  amount_paise: number;
  currency: string;
  razorpay_order_id: string;
  key_id: string;
  test_mode: boolean;
  notes?: Record<string, unknown>;
}

export interface RazorpayVerifyPayload {
  order_id: number;
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}
