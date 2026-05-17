"use client";

// "Check for reply from seller" CTA — visible on the deal-room page
// when the Job is in ``awaiting_seller_reply``. One click mints a
// single browser-agent fetch against the user's Browserbase context
// (server-side). On a hit the backend persists the reply, advances
// the job to ``active``, and spawns the negotiator (which pauses for
// approval). On a miss the user sees a "Nothing new yet" toast.
//
// Background polling was removed — Browserbase quota is precious, so
// reply fetching is user-driven only. See
// ``api/orchestration/jobs.py::run_job_lifecycle`` for the
// matching backend exit-after-send behavior.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { checkReplies } from "@/lib/api-client";
import { cn } from "@/lib/utils";

interface CheckReplyButtonProps {
  jobId: string;
  className?: string;
}

type Toast = { tone: "ok" | "info" | "error"; text: string } | null;

export function CheckReplyButton({ jobId, className }: CheckReplyButtonProps) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [toast, setToast] = useState<Toast>(null);

  async function onClick() {
    if (pending) return;
    setPending(true);
    setToast(null);
    try {
      const result = await checkReplies(jobId);
      if (result.found) {
        const n = result.reply_count ?? 1;
        setToast({
          tone: "ok",
          text:
            n === 1
              ? "New reply — Goti is drafting a counter…"
              : `${n} new replies — Goti is drafting a counter…`,
        });
        // Refresh the server-rendered page so the new approval card +
        // seller message appear once the negotiator has paused.
        router.refresh();
      } else {
        setToast({
          tone: "info",
          text: "No new reply yet — check back in a bit.",
        });
      }
    } catch (err) {
      setToast({
        tone: "error",
        text:
          err instanceof Error
            ? `Check failed: ${err.message}`
            : "Check failed — try again.",
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <button
        type="button"
        onClick={onClick}
        disabled={pending}
        className={cn(
          "inline-flex items-center justify-center gap-2 rounded-xl bg-orange px-4 py-2 text-paper text-caption font-semibold border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] hover:bg-orange/95",
          pending && "opacity-60 cursor-not-allowed"
        )}
        aria-busy={pending}
      >
        {pending ? (
          <>
            <span
              aria-hidden
              className="inline-block size-3 rounded-full border-2 border-paper/70 border-t-transparent animate-spin"
            />
            Goti is checking for a new reply… (~30s)
          </>
        ) : (
          <>Check for reply from seller</>
        )}
      </button>
      {toast ? (
        <p
          role="status"
          aria-live="polite"
          className={cn(
            "text-caption",
            toast.tone === "ok" && "text-green",
            toast.tone === "info" && "text-ink-2",
            toast.tone === "error" && "text-accent"
          )}
        >
          {toast.text}
        </p>
      ) : null}
    </div>
  );
}
