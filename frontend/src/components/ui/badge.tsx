"use client";

import { HTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/cn";

/** shadcn/ui-style Badge (dependency-free). Variant colors signal status. */
export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "success" | "warning" | "danger" | "outline";
}

const variants: Record<NonNullable<BadgeProps["variant"]>, string> = {
  default: "bg-brand-100 text-brand-700",
  secondary: "bg-gray-100 text-gray-600",
  success: "bg-emerald-100 text-emerald-700",
  warning: "bg-amber-100 text-amber-700",
  danger: "bg-red-100 text-red-700",
  outline: "border border-gray-300 text-gray-600",
};

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant = "default", ...props }, ref) => (
    <span
      ref={ref}
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        variants[variant],
        className
      )}
      {...props}
    />
  )
);
Badge.displayName = "Badge";
