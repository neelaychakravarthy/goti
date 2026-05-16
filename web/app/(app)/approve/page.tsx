import { ApprovalQueue } from "@/components/approve/approval-queue";
import { BatchActionCard } from "@/components/approve/batch-action-card";
import { ControlStatusCard } from "@/components/approve/control-status-card";
import { HubHeader } from "@/components/hub/hub-header";
import { PreviewEmptyState } from "@/components/preview/preview-empty-state";
import { HUNTS, resolveHunt } from "@/lib/hunts";
import approvals from "@/mocks/approvals.json";
import outbox from "@/mocks/outbox.json";
import type { ApprovalTicket, Outbox } from "@/types";

export default async function ApprovePage({
  searchParams,
}: {
  searchParams: Promise<{ hunt?: string | string[] }>;
}) {
  const params = await searchParams;
  const raw = Array.isArray(params.hunt) ? params.hunt[0] : params.hunt;
  const huntKey = resolveHunt(raw);
  const cfg = HUNTS[huntKey];

  if (huntKey !== "standing-desk") {
    return (
      <>
        <HubHeader
          title={cfg.title}
          sub={cfg.sub}
          status={cfg.status}
          huntKey={huntKey}
        />
        <PreviewEmptyState pageLabel="Approvals" huntName={cfg.title} />
      </>
    );
  }

  const tickets = approvals as ApprovalTicket[];
  const out = outbox as Outbox;

  const stats: { label: string; value: string | number }[] = [
    { label: "Selected products", value: out.selected },
    { label: "Drafts", value: out.drafts },
    { label: "Sent", value: out.sent },
    { label: "Waiting for approval", value: out.waiting },
  ];

  return (
    <>
      <HubHeader
        title={cfg.title}
        sub={cfg.sub}
        status={cfg.status}
        huntKey={huntKey}
      />
      <div className="mx-auto max-w-[1200px] flex flex-col gap-6 px-6 py-8">
      <header className="flex flex-col gap-3 max-w-[760px]">
        <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-panel-dark text-paper px-2.5 py-1 text-caption font-medium">
          3 · Review Goti&apos;s next moves
        </span>
        <h1 className="font-display font-bold text-ink text-display-2 leading-tight tracking-tight">
          Goti drafted messages for your selected products.
        </h1>
        <p className="text-body text-ink-2">
          These messages will not leave Goti until you approve them.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-1.5">
        {stats.map((s) => (
          <span
            key={s.label}
            className="inline-flex items-baseline rounded-full bg-paper-2 px-3 py-1 text-caption text-ink-2 border border-ink-line/15"
          >
            {`${s.label}: ${s.value}`}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 lg:col-span-8">
          <ApprovalQueue tickets={tickets} />
        </div>
        <div className="col-span-12 lg:col-span-4 flex flex-col gap-4">
          <ControlStatusCard messagesSent={out.sent} />
          <BatchActionCard />
        </div>
      </div>
      </div>
    </>
  );
}
