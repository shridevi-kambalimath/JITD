import { AlertTriangle, CalendarClock, ExternalLink, ListChecks, Microscope, XCircle } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link } from "react-router";
import { type FindingSummary, type ReviewStatus, useSetReview } from "@/api/reconciliation";
import { useReviewQueue } from "@/api/workspace";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { EvidenceStateBadge, type EvidenceState } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspace } from "@/context/workspace";
import { CATEGORY_LABELS, describeEventDate, formatEventDate } from "@/lib/claims";
import { capitalize, FINDING_CATEGORY_LABELS, ISSUE_LABELS, REVIEW_LABELS } from "@/lib/reconciliation";
import { cn } from "@/lib/utils";
import { evidenceHref } from "@/lib/verification";

type StatusFilter = "all" | ReviewStatus;
const GROUPS: { state: EvidenceState; title: string; description: string }[] = [
  { state: "REVIEW_REQUIRED", title: "Review required", description: "High-risk subjects with a discrepancy or gap, or possible evidence the extractor missed." },
  { state: "CONFLICTING_EVIDENCE", title: "Conflicting evidence", description: "Records state different things. Both are kept; neither is chosen." },
  { state: "INSUFFICIENT_EVIDENCE", title: "Insufficient evidence", description: "The records do not establish this: information is missing or a referenced record is absent." },
];

