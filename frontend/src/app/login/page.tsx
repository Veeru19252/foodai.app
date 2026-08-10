"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

const ROLE_HOME: Record<string, string> = {
  customer: "/restaurants",
  restaurant: "/restaurant/orders",
  delivery: "/driver",
  admin: "/admin",
};

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const user = await login(email, password);
      router.push(ROLE_HOME[user.role] ?? "/restaurants");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-10 max-w-md px-4">
      <div className="mb-6 flex flex-col items-center">
        <span className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-2xl font-bold text-white shadow-lg shadow-brand-600/30">
          F
        </span>
        <h1 className="mt-4 text-center text-2xl font-bold tracking-tight">
          Welcome back
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Sign in to FoodAI to order, deliver, or manage
        </p>
      </div>
      <form
        onSubmit={handleSubmit}
        className="card-premium space-y-4 p-6"
      >
        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
        <div>
          <label htmlFor="email" className="mb-1 block text-sm font-medium">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-gray-300 bg-white/70 px-3 py-2 transition-[border-color,box-shadow] duration-150 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            placeholder="customer@foodai.com"
          />
        </div>
        <div>
          <label htmlFor="password" className="mb-1 block text-sm font-medium">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg border border-gray-300 bg-white/70 px-3 py-2 transition-[border-color,box-shadow] duration-150 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            placeholder="password123"
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          className="press w-full rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 py-2.5 font-semibold text-white shadow-sm shadow-brand-600/30 transition-[background-color,box-shadow] duration-150 hover:brightness-105 disabled:opacity-60"
        >
          {busy ? "Logging in…" : "Log in"}
        </button>
        <p className="text-center text-sm text-gray-500">
          New here?{" "}
          <Link href="/register" className="font-medium text-brand-600 transition-colors duration-150 hover:text-brand-700 hover:underline">
            Create an account
          </Link>
        </p>
        <div className="rounded-xl bg-gray-50/80 px-3 py-2 text-xs text-gray-500 ring-1 ring-gray-100">
          Demo accounts — password: <code>password123</code>
          <br />
          customer@foodai.com · spice@foodai.com · rider@foodai.com ·
          admin@foodai.com
        </div>
      </form>
    </div>
  );
}
