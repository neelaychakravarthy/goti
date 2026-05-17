// Per-hunt chat — the primary control plane for an active hunt.
// URL: /c/<hunt_id>
//
// Layout (full-height, no separate page chrome):
//
//   ┌───────────────────────────────────────────────────────────┐
//   │ Sticky header: hunt goal + status                         │
//   │ TaskStatusStrip (running async work for this hunt)        │
//   ├───────────────────────────────────────────────────────────┤
//   │ Scrolling chat panel:                                     │
//   │   - Agent reasoning bubbles                               │
//   │   - Inline listing-discovered cards                       │
//   │   - Inline approval cards                                 │
//   │   - Task start/finish status pills                        │
//   │   - Analyzer progress/complete events                     │
//   │   - "Lessons captured → View in Memory" on close          │
//   ├───────────────────────────────────────────────────────────┤
//   │ Composer (bottom):                                        │
//   │   - When hunt is waiting on a clarifying question →       │
//   │     captures the answer, POSTs to the approval bridge.    │
//   │   - Otherwise → disabled "Goti is working…" hint.         │
//   └───────────────────────────────────────────────────────────┘
//
// Clicking an inline listing card opens a slideover with the
// per-listing seller chat (DealRoomLayout inside the slideover).
//
// All inline state — selected listing for the slideover, pending
// clarify question — lives in this component. The chat panel and the
// composer are siblings; the composer reads notifications to know if a
// clarifying question is open.

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { ActiveNegotiationsStrip } from "@/components/chat/active-negotiations-strip";
import { CandidatesPanel } from "@/components/chat/candidates-panel";
import { HuntChatComposer } from "@/components/chat/hunt-chat-composer";
import { HuntControlMenu } from "@/components/chat/hunt-control-menu";
import { HuntConversation } from "@/components/chat/hunt-conversation";
import { TaskStatusStrip } from "@/components/chat/task-status-strip";
import { DealSlideover } from "@/components/deal/deal-slideover";
import { ErrorMessage } from "@/components/ui/error-message";
import { getHunt } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { HuntState } from "@/types";

function chatStatusLine(hunt: HuntState | null): string | undefined {
  if (!hunt) return undefined;
  switch (hunt.status) {
    case "awaiting_clarification":
      return "Waiting for your input below.";
    case "discovering":
      return "Goti is searching marketplaces…";
    case "awaiting_picks":
      return `Goti surfaced ${hunt.candidates_count ?? 0} candidate${(hunt.candidates_count ?? 0) === 1 ? "" : "s"}.`;
    case "negotiating": {
      const open = hunt.open_negotiations_count ?? 0;
      return open > 0
        ? `Negotiating ${open} listing${open === 1 ? "" : "s"}.`
        : "Negotiating.";
    }
    case "paused":
      return "Hunt is paused.";
    case "closed":
      return "Hunt closed.";
    case "error":
      return "Hunt errored.";
    default:
      return undefined;
  }
}

export default function HuntChatPage({
  params,
}: {
  params: Promise<{ hunt_id: string }>;
}) {
  const searchParams = useSearchParams();
  const dealQueryParam = searchParams?.get("deal") ?? null;
  const [huntId, setHuntId] = useState<string | null>(null);
  const [hunt, setHunt] = useState<HuntState | null>(null);
  const [huntError, setHuntError] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  // Resolve the dynamic param (Promise in Next 15+).
  useEffect(() => {
    let cancelled = false;
    params.then((p) => {
      if (!cancelled) setHuntId(p.hunt_id);
    });
    return () => {
      cancelled = true;
    };
  }, [params]);

  // ``?deal=<job_id>`` deep-link from notifications opens the slideover
  // for that specific job. The "previous-prop tracking" pattern keeps
  // the slideover URL-driven AND click-driven without violating
  // react-hooks/set-state-in-effect.
  const [lastDealParam, setLastDealParam] = useState<string | null>(null);
  if (dealQueryParam !== lastDealParam) {
    setLastDealParam(dealQueryParam);
    if (dealQueryParam) setSelectedJobId(dealQueryParam);
  }

  // Poll the hunt state every 5s for status + counts. The chat panel
  // gets its updates via SSE, but the header pill (status, candidate
  // counts) lives off the /api/hunts/{id} body.
  useEffect(() => {
    if (!huntId) return;
    let cancelled = false;
    async function load() {
      try {
        const h = await getHunt(huntId!);
        if (!cancelled) {
          setHunt(h);
          setHuntError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setHuntError(e instanceof Error ? e.message : "couldn't load hunt");
        }
      }
    }
    load();
    const id = setInterval(load, 5_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [huntId]);

  if (!huntId) {
    return (
      <div className="flex-1 flex items-center justify-center text-caption text-ink-3">
        Loading hunt…
      </div>
    );
  }

  if (huntError) {
    return (
      <div className="flex-1 flex items-center justify-center px-6">
        <ErrorMessage
          title="Couldn't load this hunt"
          body="Goti can't reach the backend right now. Try again in a moment."
        />
      </div>
    );
  }

  const status = chatStatusLine(hunt);

  return (
    <>
      {/* Sticky header */}
      <header
        className={cn(
          "shrink-0 border-b bg-paper/95 backdrop-blur px-6 py-3",
          "flex flex-col gap-1"
        )}
        style={{ borderColor: "rgba(15,15,15,0.08)" }}
      >
        <div className="flex items-center justify-between gap-3">
          <h1 className="font-display font-bold text-ink leading-tight text-headline truncate">
            {hunt?.goal_text ?? "Hunt"}
          </h1>
          <div className="flex items-center gap-2 shrink-0">
            <HuntControlMenu huntId={huntId} hunt={hunt} />
            <Link
              href="/"
              className="text-caption text-ink-3 hover:text-ink underline-offset-2 hover:underline"
            >
              + New hunt
            </Link>
          </div>
        </div>
        {status ? (
          <p className="text-caption text-ink-2">{status}</p>
        ) : null}
      </header>

      {/* Main split: chat column (left) + candidates rail (right). */}
      <div className="flex-1 min-h-0 flex">
        {/* Chat column — task strip, conversation, composer. */}
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="shrink-0 px-6 pt-3 flex flex-col gap-2">
            <TaskStatusStrip huntId={huntId} />
            <ActiveNegotiationsStrip
              huntId={huntId}
              onOpen={(jobId) => setSelectedJobId(jobId)}
            />
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4">
            <div className="mx-auto max-w-[820px]">
              <HuntConversation
                huntId={huntId}
                onNegotiationStarted={(jobId) => setSelectedJobId(jobId)}
              />
            </div>
          </div>

          <div
            className="shrink-0 border-t bg-paper px-6 py-4"
            style={{ borderColor: "rgba(15,15,15,0.08)" }}
          >
            <div className="mx-auto max-w-[820px]">
              <HuntChatComposer huntId={huntId} hunt={hunt} />
            </div>
          </div>
        </div>

        {/* Candidates rail — discovered + accepted listings live here
            instead of inline in the conversation, because discovery
            runs in parallel with everything else and shouldn't be
            forced into a sequential feed. */}
        <CandidatesPanel
          huntId={huntId}
          onStarted={(jobId) => setSelectedJobId(jobId)}
          className="hidden xl:flex"
        />
      </div>

      {/* Per-listing seller chat slideover */}
      <DealSlideover
        jobId={selectedJobId}
        onClose={() => setSelectedJobId(null)}
      />
    </>
  );
}
