"use client";

/**
 * PhoneOtpVerify — pre-order phone verification (Swiggy/Zomato style).
 *
 * The customer enters a 10-digit mobile, we request an OTP, they type the
 * 6-digit code, and the backend returns a short-lived otp_token. The checkout
 * flow refuses to place the order until that token matches the delivery phone.
 *
 * Demo mode: the backend has no SMS provider, so the code is returned in the
 * request response and auto-filled (dev_code) — swap the auto-fill for a real
 * SMS UI when a provider is wired up.
 */

import { useState } from "react";
import { authApi } from "@/lib/api";

interface PhoneOtpVerifyProps {
  /** Pre-filled mobile from the customer's last verified number. */
  defaultPhone?: string | null;
  onVerified: (phone: string, otpToken: string) => void;
  onError?: (message: string) => void;
}

const PHONE_RE = /^[6-9]\d{9}$/;

export default function PhoneOtpVerify({
  defaultPhone,
  onVerified,
  onError,
}: PhoneOtpVerifyProps) {
  const [phone, setPhone] = useState(defaultPhone ?? "");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [sentTo, setSentTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [cooldown, setCooldown] = useState(0);

  const canSend = PHONE_RE.test(phone.replace(/\D/g, "")) && !loading && cooldown === 0;
  const canVerify = code.length === 6 && !loading;

  async function sendOtp() {
    const normalized = phone.replace(/\D/g, "").slice(-10);
    setError("");
    setLoading(true);
    try {
      const res = await authApi.otpRequest(normalized);
      if (res.dev_code) {
        // Demo: backend returns the code because no SMS provider is wired up.
        setCode(res.dev_code);
      }
      setSentTo(normalized);
      setStep("code");
      // Resend cooldown (mirrors the backend's 60s limit).
      setCooldown(60);
      const timer = setInterval(() => {
        setCooldown((c) => {
          if (c <= 1) {
            clearInterval(timer);
            return 0;
          }
          return c - 1;
        });
      }, 1000);
    } catch (e) {
      const message = e instanceof Error ? e.message : "Could not send OTP.";
      setError(message);
      onError?.(message);
    } finally {
      setLoading(false);
    }
  }

  async function verifyCode() {
    const normalized = sentTo.replace(/\D/g, "").slice(-10);
    setError("");
    setLoading(true);
    try {
      const res = await authApi.otpVerify(normalized, code.trim());
      if (res.ok && res.otp_token) {
        onVerified(normalized, res.otp_token);
      } else {
        setError(res.message || "Verification failed. Please try again.");
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : "Verification failed.";
      setError(message);
      onError?.(message);
    } finally {
      setLoading(false);
    }
  }

  function editPhone() {
    setStep("phone");
    setCode("");
    setError("");
  }

  return (
    <div className="rounded-2xl border border-zinc-800 bg-card p-5">
      <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-zinc-100">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-500/15 text-[11px] text-brand-300">
          2
        </span>
        Verify your phone
      </div>
      <p className="mb-4 text-sm text-zinc-400">
        We&apos;ll send a one-time password to confirm it&apos;s really you.
      </p>

      {step === "phone" ? (
        <div className="flex flex-col gap-3">
          <label className="text-xs font-medium uppercase tracking-wide text-zinc-500">
            Mobile number
          </label>
          <div className="flex gap-2">
            <span className="flex items-center rounded-xl border border-zinc-800 bg-zinc-900 px-3 text-sm text-zinc-400">
              +91
            </span>
            <input
              inputMode="numeric"
              placeholder="10-digit mobile number"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="min-w-0 flex-1 rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2.5 text-sm text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-brand-400/60"
            />
          </div>
          <button
            onClick={sendOtp}
            disabled={!canSend}
            className="rounded-xl bg-brand-400 px-4 py-2.5 text-sm font-semibold text-zinc-950 transition hover:bg-brand-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading ? "Sending…" : "Send OTP"}
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-zinc-400">
              Code sent to{" "}
              <span className="font-medium text-zinc-100">+91 {sentTo}</span>
            </span>
            <button
              onClick={editPhone}
              className="text-xs font-medium text-brand-300 hover:text-brand-200"
            >
              Change
            </button>
          </div>
          <input
            inputMode="numeric"
            maxLength={6}
            placeholder="6-digit code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            className="rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2.5 text-center text-lg tracking-[0.5em] text-zinc-100 outline-none placeholder:text-base placeholder:tracking-normal placeholder:text-zinc-600 focus:border-brand-400/60"
          />
          <button
            onClick={verifyCode}
            disabled={!canVerify}
            className="rounded-xl bg-brand-400 px-4 py-2.5 text-sm font-semibold text-zinc-950 transition hover:bg-brand-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading ? "Verifying…" : "Verify & continue"}
          </button>
          <button
            onClick={sendOtp}
            disabled={cooldown > 0 || loading}
            className="text-xs font-medium text-zinc-400 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
          </button>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
    </div>
  );
}
