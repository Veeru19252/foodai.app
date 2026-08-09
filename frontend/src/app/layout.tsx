import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { CartProvider } from "@/lib/cart";
import Navbar from "@/components/Navbar";

export const metadata: Metadata = {
  title: "FoodAI — Food delivery with AI-powered ETAs",
  description:
    "Order from local restaurants and track your delivery live with ML-predicted arrival times.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <AuthProvider>
          <CartProvider>
            <Navbar />
            <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
          </CartProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
