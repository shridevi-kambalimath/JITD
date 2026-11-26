import { Activity, AlertTriangle, ExternalLink, Microscope, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import type { ClaimCategory } from "@/api/analysis";
import { useDocuments } from "@/api/documents";
import { type TimelineEntry, useTimeline } from "@/api/timeline";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { RunAnalysisButton } from "@/components/run-analysis-button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspace } from "@/context/workspace";
import { CATEGORY_LABELS, methodLabel } from "@/lib/claims";
import { groupByWhen, placementText, precisionTag } from "@/lib/timeline";
import { cn } from "@/lib/utils";
import { evidenceHref } from "@/lib/verification";

const CATEGORY_ORDER: ClaimCategory[] = ["encounter", "symptom", "procedure", "lab_result", "diagnosis", "medication", "allergy", "record_reference"];

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function TimelinePage() {
  const { patientId } = useWorkspace();
  const [category, setCategory] = useState<ClaimCategory | null>(null);
  const [search, setSearch] = useState("");
  const q = useDebounced(search, 250);
  const timeline = useTimeline(patientId, { category, q });
  const docs = useDocuments(patientId);
  const processed = (docs.data ?? []).filter((d) => d.status === "processed").length;
  const data = timeline.data;
  const filtered = !!category || !!q.trim();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Clinical Timeline"
        description="What the documents record, in date order, built from verified claims. Each entry is placed by the event date its passage states; if the passage states none, by its document's date, and it says so. No date is inferred."
        actions={data?.results_run_id ? <RunAnalysisButton patientId={patientId} processedCount={processed} hasResults /> : undefined}
      />

      {timeline.isPending ? (
        <Card className="space-y-3 p-5" aria-busy="true">
          {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-12" />)}
        </Card>
      ) : timeline.isError ? (
        <ErrorState error={timeline.error} onRetry={() => timeline.refetch()} />
      ) : !data!.results_run_id ? (
        <Card>
          <EmptyState
            icon={<Activity />}
            title="No timeline yet"
            description="The timeline is built from extracted claims. Run the analysis on this patient's processed documents first."
            action={<RunAnalysisButton patientId={patientId} processedCount={processed} hasResults={false} />}
          />
        </Card>
      ) : (
        <>
          {!data!.is_current && (
            <p role="status" className="flex gap-2 rounded-md border border-conflicting-line bg-conflicting-soft px-3 py-2 text-[13px] text-ink [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-conflicting">
              <AlertTriangle />
              <span>This timeline may be out of date: {data!.stale_reason}</span>
            </p>
          )}

          <Card>
            <div className="space-y-3 border-b border-line px-5 py-4">
              <p className="text-[13px] text-ink-muted" data-testid="timeline-counts">
                <span className="font-medium text-ink tabular-nums">{data!.total}</span> entries ·{" "}
                <span className="tabular-nums">{data!.by_basis.event_date ?? 0}</span> placed by a stated event date ·{" "}
                <span className="tabular-nums">{data!.by_basis.document_date ?? 0}</span> by document date only
                {(data!.by_basis.undated ?? 0) > 0 && <> · <span className="tabular-nums">{data!.by_basis.undated}</span> undated</>}
                {data!.excluded_unverified > 0 && <> · <span className="text-review"><span className="tabular-nums">{data!.excluded_unverified}</span> left off because they failed verification</span></>}
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <label className="relative block w-full sm:w-72">
                  <span className="sr-only">Search the timeline</span>
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-ink-faint" aria-hidden />
                  <input
                    type="search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    maxLength={200}
                    placeholder="Search entries, quotes, documents"
                    className="h-9 w-full rounded-md border border-line-strong bg-surface pl-8 pr-3 text-[13px] text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none"
                  />
                </label>
                <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by category">
                  <Chip active={category === null} onClick={() => setCategory(null)} label="All" count={data!.total} />
                  {CATEGORY_ORDER.filter((c) => data!.by_category[c]).map((c) => (
                    <Chip key={c} active={category === c} onClick={() => setCategory(category === c ? null : c)} label={CATEGORY_LABELS[c]} count={data!.by_category[c]!} />
                  ))}
                </div>
              </div>
            </div>

            {data!.entries.length === 0 ? (
              <EmptyState
                icon={<Search />}
                title="No entries match"
                description="Try another search term or category."
                action={filtered ? <button type="button" onClick={() => { setCategory(null); setSearch(""); }} className="inline-flex items-center gap-1 text-[13px] text-brand hover:underline [&_svg]:size-3.5"><X />Clear filters</button> : undefined}
              />
            ) : (
              <ol aria-label="Timeline" className={cn("divide-y divide-line", timeline.isFetching && "opacity-60")}>
                {groupByWhen(data!.entries).map((g) => (
                  <li key={g.when} className="grid gap-x-6 gap-y-2 px-5 py-4 md:grid-cols-[140px_minmax(0,1fr)]" data-testid="timeline-group">
                    <div className="md:pt-1">
                      <span className="font-mono text-[13px] font-semibold tabular-nums text-ink">{g.when}</span>
                      <span className="ml-2 text-[11px] text-ink-faint md:ml-0 md:block">{g.entries.length} entr{g.entries.length === 1 ? "y" : "ies"}</span>
                    </div>
                    <ul className="space-y-2">
                      {g.entries.map((e) => <Entry key={e.claim_id} entry={e} />)}
                    </ul>
                  </li>
                ))}
              </ol>
            )}
          </Card>
          <p className="text-[12px] text-ink-faint">
            Solid border: placed by an event date the passage states. Dashed border: the passage states no date, so the entry sits at its document's date.
            Only claims that pass verification against their source appear. Entries record what each document says, not whether it is clinically right.
          </p>
        </>
      )}
    </div>
  );
}

function Chip({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count: number }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn("rounded-md border px-2 py-1 text-[12px] font-medium", active ? "border-brand-line bg-brand-soft text-brand" : "border-line text-ink-muted hover:bg-subtle")}
    >
      {label} <span className="tabular-nums text-ink-faint">{count}</span>
    </button>
  );
}

