"use client";

// The empty-state composer on `/` — captures the user's natural-language
// goal, POSTs it via startHunt, navigates to /c/<hunt_id>. Replaces
// the old `/start` page's NLInputHero.

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { startHunt } from "@/lib/api-client";
import { cn } from "@/lib/utils";

const PLACEHOLDER =
  "Find me a standing desk under $250 near San Francisco. No IKEA. Pickup today or tomorrow.";
const STORAGE_KEY = "goti_buying_request";

export function NewHuntComposer() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Initial value reads from localStorage during state init — runs on
  // the client only (typeof window guarded) so we avoid the SSR
  // hydration mismatch + the react-hooks/set-state-in-effect lint.
  const [value, setValue] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    try {
      return window.localStorage.getItem(STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });

  const trimmed = value.trim();
  const disabled = pending || submitting || trimmed.length === 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (disabled) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, trimmed);
    } catch {
      /* ignore */
    }
    setError(null);
    setSubmitting(true);
    let huntId: string | null = null;
    try {
      const resp = await startHunt(trimmed);
      huntId = resp.hunt_id ?? null;
    } catch (err) {
      setError(
        err instanceof Error
          ? `Couldn't start the hunt: ${err.message}`
          : "Couldn't start the hunt — try again."
      );
      setSubmitting(false);
      return;
    }
    if (huntId) {
      // Clear the saved draft now that the hunt has been created.
      try {
        window.localStorage.removeItem(STORAGE_KEY);
      } catch {
        /* ignore */
      }
      startTransition(() => {
        router.push(`/c/${encodeURIComponent(huntId)}`);
      });
    } else {
      setError("Backend didn't return a hunt id — try again.");
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-4 items-stretch w-full"
    >
      <label className="flex flex-col gap-2">
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
          {submitting ? "Starting hunt…" : "Find my best options"}
          <span aria-hidden>→</span>
        </button>
      </div>

      {error ? (
        <p className="text-caption text-accent text-center" role="alert">
          {error}
        </p>
      ) : null}

      <p className="text-caption text-ink-3 text-center">
        Goti drafts. You approve every send.
      </p>
    </form>
  );
}
