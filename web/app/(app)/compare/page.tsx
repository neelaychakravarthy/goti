import { CompareDeskContent } from "@/components/compare/compare-desk-content";
import { HubHeader } from "@/components/hub/hub-header";
import { PreviewEmptyState } from "@/components/preview/preview-empty-state";
import { HUNTS, resolveHunt } from "@/lib/hunts";

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ hunt?: string | string[] }>;
}) {
  const params = await searchParams;
  const raw = Array.isArray(params.hunt) ? params.hunt[0] : params.hunt;
  const huntKey = resolveHunt(raw);
  const cfg = HUNTS[huntKey];

  return (
    <div className="flex flex-col">
      <HubHeader
        title={cfg.title}
        sub={cfg.sub}
        status={cfg.status}
        huntKey={huntKey}
      />
      {huntKey === "standing-desk" ? (
        <CompareDeskContent />
      ) : (
        <PreviewEmptyState pageLabel="Best options" huntName={cfg.title} />
      )}
    </div>
  );
}
