interface PreviewEmptyStateProps {
  pageLabel: string;
  huntName: string;
}

/**
 * Centered "this hunt is in preview" placeholder shown on downstream pages
 * (compare/approve/playbook) for hunts that backend hasn't wired yet.
 */
export function PreviewEmptyState({ pageLabel, huntName }: PreviewEmptyStateProps) {
  return (
    <div className="mx-auto max-w-[1200px] px-6 py-16 flex items-center justify-center">
      <div
        className="w-full max-w-[480px] rounded-2xl border bg-paper py-12 px-8 text-center flex flex-col gap-3"
        style={{ borderColor: "var(--ink-line)" }}
      >
        <span className="text-micro uppercase tracking-[0.12em] text-ink-3 font-semibold">
          DEMO PREVIEW
        </span>
        <h2 className="font-display font-bold text-headline text-ink leading-tight">
          This hunt is in preview.
        </h2>
        <p className="text-body text-ink-2 leading-relaxed">
          Backend will wire {pageLabel} for {huntName} next. Standing desk is the
          live demo path.
        </p>
      </div>
    </div>
  );
}
