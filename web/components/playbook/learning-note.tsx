import { cn } from "@/lib/utils";
import type { LearningNote } from "@/types";

interface LearningNoteCardProps {
  note: LearningNote;
}

export function LearningNoteCard({ note }: LearningNoteCardProps) {
  const yellow = note.kind === "local_price_memory";

  return (
    <article
      className={cn(
        "rounded-xl border p-3.5 flex flex-col gap-1.5",
        yellow ? "bg-yellow/30 border-yellow-deep/50" : "bg-paper border-ink-line/15"
      )}
    >
      <span className="text-micro uppercase tracking-wider text-ink-3 font-semibold flex items-center gap-1.5">
        <Bolt /> {note.title}
      </span>
      <p className="text-caption text-ink leading-relaxed">{note.body}</p>
    </article>
  );
}

function Bolt() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3" fill="currentColor">
      <path d="M9 1L3 9h4l-1 6 6-8H8z" />
    </svg>
  );
}
