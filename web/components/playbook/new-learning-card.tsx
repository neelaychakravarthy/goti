interface NewLearningCardProps {
  body: string;
}

export function NewLearningCard({ body }: NewLearningCardProps) {
  return (
    <aside
      className="rounded-xl border bg-yellow text-ink px-4 py-3 flex flex-col gap-1.5 shadow-[0_1px_0_0_rgba(0,0,0,1)]"
      style={{ borderColor: "var(--yellow-deep)" }}
    >
      <span className="text-micro uppercase tracking-wider font-semibold text-ink-2 flex items-center gap-1.5">
        <Bolt /> New learning
      </span>
      <p className="font-display font-semibold text-ink text-body leading-snug">
        {body}
      </p>
    </aside>
  );
}

function Bolt() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="size-3" fill="currentColor">
      <path d="M9 1L3 9h4l-1 6 6-8H8z" />
    </svg>
  );
}
