interface StackHeroProps {
  brief: string;
  stats: {
    found: number;
    worth_pursuing: number;
    best_likely_close: number;
    projected_savings: string;
  };
}

export function StackHero({ brief, stats }: StackHeroProps) {
  return (
    <div className="rounded-2xl bg-panel-dark text-paper p-6 flex flex-col gap-4 border border-ink-line h-full">
      <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-panel-dark-2 px-2.5 py-1 text-caption font-medium text-paper/80 border border-paper/15">
        2 · Compare sellers
      </span>
      <h1 className="font-display font-bold text-paper text-display-2 md:text-display-1 leading-tight tracking-tight max-w-[640px]">
        Best options found.
      </h1>
      <p className="text-body text-paper/70">{brief}</p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
        <StatTile label="Found" value={stats.found.toString()} />
        <StatTile label="Worth pursuing" value={stats.worth_pursuing.toString()} />
        <StatTile
          label="Best likely close"
          value={`$${stats.best_likely_close}`}
        />
        <StatTile
          label="Projected savings"
          value={stats.projected_savings}
          accent
        />
      </div>
    </div>
  );
}

function StatTile({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div
      className={
        accent
          ? "rounded-lg bg-yellow text-ink border border-yellow-deep px-3 py-2.5"
          : "rounded-lg bg-panel-dark-2 text-paper border border-paper/10 px-3 py-2.5"
      }
    >
      <div
        className={
          accent
            ? "text-micro uppercase tracking-wider font-medium text-ink-2"
            : "text-micro uppercase tracking-wider font-medium text-paper/55"
        }
      >
        {label}
      </div>
      <div className="text-headline font-display font-bold leading-tight">
        {value}
      </div>
    </div>
  );
}
