import { CaseFile } from "@/components/playbook/case-file";
import { HubHeader } from "@/components/hub/hub-header";
import { LearningNoteCard } from "@/components/playbook/learning-note";
import { NewLearningCard } from "@/components/playbook/new-learning-card";
import { PreviewEmptyState } from "@/components/preview/preview-empty-state";
import { HUNTS, resolveHunt } from "@/lib/hunts";
import playbook from "@/mocks/playbook.json";
import type { Playbook } from "@/types";

export default async function PlaybookPage({
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
        <PreviewEmptyState pageLabel="Playbook" huntName={cfg.title} />
      </>
    );
  }

  const pb = playbook as Playbook;

  return (
    <>
      <HubHeader
        title={cfg.title}
        sub={cfg.sub}
        status={cfg.status}
        huntKey={huntKey}
      />
      <div className="mx-auto max-w-[1200px] flex flex-col gap-6 px-6 py-10">
        <div className="grid grid-cols-12 gap-4 items-start">
          <header className="col-span-12 lg:col-span-7 flex flex-col gap-2">
            <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-panel-dark text-paper px-2.5 py-1 text-caption font-medium">
              5 · Goti&apos;s playbook
            </span>
            <h1
              className="font-display font-bold text-ink leading-tight tracking-tight"
              style={{ fontSize: "32px" }}
            >
              Every close becomes a case file.
            </h1>
            <p className="text-body text-ink-2 max-w-[640px]">
              Goti saves what worked, so the next negotiation starts smarter.
            </p>
          </header>

          <div className="col-span-12 lg:col-span-5">
            <NewLearningCard body={pb.new_learning.body} />
          </div>
        </div>

        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 lg:col-span-8 grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
            {pb.cases.map((c, i) => (
              <div key={c.case_id} className={i === 0 ? "" : "md:mt-4"}>
                <CaseFile caseFile={c} variant={i === 0 ? "primary" : "secondary"} />
              </div>
            ))}
          </div>

          <div className="col-span-12 lg:col-span-4 flex flex-col gap-3">
            {pb.notes.map((n) => (
              <LearningNoteCard key={n.kind} note={n} />
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
