"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

const ROLE_HOME: Record<string, string> = {
  customer: "/restaurants",
  restaurant: "/restaurant/orders",
  delivery: "/driver",
  admin: "/admin",
};

export default function ProtectedRoute({
  role,
  children,
}: {
  role?: string;
  children: React.ReactNode;
}) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (role && user.role !== role) {
      router.replace(ROLE_HOME[user.role] ?? "/login");
    }
  }, [user, loading, role, router]);

  if (loading || !user || (role && user.role !== role)) {
    return (
      <div className="flex h-64 items-center justify-center text-gray-500">
        Loading…
      </div>
    );
  }

  return <>{children}</>;
}
