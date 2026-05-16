"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { cn } from "@/lib/utils";
import {
  GOTI_SESSION_COOKIE,
  GOTI_SESSION_MAX_AGE,
  GOTI_SESSION_VALUE,
} from "@/lib/auth";

const PLACEHOLDER =
  "Find me a standing desk under $250 near San Francisco. No IKEA. Pickup today or tomorrow.";
const STORAGE_KEY = "goti_buying_request";

export function NLInputHero() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [value, setValue] = useState(() => {
    if (typeof window === "undefined") return "";
    try {
      return window.localStorage.getItem(STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });

  const trimmed = value.trim();
  const disabled = pending || trimmed.length === 0;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (disabled) return;
    document.cookie = `${GOTI_SESSION_COOKIE}=${GOTI_SESSION_VALUE}; path=/; max-age=${GOTI_SESSION_MAX_AGE}`;
    try {
      window.localStorage.setItem(STORAGE_KEY, trimmed);
    } catch {
      // localStorage may be unavailable (incognito quotas, etc.) — fall through.
    }
    startTransition(() => {
      router.push("/search");
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-6 items-stretch w-full max-w-[720px]"
    >
      <div className="flex flex-col gap-4 text-center">
        <span className="text-micro uppercase tracking-[0.18em] text-ink-3 font-medium">
          Buyer agent for used marketplaces
        </span>
        <h1
          className="font-display font-bold text-ink leading-[1.04] tracking-[-0.02em]"
          style={{ fontSize: "clamp(36px, 6vw, 52px)" }}
        >
          What are you trying to buy used?
        </h1>
        <p className="text-subhead text-ink-2 max-w-[600px] mx-auto">
          Tell Goti what you want. It searches used marketplaces, compares
          sellers, and drafts messages for your approval.
        </p>
      </div>

      <label className="flex flex-col gap-3">
        <span className="sr-only">Describe what you want to buy</span>
        <textarea
          rows={3}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={PLACEHOLDER}
          className={cn(
            "w-full resize-none rounded-2xl bg-paper px-4 py-4",
            "font-display text-ink placeholder:text-ink-3",
            "border outline-none transition",
            "focus:ring-2 focus:ring-orange/40 focus:border-orange"
          )}
          style={{
            borderColor: "var(--ink-line)",
            fontSize: "18px",
            lineHeight: 1.5,
          }}
        />
      </label>

      <div className="flex items-center justify-center">
        <button
          type="submit"
          disabled={disabled}
          className={cn(
            "inline-flex items-center gap-2 rounded-xl bg-orange px-5 py-3 text-paper font-semibold",
            "border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95 transition",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          Find my best options
          <span aria-hidden>→</span>
        </button>
      </div>

      <p className="text-caption text-ink-3 text-center">
        Goti drafts. You approve every send.
      </p>
    </form>
  );
}
