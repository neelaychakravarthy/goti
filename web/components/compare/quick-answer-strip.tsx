interface QuickAnswerCellProps {
  label: string;
  primary: string;
  detail: string;
  accent?: "yellow" | "green" | "neutral";
}

const ACCENT: Record<NonNullable<QuickAnswerCellProps["accent"]>, string> = {
  yellow: "bg-yellow/20 border-yellow-deep/40",
  green: "bg-green-soft border-green/30",
  neutral: "bg-paper-2 border-ink-line/15",
};

function Cell({ label, primary, detail, accent = "neutral" }: QuickAnswerCellProps) {
  return (
    <div className={`rounded-xl border px-3.5 py-3 ${ACCENT[accent]}`}>
      <div className="text-micro uppercase tracking-wider font-medium text-ink-3">
        {label}
      </div>
      <div className="text-body font-display font-bold text-ink mt-1">
        {primary}
      </div>
      <div className="text-caption text-ink-2 mt-0.5">{detail}</div>
    </div>
  );
}

export function QuickAnswerStrip() {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
      <Cell label="Best price" primary="FlexiSpot" detail="likely $195" accent="yellow" />
      <Cell label="Best item" primary="Uplift" detail="retail $599" />
      <Cell label="Fastest pickup" primary="Vari" detail="today" />
      <Cell label="Safest seller" primary="Nextdoor" detail="verified" accent="green" />
    </div>
  );
}
