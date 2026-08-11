"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { useCart } from "@/lib/cart";
import NotificationBell from "@/components/NotificationBell";
import LocationPickerModal from "@/components/LocationPickerModal";
import PhoneOtpVerify from "@/components/PhoneOtpVerify";
import { useDeliveryLocation } from "@/lib/location";
import type { User } from "@/lib/types";

const ROLE_HOME: Record<string, string> = {
  customer: "/restaurants",
  restaurant: "/restaurant/orders",
  delivery: "/driver",
  admin: "/admin",
};

export default function Navbar() {
  const { user, logout, updateUser } = useAuth();
  const { count } = useCart();
  const { location, setLocation } = useDeliveryLocation();
  const router = useRouter();
  const [locationOpen, setLocationOpen] = useState(false);
  const [phoneOpen, setPhoneOpen] = useState(false);

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  const handlePhoneVerified = (userFromResponse: User | undefined, phone: string) => {
    if (userFromResponse) updateUser(userFromResponse);
    else updateUser({ phone, phone_verified_at: new Date().toISOString() });
    setPhoneOpen(false);
  };

  return (
    <>
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
              <button
                onClick={() => setLocationOpen(true)}
                className="flex items-center gap-1.5 rounded-full border border-line bg-card/60 px-3 py-1.5 font-medium text-secondary transition-colors duration-150 hover:bg-surface hover:text-brand-300"
                title="Change delivery location"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-3.5 w-3.5 text-brand-400"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 21s-6-5.1-6-10a6 6 0 1 1 12 0c0 4.9-6 10-6 10z"
                  />
                  <circle cx="12" cy="11" r="2" />
                </svg>
                {location
                  ? `${location.areaLabel}, ${location.city}`
                  : "Set location"}
              </button>
              {!user.phone_verified_at && (
                <button
                  onClick={() => setPhoneOpen(true)}
                  className="rounded-full border border-brand-500/30 bg-brand-500/10 px-3 py-1.5 font-medium text-brand-300 transition-colors duration-150 hover:bg-brand-500/20"
                  title="Verify your phone number"
                >
                  Verify phone
                </button>
              )}
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

    {/* Overlays render outside the glass header: .glass uses backdrop-filter,
        which becomes the containing block for position:fixed descendants and
        would clip these full-screen modals to the 56px header strip. */}
    <LocationPickerModal
      open={locationOpen}
      initial={location}
      onConfirm={(loc) => {
        setLocation(loc);
        setLocationOpen(false);
      }}
      onClose={() => setLocationOpen(false)}
    />

    {phoneOpen && (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
        onClick={() => setPhoneOpen(false)}
        role="dialog"
        aria-modal="true"
        aria-label="Verify your phone"
      >
        <div
          className="w-full max-w-md rounded-2xl border border-zinc-800 bg-card p-5 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-bold text-zinc-100">Verify your phone</h2>
            <button
              onClick={() => setPhoneOpen(false)}
              className="grid h-8 w-8 place-items-center rounded-full bg-surface hover:bg-elevated"
              aria-label="Close"
            >
              ×
            </button>
          </div>
          <PhoneOtpVerify
            defaultPhone={user?.phone ?? null}
            onVerified={(phone) => handlePhoneVerified(undefined, phone)}
            onVerifiedUser={(u) => handlePhoneVerified(u, "")}
          />
        </div>
      </div>
    )}
  </>
);
}
