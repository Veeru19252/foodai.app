"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useCart } from "@/lib/cart";
import NotificationBell from "@/components/NotificationBell";

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
    <header className="glass sticky top-0 z-40 shadow-[0_1px_2px_rgba(0,0,0,0.4)]">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <Link href="/" className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-bold text-white shadow-sm">
            F
          </span>
          <span className="text-lg font-bold tracking-tight text-foreground">
            Food<span className="text-brand-400">AI</span>
          </span>
        </Link>

        <nav className="flex items-center gap-4 text-sm">
          {user?.role === "customer" && (
            <>
              <Link href="/restaurants" className="font-medium text-secondary transition-colors duration-150 hover:text-brand-300">
                Restaurants
              </Link>
              <Link href="/orders" className="font-medium text-secondary transition-colors duration-150 hover:text-brand-300">
                My Orders
              </Link>
              <Link
                href="/checkout"
                className="press relative rounded-full bg-brand-600 px-3 py-1.5 font-semibold text-white shadow-sm shadow-brand-600/30 transition-colors duration-150 hover:bg-brand-700"
              >
                Cart
                {count > 0 && (
                  <span
                    key={count}
                    className="badge-pop absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full bg-foreground text-[10px] font-bold text-background"
                  >
                    {count}
                  </span>
                )}
              </Link>
            </>
          )}
          {user?.role === "restaurant" && (
            <>
              <Link href="/restaurant/orders" className="font-medium text-secondary transition-colors duration-150 hover:text-brand-300">
                Orders
              </Link>
              <Link href="/restaurant/menu" className="font-medium text-secondary transition-colors duration-150 hover:text-brand-300">
                Menu
              </Link>
              <Link href="/restaurant/offers" className="font-medium text-secondary transition-colors duration-150 hover:text-brand-300">
                Offers
              </Link>
              <Link href="/restaurant/reviews" className="font-medium text-secondary transition-colors duration-150 hover:text-brand-300">
                Reviews
              </Link>
              <Link href="/restaurant/analytics" className="font-medium text-secondary transition-colors duration-150 hover:text-brand-300">
                Analytics
              </Link>
            </>
          )}
          {user?.role === "delivery" && (
            <Link href="/driver" className="font-medium text-secondary transition-colors duration-150 hover:text-brand-300">
              My Deliveries
            </Link>
          )}
          {user?.role === "admin" && (
            <Link href="/admin" className="font-medium text-secondary transition-colors duration-150 hover:text-brand-300">
              Dashboard
            </Link>
          )}

          {user ? (
            <div className="flex items-center gap-3">
              {user && <NotificationBell />}
              <span className="hidden text-muted sm:inline">
                {user.name} ({user.role})
              </span>
              <button
                onClick={handleLogout}
                className="press rounded-lg border border-line bg-card/60 px-3 py-1.5 font-medium text-secondary transition-colors duration-150 hover:bg-surface"
              >
                Log out
              </button>
            </div>
          ) : (
            <Link
              href="/login"
              className="press rounded-lg border border-line bg-card/60 px-3 py-1.5 font-medium text-secondary transition-colors duration-150 hover:bg-surface"
            >
              Log in
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}
