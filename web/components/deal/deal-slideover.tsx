"use client";

// Slideover panel that renders the per-listing seller conversation
// (DealRoomLayout) without leaving the parent hunt chat.
//
// Opens from the right edge when a listing in the hunt chat is clicked
// (either via "Start negotiation" on a discovered listing card, or via
// clicking an already-accepted listing card). Closes via the close
// button, the backdrop, or ESC.

import { useEffect, useState } from "react";

import { DealRoomLayout } from "@/components/deal/deal-room-layout";
import { getDealRoom } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { DealRoom } from "@/types";

const POLL_MS = 3_000;

interface Props {
  jobId: string | null;
  onClose: () => void;
  siblingCount?: number;
}

export function DealSlideover({ jobId, onClose, siblingCount = 0 }: Props) {
  const [room, setRoom] = useState<DealRoom | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reset state when the selected job changes (or closes). Uses the
  // "previous-prop tracking" pattern (not a useEffect) so we don't
  // violate react-hooks/set-state-in-effect.
  const [lastJobId, setLastJobId] = useState<string | null>(jobId);
  if (jobId !== lastJobId) {
    setLastJobId(jobId);
    setRoom(null);
    setError(null);
  }

  // Poll the deal room while the slideover is open.
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    async function load() {
      try {
        const r = await getDealRoom(jobId!);
        if (!cancelled) {
          setRoom(r);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "couldn't load deal");
        }
      }
    }
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [jobId]);

  // ESC to close.
  useEffect(() => {
    if (!jobId) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [jobId, onClose]);

  // Lock body scroll while open.
  useEffect(() => {
    if (!jobId) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [jobId]);

  if (!jobId) return null;

  return (
    <div className="fixed inset-0 z-40">
      {/* backdrop */}
      <button
        type="button"
        aria-label="Close negotiation panel"
        onClick={onClose}
        className="absolute inset-0 bg-ink/30 backdrop-blur-sm"
      />
      {/* panel */}
      <aside
        role="dialog"
        aria-label="Seller negotiation"
        className={cn(
          "absolute top-0 right-0 h-screen w-full max-w-[820px]",
          "bg-paper shadow-[-12px_0_24px_-12px_rgba(0,0,0,0.18)] border-l",
          "flex flex-col"
        )}
        style={{ borderColor: "var(--ink-line)" }}
      >
        <header
          className="shrink-0 flex items-center justify-between gap-3 px-5 py-3 border-b"
          style={{ borderColor: "rgba(15,15,15,0.08)" }}
        >
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
              Seller conversation
            </span>
            <span className="text-caption text-ink truncate">
              {room?.listing?.title ?? "Loading…"}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className={cn(
              "shrink-0 inline-flex items-center justify-center rounded-lg",
              "size-8 border bg-paper hover:bg-paper-3 transition"
            )}
            style={{ borderColor: "rgba(15,15,15,0.12)" }}
            aria-label="Close"
          >
            <span aria-hidden className="text-ink">
              ✕
            </span>
          </button>
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4">
          {error ? (
            <div className="rounded-2xl border bg-paper-2 px-4 py-3 text-caption text-accent">
              {error}
            </div>
          ) : room ? (
            <DealRoomLayout room={room} siblingCount={siblingCount} />
          ) : (
            <div className="rounded-2xl border bg-paper-2 px-4 py-3 text-caption text-ink-3">
              Loading negotiation…
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
