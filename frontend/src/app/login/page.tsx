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
    <div className="mx-auto mt-12 max-w-md">
      <h1 className="mb-6 text-center text-2xl font-bold">Welcome back</h1>
      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm"
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
            className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
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
            className="w-full rounded-lg border border-gray-300 px-3 py-2 focus:border-brand-500 focus:outline-none"
            placeholder="password123"
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-brand-600 py-2.5 font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {busy ? "Logging in…" : "Log in"}
        </button>
        <p className="text-center text-sm text-gray-500">
          New here?{" "}
          <Link href="/register" className="font-medium text-brand-600 hover:underline">
            Create an account
          </Link>
        </p>
        <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500">
          Demo accounts — password: <code>password123</code>
          <br />
          customer@foodai.com · spice@foodai.com · rider@foodai.com ·
          admin@foodai.com
        </div>
      </form>
    </div>
  );
}
