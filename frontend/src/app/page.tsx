"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

/** Landing page: routes the user to the right app by role. */
export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    const roleHomes: Record<string, string> = {
      customer: "/restaurants",
      restaurant: "/restaurant/orders",
      delivery: "/driver",
      admin: "/admin",
    };
    router.replace(roleHomes[user.role] ?? "/login");
  }, [user, loading, router]);

  return (
    <div className="flex h-64 items-center justify-center text-gray-500">
      Redirecting…
    </div>
  );
}
