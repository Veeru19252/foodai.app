"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import type { CartGroup, CartLine } from "@/lib/types";

interface CartContextValue {
  items: CartLine[];
  addItem: (restaurantId: number, restaurantName: string, item: CartLine) => void;
  removeItem: (menuItemId: number) => void;
  setQuantity: (menuItemId: number, quantity: number) => void;
  clear: () => void;
  subtotal: number;
  count: number;
  groups: CartGroup[];
}

const CartContext = createContext<CartContextValue | undefined>(undefined);

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<CartLine[]>([]);

  const addItem = useCallback(
    (restaurantId: number, restaurantName: string, item: CartLine) => {
      setItems((prev) => {
        const existing = prev.find((i) => i.menu_item_id === item.menu_item_id);
        if (existing) {
          return prev.map((i) =>
            i.menu_item_id === item.menu_item_id
              ? { ...i, quantity: i.quantity + 1 }
              : i
          );
        }
        return [
          ...prev,
          { ...item, restaurant_id: restaurantId, restaurant_name: restaurantName, quantity: 1 },
        ];
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
  }, []);

  const subtotal = useMemo(
    () => items.reduce((sum, i) => sum + i.price * i.quantity, 0),
    [items]
  );
  const count = useMemo(
    () => items.reduce((sum, i) => sum + i.quantity, 0),
    [items]
  );

  const groups = useMemo<CartGroup[]>(() => {
    const map = new Map<number, CartGroup>();
    for (const line of items) {
      let group = map.get(line.restaurant_id);
      if (!group) {
        group = {
          restaurant_id: line.restaurant_id,
          restaurant_name: line.restaurant_name,
          items: [],
          subtotal: 0,
        };
        map.set(line.restaurant_id, group);
      }
      group.items.push(line);
      group.subtotal += line.price * line.quantity;
    }
    return Array.from(map.values());
  }, [items]);

  const value = useMemo(
    () => ({
      items,
      addItem,
      removeItem,
      setQuantity,
      clear,
      subtotal,
      count,
      groups,
    }),
    [items, addItem, removeItem, setQuantity, clear, subtotal, count, groups]
  );

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart(): CartContextValue {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart must be used within CartProvider");
  return ctx;
}
