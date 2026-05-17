"use client";

// Phase K — Memory hub. Three sections: Closed hunts / Cases / Skills.
// Replaces the old fixture-driven Playbook view. Uses the
// EverOS-backed routes (``/api/memory/cases``, ``/api/memory/skills``,
// ``/api/hunts``) so the section content reflects real memory data.
//
// Design preservation: reuses the existing ``CaseFile`` + ``LearningNoteCard``
// component aesthetics + the existing paper/ink/orange/yellow tokens.

import Link from "next/link";
import { useEffect, useState } from "react";

import { LearningNoteCard } from "@/components/playbook/learning-note";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorMessage } from "@/components/ui/error-message";
import {
  getHunts,
  getMemoryCases,
  getMemorySkills,
} from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type {
  HuntState,
  LearningNote,
  MemoryCase,
  MemorySkill,
} from "@/types";

interface MemoryData {
  closedHunts: HuntState[];
  cases: MemoryCase[];
  skills: MemorySkill[];
}

export default function PlaybookPage() {
  const [data, setData] = useState<MemoryData | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [hunts, cases, skills] = await Promise.all([
          getHunts().catch(() => [] as HuntState[]),
          getMemoryCases().catch(() => [] as MemoryCase[]),
          getMemorySkills().catch(() => [] as MemorySkill[]),
        ]);
        if (cancelled) return;
        const closedHunts = hunts.filter((h) => h.status === "closed");
        setData({ closedHunts, cases, skills });
        setError(null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "failed to load memory");
        }
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const isEmpty =
    loaded &&
    !error &&
    data !== null &&
    data.closedHunts.length === 0 &&
    data.cases.length === 0 &&
    data.skills.length === 0;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="mx-auto max-w-[1200px] flex flex-col gap-6 px-6 py-10">
        <div className="grid grid-cols-12 gap-4 items-start">
          <header className="col-span-12 flex flex-col gap-2">
            <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-panel-dark text-paper px-2.5 py-1 text-caption font-medium">
              Goti memory
            </span>
            <h1
              className="font-display font-bold text-ink leading-tight tracking-tight"
              style={{ fontSize: "32px" }}
            >
              Every close becomes a case file.
            </h1>
            <p className="text-body text-ink-2 max-w-[640px]">
              Goti saves what worked, so the next negotiation starts smarter.
            </p>
          </header>
        </div>

        {!loaded ? (
          <SkeletonGrid />
        ) : error ? (
          <ErrorMessage
            title="Couldn't load Memory"
            body="Goti can't reach the backend right now. Try again in a moment."
          />
        ) : isEmpty ? (
          <EmptyState
            title="No memory yet"
            body="Close a negotiation and Goti will analyze it — what worked, what didn't, and tactical lessons — and store it here."
          />
        ) : (
          <div className="flex flex-col gap-8">
            <ClosedHuntsSection hunts={data!.closedHunts} />
            <CasesSection cases={data!.cases} />
            <SkillsSection skills={data!.skills} />
          </div>
        )}
      </div>
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="rounded-2xl border bg-paper-2 h-44 animate-pulse"
          style={{ borderColor: "rgba(15,15,15,0.08)" }}
        />
      ))}
    </div>
  );
}

function ClosedHuntsSection({ hunts }: { hunts: HuntState[] }) {
  return (
    <section className="flex flex-col gap-3">
      <SectionHeader title="Closed hunts" count={hunts.length} />
      {hunts.length === 0 ? (
        <p className="text-caption text-ink-3">
          No closed hunts yet. Close one and it shows up here.
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {hunts.map((h) => (
            <ClosedHuntCard key={h.id} hunt={h} />
          ))}
        </div>
      )}
    </section>
  );
}

function ClosedHuntCard({ hunt }: { hunt: HuntState }) {
  const title = hunt.goal_text.length > 60
    ? `${hunt.goal_text.slice(0, 57)}…`
    : hunt.goal_text;
  return (
    <Link
      href={`/chat?hunt_id=${encodeURIComponent(hunt.id)}`}
      className={cn(
        "block rounded-2xl border bg-paper p-4 transition-colors",
        "hover:bg-paper-3"
      )}
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-caption text-ink-3 font-mono">Closed hunt</span>
        <span className="text-micro text-ink-3">
          {hunt.updated_at ? formatDate(hunt.updated_at) : ""}
        </span>
      </div>
      <h3 className="font-display font-bold text-ink mt-1 leading-tight">
        {title}
      </h3>
      <p className="text-micro text-ink-3 mt-1">
        {hunt.candidates_count ?? 0} candidate(s) ·{" "}
        {hunt.open_negotiations_count ?? 0} open
      </p>
    </Link>
  );
}

function CasesSection({ cases }: { cases: MemoryCase[] }) {
  return (
    <section className="flex flex-col gap-3">
      <SectionHeader title="Cases" count={cases.length} />
      {cases.length === 0 ? (
        <p className="text-caption text-ink-3">
          No Cases yet. After closing a deal, Goti analyzes the negotiation
          and writes a structured Case here.
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {cases.map((c, i) => (
            <CaseCardLink key={c.id} memCase={c} primary={i === 0} />
          ))}
        </div>
      )}
    </section>
  );
}

