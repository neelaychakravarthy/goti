interface ControlStatusCardProps {
  messagesSent: number;
}

export function ControlStatusCard({ messagesSent }: ControlStatusCardProps) {
  return (
    <aside
      className="rounded-2xl border-2 bg-paper p-5 flex flex-col gap-2"
      style={{ borderColor: "var(--green)" }}
    >
      <span className="text-micro uppercase tracking-wider text-green font-semibold">
        Control status
      </span>
      <div className="text-headline font-display font-bold text-ink leading-tight">
        {messagesSent} messages sent
      </div>
      <p className="text-caption text-ink-2 leading-relaxed">
        Approve one, approve all, edit drafts, or skip a seller. Goti stays
        paused.
      </p>
    </aside>
  );
}
