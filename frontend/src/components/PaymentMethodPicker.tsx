"use client";

import { cn } from "@/lib/cn";
import { Card } from "@/components/ui/card";

export type PaymentMethod = "COD" | "RAZORPAY";

interface PaymentMethodPickerProps {
  value: PaymentMethod;
  onChange: (method: PaymentMethod) => void;
  total: number;
}

/**
 * Checkout payment selection — shadcn-style radio cards.
 *
 * COD  -> fully working (cash collected at delivery).
 * Razorpay -> test-mode interface: after the order is placed the checkout
 * runs the intent -> simulated signature -> verify flow (see CheckoutPage).
 */
export function PaymentMethodPicker({ value, onChange, total }: PaymentMethodPickerProps) {
  const options: {
    id: PaymentMethod;
    title: string;
    description: string;
    badge: string;
  }[] = [
    {
      id: "COD",
      title: "Cash on Delivery",
      description: "Pay in cash when your order arrives",
      badge: "Recommended",
    },
    {
      id: "RAZORPAY",
      title: "Razorpay (test)",
      description: "Test-mode card / UPI checkout — no real money",
      badge: "Test mode",
    },
  ];

  return (
    <div className="grid gap-3">
      {options.map((option) => {
        const active = value === option.id;
        return (
          <button
            key={option.id}
            type="button"
            onClick={() => onChange(option.id)}
            aria-pressed={active}
            className="text-left transition-colors"
          >
            <Card
              className={cn(
                "cursor-pointer p-4",
                active ? "border-brand-500 bg-brand-500/10 ring-2 ring-brand-500 ring-offset-1 ring-offset-background" : "hover:border-line"
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium text-foreground">{option.title}</p>
                  <p className="text-sm text-muted">{option.description}</p>
                </div>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-xs font-medium",
                    option.id === "COD"
                      ? "bg-emerald-500/15 text-emerald-300"
                      : "bg-amber-500/15 text-amber-300"
                  )}
                >
                  {option.badge}
                </span>
              </div>
              {option.id === "RAZORPAY" && (
                <p className="mt-2 text-xs text-faint">
                  Paying ₹{total.toFixed(2)} via simulated Razorpay signature
                </p>
              )}
            </Card>
          </button>
        );
      })}
    </div>
  );
}
