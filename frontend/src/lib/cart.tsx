"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import type { CartLine } from "@/lib/types";

interface CartContextValue {
  items: CartLine[];
  restaurantId: number | null;
  addItem: (restaurantId: number, item: CartLine) => void;
  removeItem: (menuItemId: number) => void;
  setQuantity: (menuItemId: number, quantity: number) => void;
  clear: () => void;
  subtotal: number;
  count: number;
}

const CartContext = createContext<CartContextValue | undefined>(undefined);

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [restaurantId, setRestaurantId] = useState<number | null>(null);
  const [items, setItems] = useState<CartLine[]>([]);

  const addItem = useCallback(
    (restaurantId: number, item: CartLine) => {
      setRestaurantId(restaurantId);
      setItems((prev) => {
        const existing = prev.find((i) => i.menu_item_id === item.menu_item_id);
        if (existing) {
          return prev.map((i) =>
            i.menu_item_id === item.menu_item_id
              ? { ...i, quantity: i.quantity + 1 }
              : i
          );
        }
        return [...prev, { ...item, quantity: 1 }];
      });
    },
    []
  );

  const removeItem = useCallback((menuItemId: number) => {
    setItems((prev) => prev.filter((i) => i.menu_item_id !== menuItemId));
  }, []);

  const setQuantity = useCallback((menuItemId: number, quantity: number) => {
    setItems((prev) =>
      quantity <= 0
        ? prev.filter((i) => i.menu_item_id !== menuItemId)
        : prev.map((i) =>
            i.menu_item_id === menuItemId ? { ...i, quantity } : i
          )
    );
  }, []);

  const clear = useCallback(() => {
    setItems([]);
    setRestaurantId(null);
  }, []);

  const subtotal = useMemo(
    () => items.reduce((sum, i) => sum + i.price * i.quantity, 0),
    [items]
  );
  const count = useMemo(
    () => items.reduce((sum, i) => sum + i.quantity, 0),
    [items]
  );

  const value = useMemo(
    () => ({
      items,
      restaurantId,
      addItem,
      removeItem,
      setQuantity,
      clear,
      subtotal,
      count,
    }),
    [items, restaurantId, addItem, removeItem, setQuantity, clear, subtotal, count]
  );

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart(): CartContextValue {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart must be used within CartProvider");
  return ctx;
}
