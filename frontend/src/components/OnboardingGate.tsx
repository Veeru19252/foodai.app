"use client";

/**
 * OnboardingGate — first-run location + phone verification overlay.
 *
 * Customers who haven't chosen a delivery location or verified their mobile
 * (via OTP) see this gate on browsing pages (/restaurants, /checkout, /orders)
 * before the menu is shown. Both steps are required, then the customer is
 * dropped onto a city-filtered /restaurants.
 */

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth";
import { useDeliveryLocation } from "@/lib/location";
import type { DeliveryLocation } from "@/lib/location";
import {
  CITY_CENTERS,
  DEFAULT_CITY,
  DELIVERY_CITIES,
  DELIVERY_PRESETS,
} from "@/lib/deliveryPresets";
import LocationPicker from "@/components/LocationPicker";
import type { DeliveryPoint } from "@/components/LocationPicker";
import { initialPoint, resolveAreaLabel } from "@/components/LocationPickerModal";
import PhoneOtpVerify from "@/components/PhoneOtpVerify";
import type { User } from "@/lib/types";

/** Browsing routes where the gate applies (owner/driver/admin paths excluded). */
const BROWSING_PREFIXES = ["/restaurants", "/checkout", "/orders"];

function isBrowsingPath(pathname: string): boolean {
  if (pathname === "/") return true;
  return BROWSING_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

export default function OnboardingGate() {
  const { user, updateUser } = useAuth();
  const { location, setLocation } = useDeliveryLocation();
  const pathname = usePathname();
  const router = useRouter();

  const [step, setStep] = useState<1 | 2>(1);
  const [city, setCity] = useState<string>(location?.city ?? DEFAULT_CITY);
  const [point, setPoint] = useState<DeliveryPoint>(() => initialPoint(location));

  const needsLocation = location === null;
  const needsPhone = !user?.phone_verified_at;

  // (Re)seed the picker + choose the starting step whenever the gate applies.
  useEffect(() => {
    if (!user || user.role !== "customer") return;
    setStep(needsPhone && !needsLocation ? 2 : 1);
    setCity(location?.city ?? DEFAULT_CITY);
    setPoint(initialPoint(location));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, location]);

  if (!user || user.role !== "customer" || !isBrowsingPath(pathname)) return null;
  if (!needsLocation && !needsPhone) return null;

  function handleConfirmLocation() {
    const next: DeliveryLocation = {
      city,
      areaLabel: resolveAreaLabel(point, city),
      address: point.address,
      lat: point.lat,
      lng: point.lng,
    };
    setLocation(next);
    if (needsPhone) {
      setStep(2);
    } else {
      router.push("/restaurants");
    }
  }

  function handleVerifiedUser(verified: User) {
    updateUser(verified);
    router.push("/restaurants");
  }

  function handleVerified(phone: string) {
    updateUser({ phone, phone_verified_at: new Date().toISOString() });
    router.push("/restaurants");
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="w-full max-w-xl rounded-2xl border border-zinc-800 bg-card p-6 shadow-2xl">
        <div className="mb-5 flex items-center gap-2 text-sm">
          <span
            className={`grid h-6 w-6 place-items-center rounded-full text-xs font-bold ${
              step === 1 ? "bg-brand-400 text-zinc-950" : "bg-brand-500/15 text-brand-300"
            }`}
          >
            1
          </span>
          <span className="text-xs font-medium text-zinc-400">Delivery location</span>
          <span className="h-px w-6 bg-zinc-800" />
          <span
            className={`grid h-6 w-6 place-items-center rounded-full text-xs font-bold ${
              step === 2 ? "bg-brand-400 text-zinc-950" : "bg-brand-500/15 text-brand-300"
            }`}
          >
            2
          </span>
          <span className="text-xs font-medium text-zinc-400">Verify phone</span>
        </div>

        {step === 1 ? (
          <div>
            <h2 className="text-xl font-bold tracking-tight text-zinc-100">
              Where should we deliver?
            </h2>
            <p className="mb-4 text-sm text-zinc-400">
              Pick your city so we can show restaurants and delivery times near you.
            </p>
            <LocationPicker
              point={point}
              onChange={setPoint}
              presets={DELIVERY_PRESETS}
              cities={DELIVERY_CITIES}
              city={city}
              onCityChange={setCity}
              cityCenters={CITY_CENTERS}
            />
            <button
              onClick={handleConfirmLocation}
              className="mt-4 w-full rounded-xl bg-brand-400 px-4 py-3 text-sm font-semibold text-zinc-950 transition hover:bg-brand-300"
            >
              Confirm location
            </button>
          </div>
        ) : (
          <div>
            <h2 className="text-xl font-bold tracking-tight text-zinc-100">
              One last step — verify your phone
            </h2>
            <p className="mb-4 text-sm text-zinc-400">
              We&apos;ll send a one-time password to confirm it&apos;s really you.
            </p>
            <PhoneOtpVerify
              defaultPhone={user.phone ?? null}
              onVerified={handleVerified}
              onVerifiedUser={handleVerifiedUser}
            />
          </div>
        )}
      </div>
    </div>
  );
}
