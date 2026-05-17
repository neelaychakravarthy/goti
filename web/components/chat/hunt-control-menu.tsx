"use client";

// Hunt lifecycle controls (Pause / Resume / Stop / Delete) for the
// sticky header of /c/<hunt_id>. Renders as a small dropdown menu so
// it doesn't crowd the header.
//
// Action semantics (backed by api/routes/hunts.py):
// - Pause: cancels in-flight tasks, status=paused. Reversible.
// - Resume: re-spawns the lifecycle. Only valid for paused / errored.
// - Stop: cancels + sets status=closed. Keeps data.
// - Delete: nukes the hunt + every Job under it. Irreversible.
//
// Destructive actions (Stop / Delete) are gated behind an inline
// confirm. On a successful Delete, the user is bounced back to / so
// they don't sit on a stale chat for a now-gone hunt.

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  deleteHunt,
  pauseHunt,
  resumeHunt,
  stopHunt,
} from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { HuntState } from "@/types";

type Action = "pause" | "resume" | "stop" | "delete";

interface Props {
  huntId: string;
  hunt: HuntState | null;
}

export function HuntControlMenu({ huntId, hunt }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<Action | null>(null);
  const [confirming, setConfirming] = useState<"stop" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Close the menu on outside click + ESC.
  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) {
        setOpen(false);
        setConfirming(null);
      }
    }
    function key(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        setConfirming(null);
      }
    }
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  const status = hunt?.status ?? "";
  const isTerminal = status === "closed" || status === "error";
  const canPause = !isTerminal && status !== "paused";
  const canResume = status === "paused" || status === "error";
  const canStop = !isTerminal;
  // Delete is always available — even closed/errored hunts can be wiped.

  async function run(action: Action) {
    setError(null);
    setPending(action);
    try {
      if (action === "pause") {
        await pauseHunt(huntId);
      } else if (action === "resume") {
        await resumeHunt(huntId);
      } else if (action === "stop") {
        await stopHunt(huntId);
      } else {
        await deleteHunt(huntId);
        // Hunt is gone — don't try to load the chat again.
        router.push("/");
        return;
      }
      setOpen(false);
      setConfirming(null);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Couldn't ${action} the hunt.`);
    } finally {
      setPending(null);
    }
  }

  return (
    <div ref={menuRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex items-center gap-1 rounded-lg border bg-paper px-2.5 py-1",
          "text-caption text-ink hover:bg-paper-3 transition"
        )}
        style={{ borderColor: "rgba(15,15,15,0.12)" }}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span>Hunt</span>
        <span aria-hidden className="text-ink-3 text-micro">
          ▾
        </span>
      </button>
      {open ? (
        <div
          role="menu"
          className={cn(
            "absolute right-0 top-full mt-1 z-30 w-[240px]",
            "rounded-xl border bg-paper shadow-[0_8px_24px_-12px_rgba(0,0,0,0.18)]",
            "py-1 flex flex-col"
          )}
          style={{ borderColor: "var(--ink-line)" }}
        >
          {confirming === null ? (
            <>
              <MenuItem
                label={pending === "pause" ? "Pausing…" : "Pause"}
                disabled={!canPause || pending !== null}
                onClick={() => run("pause")}
              />
              <MenuItem
                label={pending === "resume" ? "Resuming…" : "Resume"}
                disabled={!canResume || pending !== null}
                onClick={() => run("resume")}
              />
              <div className="mx-3 my-1 h-px bg-ink-line/10" />
              <MenuItem
                label="Stop hunt"
                disabled={!canStop || pending !== null}
                tone="warn"
                onClick={() => setConfirming("stop")}
              />
              <MenuItem
                label="Delete hunt"
                disabled={pending !== null}
                tone="danger"
                onClick={() => setConfirming("delete")}
              />
            </>
          ) : confirming === "stop" ? (
            <ConfirmBlock
              title="Stop this hunt?"
              body="Cancels in-flight discovery + negotiations. Data is preserved — you can still view the hunt's history. Cannot resume after stopping."
              confirmLabel={pending === "stop" ? "Stopping…" : "Stop hunt"}
              tone="warn"
              busy={pending === "stop"}
              onCancel={() => setConfirming(null)}
              onConfirm={() => run("stop")}
            />
          ) : (
            <ConfirmBlock
              title="Delete this hunt?"
              body="Permanently removes the hunt and every negotiation, message, and listing under it. Cannot be undone."
              confirmLabel={pending === "delete" ? "Deleting…" : "Delete"}
              tone="danger"
              busy={pending === "delete"}
              onCancel={() => setConfirming(null)}
              onConfirm={() => run("delete")}
            />
          )}
          {error ? (
            <p className="text-micro text-accent px-3 pt-1 pb-1.5">{error}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

interface MenuItemProps {
  label: string;
  disabled?: boolean;
  tone?: "default" | "warn" | "danger";
  onClick: () => void;
}

function MenuItem({ label, disabled, tone = "default", onClick }: MenuItemProps) {
  const color =
    tone === "danger"
      ? "text-accent hover:bg-accent/5"
      : tone === "warn"
        ? "text-ink hover:bg-yellow/15"
        : "text-ink hover:bg-paper-3";
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "text-left px-3 py-1.5 text-caption transition-colors",
        color,
        "disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
      )}
    >
      {label}
    </button>
  );
}

interface ConfirmBlockProps {
  title: string;
  body: string;
  confirmLabel: string;
  tone: "warn" | "danger";
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

function ConfirmBlock({
  title,
  body,
  confirmLabel,
  tone,
  busy,
  onCancel,
  onConfirm,
}: ConfirmBlockProps) {
  return (
    <div className="px-3 py-2 flex flex-col gap-2">
      <h3 className="text-caption font-display font-bold text-ink">{title}</h3>
      <p className="text-micro text-ink-2 leading-snug">{body}</p>
      <div className="flex items-center justify-end gap-1 pt-1">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className={cn(
            "rounded-md border bg-paper px-2 py-1 text-micro font-medium text-ink",
            "hover:bg-paper-3 transition disabled:opacity-50"
          )}
          style={{ borderColor: "rgba(15,15,15,0.12)" }}
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className={cn(
            "rounded-md border px-2 py-1 text-micro font-semibold text-paper",
            "shadow-[0_2px_0_0_rgba(0,0,0,1)] disabled:opacity-50",
            tone === "danger"
              ? "bg-accent hover:bg-accent/95"
              : "bg-yellow-deep hover:bg-yellow-deep/95"
          )}
          style={{ borderColor: "rgba(15,15,15,0.5)" }}
        >
          {confirmLabel}
        </button>
      </div>
    </div>
  );
}
