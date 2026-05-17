"use client";

// Phase L — top-of-chat "Running" strip. Polls
// ``GET /api/hunts/{id}/running-tasks`` every 3s and renders a small
// row of pill-shaped status chips per live task. Hides itself when no
// tasks are running. Reuses the existing color tokens (paper / ink /
// yellow / green).
//
// Phase O of the followups round adds a "Stopped" sub-strip rendered
// above Running when the durable async_tasks table has any
// ``interrupted`` rows for the hunt. Each row has a Resume button
// that calls POST /api/tasks/{id}/resume; on success we
// optimistically refresh both lists so the row hops from Stopped →
// Running.

import { useCallback, useEffect, useState } from "react";

import { ApiError, getRunningTasks, getStoppedTasks, resumeTask } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { RunningTask, StoppedTask } from "@/types";

const POLL_INTERVAL_MS = 3_000;

interface Props {
  huntId: string;
  className?: string;
}

export function TaskStatusStrip({ huntId, className }: Props) {
  const [tasks, setTasks] = useState<RunningTask[]>([]);
  const [stoppedTasks, setStoppedTasks] = useState<StoppedTask[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [running, stopped] = await Promise.all([
        getRunningTasks(huntId).catch(() => ({ tasks: [] })),
        getStoppedTasks(huntId).catch(() => ({ tasks: [] })),
      ]);
      setTasks(running.tasks ?? []);
      setStoppedTasks(stopped.tasks ?? []);
      setLoaded(true);
    } catch {
      setLoaded(true);
    }
  }, [huntId]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (cancelled) return;
      await refresh();
    }
    load();
    const id = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [refresh]);

  if (!loaded || (tasks.length === 0 && stoppedTasks.length === 0)) {
    return null;
  }

  return (
    <div className={cn("flex flex-col gap-2", className)} aria-live="polite">
      {stoppedTasks.length > 0 ? (
        <div
          className="flex flex-wrap items-center gap-2 rounded-2xl border bg-paper-2 px-3 py-2"
          style={{ borderColor: "rgba(15,15,15,0.08)" }}
        >
          <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
            Stopped
          </span>
          {stoppedTasks.map((task) => (
            <StoppedTaskChip
              key={task.id}
              task={task}
              onResumed={refresh}
            />
          ))}
        </div>
      ) : null}
      {tasks.length > 0 ? (
        <div
          className="flex flex-wrap items-center gap-2 rounded-2xl border bg-paper-2 px-3 py-2"
          style={{ borderColor: "rgba(15,15,15,0.08)" }}
        >
          <span className="text-micro uppercase tracking-[0.08em] text-ink-3 font-semibold">
            Running
          </span>
          {tasks.map((task) => (
            <TaskChip key={task.task_id} task={task} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function StoppedTaskChip({
  task,
  onResumed,
}: {
  task: StoppedTask;
  onResumed: () => void;
}) {
  const dot = dotColorForKind(task.kind);
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const handleResume = useCallback(async () => {
    if (busy || !task.can_resume) return;
    setBusy(true);
    setErrMsg(null);
    try {
      await resumeTask(task.id);
      await onResumed();
    } catch (e) {
      if (e instanceof ApiError) {
        setErrMsg(`Resume failed (${e.status})`);
      } else if (e instanceof Error) {
        setErrMsg(e.message);
      } else {
        setErrMsg("Resume failed");
      }
    } finally {
      setBusy(false);
    }
  }, [busy, task.can_resume, task.id, onResumed]);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full bg-paper border px-2.5 py-1 text-micro text-ink",
      )}
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
    >
      <span
        aria-hidden
        className="inline-flex size-2 rounded-full"
        style={{ background: dot, opacity: 0.5 }}
      />
      <span className="font-medium">{task.label}</span>
      {task.can_resume ? (
        <button
          type="button"
          onClick={handleResume}
          disabled={busy}
          className={cn(
            "text-micro rounded-full px-2 py-0.5 font-semibold transition",
            "bg-ink text-paper hover:opacity-90 disabled:opacity-50",
          )}
        >
          {busy ? "Resuming…" : "Resume"}
        </button>
      ) : (
        <span className="text-micro text-ink-3">not auto-resumable</span>
      )}
      {errMsg ? (
        <span className="text-micro text-orange">{errMsg}</span>
      ) : null}
    </span>
  );
}

function TaskChip({ task }: { task: RunningTask }) {
  const dot = dotColorForKind(task.kind);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full bg-paper border px-2.5 py-1",
        "text-micro text-ink"
      )}
      style={{ borderColor: "rgba(15,15,15,0.12)" }}
    >
      <span
        aria-hidden
        className="inline-flex size-2 rounded-full animate-pulse"
        style={{ background: dot }}
      />
      <span className="font-medium">{task.label}</span>
      {task.elapsed_s ? (
        <span className="text-ink-3 font-mono">
          {Math.max(1, Math.round(task.elapsed_s))}s
        </span>
      ) : null}
    </span>
  );
}

function dotColorForKind(kind: string): string {
  switch (kind) {
    case "discovery":
      return "var(--yellow, #d97706)";
    case "negotiator_draft":
      return "#8b5cf6";
    case "classifier":
      return "#0ea5e9";
    case "check_replies":
      return "#0ea5e9";
    case "finalize_close":
      return "var(--green, #16a34a)";
    case "analyzer":
    case "analyzer_job":
      return "var(--orange, #f97316)";
    default:
      return "var(--ink-3, #6b7280)";
  }
}
