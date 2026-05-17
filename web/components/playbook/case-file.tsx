import { cn } from "@/lib/utils";
import type { Case } from "@/types";

interface CaseFileProps {
  caseFile: Case;
  variant?: "primary" | "secondary";
}

export function CaseFile({ caseFile, variant = "primary" }: CaseFileProps) {
  const isPrimary = variant === "primary";

  return (
    <article
      className={cn(
        "relative rounded-2xl border bg-paper p-5 pt-7 flex flex-col gap-3",
        isPrimary ? "border-ink-line/30" : "border-ink-line/15"
      )}
      style={{ borderColor: isPrimary ? "rgba(15,15,15,0.22)" : "rgba(15,15,15,0.12)" }}
    >
      <span
        className="absolute -top-2 left-4 inline-flex items-center rounded-md border bg-orange text-paper px-2 py-0.5 text-micro font-mono font-semibold"
        style={{ borderColor: "var(--ink-line)" }}
      >
        {caseFile.case_id}
      </span>

      <div className="flex flex-col gap-1">
        <h3
          className={cn(
            "font-display font-bold text-ink leading-tight",
            isPrimary ? "text-headline" : "text-body"
          )}
        >
          {caseFile.title}
        </h3>
        <span className="text-caption text-ink-3">{caseFile.location}</span>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Stat
          label="Start"
          value={`$${caseFile.start_price}`}
          tone="neutral"
        />
        <Stat
          label="Closed"
          value={`$${caseFile.closed_price}`}
          tone="green"
        />
        <Stat label="Saved" value={`$${caseFile.saved}`} tone="yellow" />
      </div>

      <div
        className="rounded-xl border bg-paper-2 p-3"
        style={{ borderColor: "rgba(15,15,15,0.12)" }}
      >
        <div className="text-micro uppercase tracking-wider text-ink-3 font-semibold">
          Tactic learned
        </div>
        <p className="text-caption text-ink mt-1 font-medium">
          {caseFile.tactic_learned}
        </p>
      </div>

      <div
        className="rounded-xl border bg-paper p-3"
        style={{ borderColor: "rgba(15,15,15,0.1)" }}
      >
        <div className="text-micro uppercase tracking-wider text-ink-3 font-medium">
          Seller pattern
        </div>
        <p className="text-caption text-ink-2 mt-1">
          {caseFile.seller_pattern}
        </p>
      </div>

      {caseFile.learning_attached ? (
        <p className="text-micro text-ink-3 italic">
          {caseFile.learning_attached}
        </p>
      ) : null}
    </article>
  );
}

function Stat({
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
      <div className="text-body font-display font-bold leading-tight">
        {value}
      </div>
    </div>
  );
}
