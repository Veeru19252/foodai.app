"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useCart } from "@/lib/cart";

const ROLE_HOME: Record<string, string> = {
  customer: "/restaurants",
  restaurant: "/restaurant/orders",
  delivery: "/driver",
  admin: "/admin",
};

export default function Navbar() {
  const { user, logout } = useAuth();
  const { count } = useCart();
  const router = useRouter();

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  return (
    <header className="sticky top-0 z-40 border-b border-gray-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <Link href="/" className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-brand-600 text-sm font-bold text-white">
            F
          </span>
          <span className="text-lg font-bold text-gray-900">
            Food<span className="text-brand-600">AI</span>
          </span>
        </Link>

        <nav className="flex items-center gap-4 text-sm">
          {user?.role === "customer" && (
            <>
              <Link href="/restaurants" className="font-medium hover:text-brand-600">
                Restaurants
              </Link>
              <Link href="/orders" className="font-medium hover:text-brand-600">
                My Orders
              </Link>
              <Link
                href="/checkout"
                className="relative rounded-full bg-brand-600 px-3 py-1.5 font-semibold text-white hover:bg-brand-700"
              >
                Cart
                {count > 0 && (
                  <span className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full bg-gray-900 text-[10px] text-white">
                    {count}
                  </span>
                )}
              </Link>
            </>
          )}
          {user?.role === "restaurant" && (
            <Link href="/restaurant/orders" className="font-medium hover:text-brand-600">
              Orders
            </Link>
          )}
          {user?.role === "delivery" && (
            <Link href="/driver" className="font-medium hover:text-brand-600">
              My Deliveries
            </Link>
          )}
          {user?.role === "admin" && (
            <Link href="/admin" className="font-medium hover:text-brand-600">
              Dashboard
            </Link>
          )}

          {user ? (
            <div className="flex items-center gap-3">
              <span className="hidden text-gray-500 sm:inline">
                {user.name} ({user.role})
              </span>
              <button
                onClick={handleLogout}
                className="rounded-lg border border-gray-300 px-3 py-1.5 font-medium hover:bg-gray-100"
              >
                Log out
              </button>
            </div>
          ) : (
            <Link
              href="/login"
              className="rounded-lg border border-gray-300 px-3 py-1.5 font-medium hover:bg-gray-100"
            >
              Log in
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}