export function ReviewPage() {
  const { patientId } = useWorkspace();
  const q = useReviewQueue(patientId);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const data = q.data;
  const visible = (f: FindingSummary) => filter === "all" || (filter === "pending_review" ? f.review.status === "pending_review" || f.review.changed_since_review : f.review.status === filter);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Review Queue"
        description="Everything that needs a person, most urgent first. Set a review status here or open an item for the full side-by-side view. A review status records that someone looked at an item; it is not medical approval and never changes the evidence state."
      />
      {q.isPending ? (
        <Card className="space-y-3 p-5" aria-busy="true">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-12" />)}</Card>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !data!.results_run_id ? (
        <Card>
          <EmptyState icon={<ListChecks />} title="Nothing to review yet"
            description={<>Run the analysis from the <Link to="/workspace/overview" className="text-brand underline underline-offset-2">Overview</Link> first.</>} />
        </Card>
      ) : (
        <>
          {!data!.is_current && (
            <p role="status" className="flex gap-2 rounded-md border border-conflicting-line bg-conflicting-soft px-3 py-2 text-[13px] text-ink [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-conflicting">
              <AlertTriangle /><span>This queue may be out of date: {data!.stale_reason}</span>
            </p>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[13px] text-ink-muted" data-testid="queue-counts">
              <span className="font-medium tabular-nums text-ink">{data!.counts.pending_review}</span> pending review ·{" "}
              {data!.counts.review_required} review required · {data!.counts.conflicting} conflicting · {data!.counts.insufficient} insufficient ·{" "}
              {data!.counts.unverified_claims} failed verification · {data!.counts.uncertain_dates} uncertain dates
            </p>
            <div role="group" aria-label="Filter by review status" className="flex gap-1">
              {(["all", "pending_review", "reviewed", "flagged"] as const).map((s) => (
                <button key={s} type="button" aria-pressed={filter === s} onClick={() => setFilter(s)}
                  className={cn("rounded-md border px-2 py-1 text-[12px] font-medium", filter === s ? "border-brand-line bg-brand-soft text-brand" : "border-line text-ink-muted hover:bg-subtle")}>
                  {s === "all" ? "All" : REVIEW_LABELS[s]}
                </button>
              ))}
            </div>
          </div>

          {data!.findings.length === 0 && (
            <Card><EmptyState icon={<ListChecks />} title="No discrepancies to review" description="Every reconciled subject is evidence-supported by the rules." /></Card>
          )}
          {GROUPS.map((g) => {
            const items = data!.findings.filter((f) => f.state === g.state);
            if (items.length === 0) return null;
            const shown = items.filter(visible);
            return (
              <Group key={g.state} title={<span className="flex items-center gap-2"><EvidenceStateBadge state={g.state} />{g.title}</span>} description={g.description} count={items.length} testId={`group-${g.state}`}>
                {shown.length === 0 ? <li className="px-4 py-3 text-[13px] text-ink-muted">None with this review status.</li>
                  : shown.map((f) => <FindingItem key={f.finding_id} patientId={patientId} finding={f} />)}
              </Group>
            );
          })}

          <Group title={<span className="flex items-center gap-2 [&_svg]:size-4 [&_svg]:text-review"><XCircle />Claims that failed verification</span>}
            description="Their cited text does not match the stored document. They are left out of the timeline, reconciliation and summary."
            count={data!.unverified_claims.length} testId="group-unverified">
            {data!.unverified_claims.length === 0 ? <li className="px-4 py-3 text-[13px] text-ink-muted">None: every claim passed its hard checks.</li>
              : data!.unverified_claims.map((c) => (
                <li key={c.claim_id} className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-[13px]">
                  <Badge tone="neutral">{CATEGORY_LABELS[c.claim_type]}</Badge>
                  <span className="font-medium text-ink">{c.entity}</span>
                  <span className="text-[12px] text-ink-muted">{c.document_type} · failed {(c.failed_checks ?? []).join(", ")}</span>
                  <InspectLink claimId={c.claim_id} />
                </li>
              ))}
          </Group>

          <Group title={<span className="flex items-center gap-2 [&_svg]:size-4 [&_svg]:text-ink-muted"><CalendarClock />Uncertain dates</span>}
            description="Dates that are approximate, partial, resolved from a relative expression, or written but not resolvable. Shown as recorded; worth checking where order matters."
            count={data!.uncertain_dates.length} testId="group-dates">
            {data!.uncertain_dates.length === 0 ? <li className="px-4 py-3 text-[13px] text-ink-muted">None.</li>
              : data!.uncertain_dates.map((u) => (
                <li key={u.claim_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-[13px]" data-testid="uncertain-date">
                  <span className="min-w-28 shrink-0 whitespace-nowrap font-mono font-semibold tabular-nums text-ink">{formatEventDate(u.event_date)}</span>
                  <span className="text-ink">{capitalize(u.entity)}</span>
                  <Badge tone="pending" className="whitespace-normal">{u.reason}</Badge>
                  <span className="text-[12px] text-ink-muted" title={describeEventDate(u.event_date)}>{u.document_type}{u.event_date.raw_text ? ` · “${u.event_date.raw_text}”` : ""}</span>
                  <InspectLink claimId={u.claim_id} />
                </li>
              ))}
          </Group>
        </>
      )}
    </div>
  );
}

function Group({ title, description, count, testId, children }: { title: ReactNode; description: string; count: number; testId: string; children: ReactNode }) {
  return (
    <Card data-testid={testId}>
      <div className="space-y-0.5 border-b border-line px-4 py-3">
        <div className="flex items-center justify-between gap-2 text-[14px] font-semibold text-ink"><h2>{title}</h2><span className="text-[12px] font-normal tabular-nums text-ink-faint">{count}</span></div>
        <p className="text-[12px] text-ink-muted">{description}</p>
      </div>
      <ul className="divide-y divide-line">{children}</ul>
    </Card>
  );
}

function FindingItem({ patientId, finding: f }: { patientId: string; finding: FindingSummary }) {
  const save = useSetReview(patientId);
  return (
    <li className="flex flex-wrap items-start gap-x-4 gap-y-2 px-4 py-3" data-testid="review-item">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/workspace/reconciliation?finding=${encodeURIComponent(f.finding_id)}`} className="text-[14px] font-medium text-brand hover:underline">
            {capitalize(f.subject)}
          </Link>
          <span className="text-[12px] text-ink-faint">{FINDING_CATEGORY_LABELS[f.category]}</span>
          {f.high_risk && <Badge tone="review">High risk</Badge>}
          {f.gate_rule && <span className="font-mono text-[11px] text-ink-faint">{f.gate_rule}</span>}
        </div>
        <p className="text-[12px] text-ink-muted">{f.issue_types.map((t) => ISSUE_LABELS[t] ?? t).join(" · ")}</p>
        {f.review.changed_since_review && <p className="text-[12px] text-conflicting">Changed since its status was set: please look again.</p>}
        {f.review.note && <p className="text-[12px] italic text-ink-muted">Note: {f.review.note}</p>}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-[12px] text-ink-muted">
          <span className="sr-only">Review status for {f.subject}</span>
          <select value={f.review.status} disabled={save.isPending}
            onChange={(e) => save.mutate({ findingId: f.finding_id, status: e.target.value as ReviewStatus, note: f.review.note })}
            className="h-8 rounded-md border border-line-strong bg-surface px-2 text-[13px] text-ink focus:border-brand focus:outline-none">
            {(Object.keys(REVIEW_LABELS) as ReviewStatus[]).map((s) => <option key={s} value={s}>{REVIEW_LABELS[s]}</option>)}
          </select>
        </label>
        <Link to={`/workspace/reconciliation?finding=${encodeURIComponent(f.finding_id)}`}
          className="inline-flex items-center gap-1 text-[12px] text-brand hover:underline [&_svg]:size-3.5">Sources <ExternalLink aria-hidden /></Link>
      </div>
      {save.isError && <ErrorState className="w-full" error={save.error} />}
    </li>
  );
}

function InspectLink({ claimId }: { claimId: string }) {
  return (
    <Link to={evidenceHref(claimId)} className="ml-auto inline-flex items-center gap-1 text-[12px] text-brand hover:underline [&_svg]:size-3.5">
      <Microscope aria-hidden />Inspect evidence
    </Link>
  );
}