function Entry({ entry: e }: { entry: TimelineEntry }) {
  const tag = precisionTag(e);
  const method = methodLabel(e);
  const byDocument = e.ordering_basis !== "event_date";
  return (
    <li
      className={cn("rounded-md border px-3 py-2.5 text-[13px]", byDocument ? "border-dashed border-line-strong bg-canvas" : "border-line bg-surface")}
      data-testid="timeline-entry"
      data-basis={e.ordering_basis}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Badge tone="neutral">{CATEGORY_LABELS[e.category]}</Badge>
        <span className="font-medium text-ink">{e.label}</span>
        {e.assertion && e.assertion !== "present" && <Badge tone="insufficient">{e.assertion}</Badge>}
        {tag && <Badge tone="pending">{tag}</Badge>}
        <Badge className="ml-auto" tone={method.short === "LLM" ? "pending" : "brand"} title={method.detail}>{method.short}</Badge>
      </div>
      <p className="mt-1 text-[12px] text-ink-muted">{placementText(e)}</p>
      <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="min-w-0 text-[12px] text-ink-faint">
          <q className="font-mono text-ink-muted">{e.quote}</q> · {e.document_type} · {e.section}
        </p>
        <span className="flex shrink-0 items-center gap-3">
          <Link to={evidenceHref(e.claim_id)} className="inline-flex items-center gap-1 text-[12px] text-brand hover:underline [&_svg]:size-3.5">
            <Microscope aria-hidden />Inspect evidence
          </Link>
          <Link
            to={`/workspace/documents?doc=${encodeURIComponent(e.document_id)}&claim=${encodeURIComponent(e.claim_id)}`}
            className="inline-flex items-center gap-1 text-[12px] text-brand hover:underline [&_svg]:size-3.5"
          >
            View source <ExternalLink aria-hidden />
          </Link>
        </span>
      </div>
    </li>
  );
}