function CaseCardLink({
  memCase,
  primary,
}: {
  memCase: MemoryCase;
  primary: boolean;
}) {
  const tone =
    memCase.outcome === "closed_deal"
      ? "border-green/30 bg-paper"
      : "border-ink-line/15 bg-paper";

  return (
    <Link
      href={`/playbook/cases/${encodeURIComponent(memCase.id)}`}
      className={cn(
        "relative rounded-2xl border p-5 pt-7 flex flex-col gap-3 transition-colors",
        "hover:bg-paper-3",
        tone,
        primary ? "border-2" : ""
      )}
      style={{
        borderColor: primary
          ? "rgba(15,15,15,0.22)"
          : "rgba(15,15,15,0.12)",
      }}
    >
      <span
        className="absolute -top-2 left-4 inline-flex items-center rounded-md border bg-orange text-paper px-2 py-0.5 text-micro font-mono font-semibold"
        style={{ borderColor: "var(--ink-line)" }}
      >
        {shortId(memCase.id)}
      </span>

      <div className="flex flex-col gap-1">
        <h3
          className={cn(
            "font-display font-bold text-ink leading-tight",
            primary ? "text-headline" : "text-body"
          )}
        >
          {memCase.title || "Negotiation"}
        </h3>
        {memCase.region ? (
          <span className="text-caption text-ink-3">{memCase.region}</span>
        ) : null}
      </div>

      <div className="grid grid-cols-3 gap-2">
        <CaseStat
          label="Outcome"
          value={outcomeLabel(memCase.outcome)}
          tone={outcomeTone(memCase.outcome)}
        />
        <CaseStat
          label="Closed at"
          value={
            typeof memCase.final_price === "number"
              ? `$${Math.round(memCase.final_price)}`
              : "—"
          }
          tone="green"
        />
        <CaseStat
          label="Category"
          value={memCase.category || "—"}
          tone="neutral"
        />
      </div>

      <div
        className="rounded-xl border bg-paper-2 p-3"
        style={{ borderColor: "rgba(15,15,15,0.12)" }}
      >
        <div className="text-micro uppercase tracking-wider text-ink-3 font-semibold">
          What worked
        </div>
        <p className="text-caption text-ink mt-1 font-medium">
          {memCase.summary || "Open this Case to see the structured analysis."}
        </p>
      </div>
    </Link>
  );
}

function SkillsSection({ skills }: { skills: MemorySkill[] }) {
  const notes: LearningNote[] = skills.map((s) => ({
    kind: skillKindForUI(s.category),
    title: s.name,
    body: s.description,
  }));
  return (
    <section className="flex flex-col gap-3">
      <SectionHeader title="Skills" count={skills.length} />
      {skills.length === 0 ? (
        <p className="text-caption text-ink-3">
          No Skills yet. EverOS extracts these automatically once you have
          enough closed Cases on similar items.
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {notes.map((n, idx) => (
            <LearningNoteCard key={skills[idx].id} note={n} />
          ))}
        </div>
      )}
    </section>
  );
}

function SectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-baseline gap-2">
      <h2 className="font-display font-bold text-ink text-headline">
        {title}
      </h2>
      <span className="text-micro text-ink-3 font-mono">({count})</span>
    </div>
  );
}

function CaseStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "neutral" | "green" | "yellow";
}) {
  const cls =
    tone === "yellow"
      ? "bg-yellow text-ink border-yellow-deep"
      : tone === "green"
        ? "bg-green-soft text-green border-green/30"
        : "bg-paper-2 text-ink border-ink-line/15";
  return (
    <div className={`rounded-lg border px-2.5 py-2 ${cls}`}>
      <div className="text-micro uppercase tracking-wider font-medium opacity-80">
        {label}
      </div>
      <div className="text-caption font-display font-bold leading-tight truncate">
        {value}
      </div>
    </div>
  );
}

function outcomeLabel(outcome?: string | null): string {
  if (outcome === "closed_deal") return "Closed";
  if (outcome === "no_response") return "No reply";
  if (outcome === "abandoned") return "Declined";
  return "—";
}

function outcomeTone(outcome?: string | null): "green" | "yellow" | "neutral" {
  if (outcome === "closed_deal") return "green";
  if (outcome === "no_response" || outcome === "abandoned") return "yellow";
  return "neutral";
}

function skillKindForUI(category?: string | null): LearningNote["kind"] {
  if (!category) return "message_tactic";
  const c = category.toLowerCase();
  if (c.includes("price")) return "local_price_memory";
  if (c.includes("trust") || c.includes("seller")) return "trust_signal";
  return "message_tactic";
}

function shortId(id: string): string {
  return id.length > 10 ? id.slice(0, 8) : id;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleDateString();
  } catch {
    return "";
  }
}
