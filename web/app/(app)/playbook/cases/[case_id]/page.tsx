"use client";

// Phase K — per-Case detail view. Renders the structured analyzer
// payload (what worked / what didn't / key moments / tactical lessons)
// plus a debounce-saved custom notes textarea and a delete button.

import { use, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { ErrorMessage } from "@/components/ui/error-message";
import {
  deleteCase,
  getCaseDetail,
  updateCaseNotes,
} from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { CaseDetail } from "@/types";

interface PageProps {
  params: Promise<{ case_id: string }>;
}

export default function CaseDetailPage({ params }: PageProps) {
  const { case_id: caseId } = use(params);
  const router = useRouter();

  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notesText, setNotesText] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [showConfirm, setShowConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef<string>("");

  useEffect(() => {
    let cancelled = false;
    getCaseDetail(caseId)
      .then((d) => {
        if (!cancelled) {
          setDetail(d);
          setNotesText(d.notes_text || "");
          lastSavedRef.current = d.notes_text || "";
          setLoaded(true);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error
              ? e.message
              : "couldn't load this Case"
          );
          setLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [caseId]);

  // Debounced notes autosave (1.2s after last keystroke).
  const debouncedSave = useCallback(
    (text: string) => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      setSaveState("saving");
      saveTimerRef.current = setTimeout(async () => {
        if (text === lastSavedRef.current) {
          setSaveState("saved");
          return;
        }
        try {
          await updateCaseNotes(caseId, text);
          lastSavedRef.current = text;
          setSaveState("saved");
        } catch {
          setSaveState("error");
        }
      }, 1200);
    },
    [caseId]
  );

  const onNotesChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const v = e.target.value;
    setNotesText(v);
    debouncedSave(v);
  };

  const onConfirmDelete = async () => {
    if (deleting) return;
    setDeleting(true);
    try {
      await deleteCase(caseId);
      router.push("/playbook");
    } catch (e) {
      setError(
        e instanceof Error
          ? `Delete failed: ${e.message}`
          : "Delete failed"
      );
      setDeleting(false);
      setShowConfirm(false);
    }
  };

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="mx-auto max-w-[900px] flex flex-col gap-6 px-6 py-8">
        <div>
          <Link
            href="/playbook"
            className="text-caption text-ink-2 hover:text-ink underline-offset-2 hover:underline"
          >
            ← Back to Memory
          </Link>
        </div>

        {!loaded ? (
          <div
            className="rounded-2xl border bg-paper-2 px-4 py-3 text-caption text-ink-3"
            style={{ borderColor: "rgba(15,15,15,0.08)" }}
          >
            Loading Case…
          </div>
        ) : error ? (
          <ErrorMessage
            title="Couldn't load this Case"
            body={error}
          />
        ) : detail ? (
          <>
            <CaseSummary detail={detail} />
            <AnalyzerSections detail={detail} />
            <NotesEditor
              value={notesText}
              onChange={onNotesChange}
              saveState={saveState}
            />
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setShowConfirm(true)}
                disabled={deleting}
                className={cn(
                  "rounded-2xl border bg-paper px-4 py-2 text-caption font-medium",
                  "text-orange border-orange/30 hover:bg-orange/10",
                  "shadow-[0_2px_0_0_rgba(0,0,0,1)]",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                Delete Case
              </button>
            </div>
            <DeleteConfirmDialog
              open={showConfirm}
              busy={deleting}
              onCancel={() => !deleting && setShowConfirm(false)}
              onConfirm={onConfirmDelete}
            />
          </>
        ) : null}
      </div>
    </div>
  );
}

function CaseSummary({ detail }: { detail: CaseDetail }) {
  const finalPrice = detail.case.final_price;
  return (
    <article
      className="rounded-2xl border bg-paper p-5 flex flex-col gap-3"
      style={{ borderColor: "rgba(15,15,15,0.22)" }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h1 className="font-display font-bold text-ink text-headline">
          {detail.case.title || "Negotiation"}
        </h1>
        <span className="text-micro text-ink-3 font-mono">
          {detail.case.id.slice(0, 12)}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        <Badge label={outcomeLabel(detail.case.outcome)} tone={outcomeTone(detail.case.outcome)} />
        {typeof finalPrice === "number" ? (
          <Badge label={`Closed at $${Math.round(finalPrice)}`} tone="green" />
        ) : null}
        {detail.case.category ? (
          <Badge label={detail.case.category} tone="neutral" />
        ) : null}
        {detail.case.region ? (
          <Badge label={detail.case.region} tone="neutral" />
        ) : null}
      </div>
    </article>
  );
}

function AnalyzerSections({ detail }: { detail: CaseDetail }) {
  const a = detail.analyzer;
  if (!a) {
    return (
      <article
        className="rounded-2xl border bg-paper p-5 flex flex-col gap-2"
        style={{ borderColor: "rgba(15,15,15,0.12)" }}
      >
        <h2 className="font-display font-bold text-ink">Analysis</h2>
        <p className="text-caption text-ink-3">
          This Case predates the analyzer pipeline. Only the summary is
          available — the per-turn structured analysis isn&rsquo;t.
        </p>
      </article>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <BulletList title="What worked" items={a.what_worked || []} tone="green" />
      <BulletList title="What didn't" items={a.what_didnt || []} tone="orange" />
      <KeyMomentsBlock moments={a.key_moments || []} />
      <BulletList
        title="Tactical lessons"
        items={a.tactical_lessons || []}
        tone="yellow"
      />
    </div>
  );
}

function BulletList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "green" | "orange" | "yellow";
}) {
  if (items.length === 0) return null;
  const accent =
    tone === "green"
      ? "border-green/40 bg-green-soft"
      : tone === "orange"
        ? "border-orange/40 bg-paper"
        : "bg-yellow/30 border-yellow-deep/50";
  return (
    <article
      className={cn("rounded-2xl border p-5 flex flex-col gap-2", accent)}
    >
      <h2 className="font-display font-bold text-ink">{title}</h2>
      <ul className="flex flex-col gap-1.5">
        {items.map((it, i) => (
          <li key={i} className="text-caption text-ink leading-relaxed">
            • {it}
          </li>
        ))}
      </ul>
    </article>
  );
}

function KeyMomentsBlock({
  moments,
}: {
  moments: Array<{ turn_idx: number; observation: string }>;
}) {
  if (moments.length === 0) return null;
  return (
    <article
      className="rounded-2xl border bg-paper p-5 flex flex-col gap-2"
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
    >
      <h2 className="font-display font-bold text-ink">Key moments</h2>
      <ul className="flex flex-col gap-2">
        {moments.map((m, i) => (
          <li
            key={i}
            className="flex gap-3 text-caption text-ink leading-relaxed"
          >
            <span className="font-mono text-micro text-ink-3 shrink-0 mt-0.5">
              t{m.turn_idx}
            </span>
            <span>{m.observation}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}

function NotesEditor({
  value,
  onChange,
  saveState,
}: {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  saveState: "idle" | "saving" | "saved" | "error";
}) {
  return (
    <article
      className="rounded-2xl border bg-paper p-5 flex flex-col gap-2"
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="font-display font-bold text-ink">Your notes</h2>
        <span
          className={cn(
            "text-micro font-medium",
            saveState === "saved" && "text-green",
            saveState === "saving" && "text-ink-3",
            saveState === "error" && "text-orange",
            saveState === "idle" && "text-ink-3"
          )}
        >
          {saveState === "saving" && "Saving…"}
          {saveState === "saved" && "Saved"}
          {saveState === "error" && "Save failed — try again"}
        </span>
      </div>
      <textarea
        value={value}
        onChange={onChange}
        placeholder="Add your own notes about this negotiation. Autosaves as you type."
        className="w-full min-h-[120px] rounded-xl border bg-paper-2 px-3 py-2 text-caption text-ink resize-y focus:outline-none focus:ring-2 focus:ring-ink/10"
        style={{ borderColor: "rgba(15,15,15,0.12)" }}
      />
    </article>
  );
}

function DeleteConfirmDialog({
  open,
  busy,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(v: boolean) => {
        if (!v) onCancel();
      }}
    >
      <DialogContent className="max-w-[420px]">
        <DialogTitle>Delete this Case?</DialogTitle>
        <DialogDescription>
          This removes the Case from EverOS and drops your notes. The
          underlying conversation history stays on the deal page.
        </DialogDescription>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className={cn(
              "rounded-2xl border bg-paper px-4 py-2 text-caption font-medium",
              "text-ink hover:bg-paper-3",
              "shadow-[0_2px_0_0_rgba(0,0,0,1)]"
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
              "rounded-2xl border bg-orange px-4 py-2 text-caption font-medium text-paper",
              "shadow-[0_2px_0_0_rgba(0,0,0,1)]",
              "disabled:opacity-50"
            )}
            style={{ borderColor: "rgba(15,15,15,0.5)" }}
          >
            {busy ? "Deleting…" : "Delete"}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Badge({
  label,
  tone,
}: {
  label: string;
  tone: "green" | "yellow" | "neutral";
}) {
  const cls =
    tone === "green"
      ? "bg-green-soft text-green border-green/30"
      : tone === "yellow"
        ? "bg-yellow text-ink border-yellow-deep"
        : "bg-paper-2 text-ink border-ink-line/15";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-caption font-medium",
        cls
      )}
    >
      {label}
    </span>
  );
}

function outcomeLabel(outcome?: string | null): string {
  if (outcome === "closed_deal") return "Closed deal";
  if (outcome === "no_response") return "No reply";
  if (outcome === "abandoned") return "Declined";
  return "Open";
}

function outcomeTone(outcome?: string | null): "green" | "yellow" | "neutral" {
  if (outcome === "closed_deal") return "green";
  if (outcome === "no_response" || outcome === "abandoned") return "yellow";
  return "neutral";
}
