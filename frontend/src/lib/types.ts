export type Role = "customer" | "restaurant" | "delivery" | "admin";

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface Restaurant {
  id: number;
  name: string;
  address: string;
  cuisine: string;
  rating: number;
  review_count: number;
  reviews_rating: number;
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
  created_at: string;
}

export interface OrderBrief {
  id: number;
  restaurant_id: number;
  restaurant_name: string;
  status: string;
  total: number;
  created_at: string;
  delivery_address?: string | null;
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
  items: OrderItemOut[];
}

export interface TrackingState {
  order_id: number;
  status: string;
  restaurant_name: string;
  customer_name: string;
  delivery_address?: string | null;
  route: number[][];
  route_distance_km: number;
  rider_lat: number;
  rider_lng: number;
  progress: number;
  eta_min?: number | null;
  eta_source: string;
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
