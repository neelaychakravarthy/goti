export function BatchActionCard() {
  return (
    <aside className="rounded-2xl border bg-panel-dark text-paper p-5 flex flex-col gap-3 border-ink-line">
      <span className="text-micro uppercase tracking-wider text-orange font-semibold">
        Batch action
      </span>
      <h3 className="text-headline font-display font-bold leading-tight text-paper">
        Approve selected messages.
      </h3>
      <p className="text-caption text-paper/70 leading-relaxed">
        Goti recommends sending to Uplift and Vari now, and waiting on the
        Craigslist seller because trust signals are weaker there.
      </p>
      <div className="flex flex-col gap-1.5 pt-1">
        <button
          type="button"
          disabled
          title="Preview build"
          className="rounded-lg bg-orange text-paper font-semibold py-2 border border-ink-line shadow-[0_2px_0_0_rgba(0,0,0,1)] opacity-60 cursor-not-allowed"
        >
          Approve selected messages
        </button>
        <button
          type="button"
          disabled
          title="Preview build"
          className="rounded-lg bg-transparent text-paper font-medium py-2 border border-paper/30 opacity-60 cursor-not-allowed"
        >
          Edit all first
        </button>
      </div>
    </aside>
  );
}
