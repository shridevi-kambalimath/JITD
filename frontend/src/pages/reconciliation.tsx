import { AlertTriangle, CheckCircle2, ChevronRight, GitCompareArrows, Info, Search, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useDocuments } from "@/api/documents";
import { type FindingDetail, type FindingSummary, type ReviewStatus, useFinding, useReconciliation, useSetReview } from "@/api/reconciliation";
import { EmptyState } from "@/components/empty-state";
import { EvidenceStateBadge } from "@/components/status-badge";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { RunAnalysisButton } from "@/components/run-analysis-button";
import { SourceCard } from "@/components/source-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspace } from "@/context/workspace";
import { capitalize, FINDING_CATEGORY_LABELS, ISSUE_KIND, ISSUE_LABELS, KIND_LABELS, KIND_TONE, OBSERVATION_LABELS, REVIEW_LABELS } from "@/lib/reconciliation";
import { cn, formatDateTime } from "@/lib/utils";

const NOTE_LIMIT = 2000;

export function ReconciliationPage() {
  const { patientId } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const list = useReconciliation(patientId);
  const docs = useDocuments(patientId);
  const processed = (docs.data ?? []).filter((d) => d.status === "processed").length;
  const data = list.data;
  const withIssues = data?.findings.filter((f) => f.priority !== null) ?? [];
  const without = data?.findings.filter((f) => f.priority === null) ?? [];
  const requested = params.get("finding");
  const selected = requested && data?.findings.some((f) => f.finding_id === requested) ? requested : withIssues[0]?.finding_id ?? null;
  const select = (id: string) => setParams({ finding: id }, { replace: true });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reconciliation"
        description="Potential documentation discrepancies across the records, each with every source side by side. MEDUSA-X shows what each record states and where they differ; it does not decide which record is correct."
        actions={data?.results_run_id ? <RunAnalysisButton patientId={patientId} processedCount={processed} hasResults /> : undefined}
      />

      {list.isPending ? (
        <Card className="space-y-3 p-5" aria-busy="true">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-12" />)}</Card>
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} />
      ) : !data!.results_run_id ? (
        <Card>
          <EmptyState icon={<GitCompareArrows />} title="Nothing reconciled yet"
            description="Reconciliation compares claims across documents. Run the analysis on this patient's processed documents first."
            action={<RunAnalysisButton patientId={patientId} processedCount={processed} hasResults={false} />} />
        </Card>
      ) : (
        <>
          {!data!.is_current && (
            <p role="status" className="flex gap-2 rounded-md border border-conflicting-line bg-conflicting-soft px-3 py-2 text-[13px] text-ink [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-conflicting">
              <AlertTriangle /><span>These results may be out of date: {data!.stale_reason}</span>
            </p>
          )}
          <p className="text-[13px] text-ink-muted" data-testid="reconciliation-counts">
            {data!.counts.findings} subjects: <span className="tabular-nums">{data!.counts.REVIEW_REQUIRED ?? 0}</span> review required ·{" "}
            <span className="tabular-nums">{data!.counts.CONFLICTING_EVIDENCE ?? 0}</span> conflicting evidence ·{" "}
            <span className="tabular-nums">{data!.counts.INSUFFICIENT_EVIDENCE ?? 0}</span> insufficient evidence ·{" "}
            <span className="tabular-nums">{data!.counts.EVIDENCE_SUPPORTED ?? 0}</span> evidence-supported ·{" "}
            <span className="font-medium text-ink tabular-nums">{data!.counts.pending_review}</span> pending review
          </p>

          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,4fr)_minmax(0,8fr)]">
            <Card className="self-start">
              <FindingList title="Needs attention" findings={withIssues} selected={selected} onSelect={select} />
              <details className="border-t border-line" open={withIssues.length === 0}>
                <summary className="cursor-pointer px-4 py-2.5 text-[12px] font-medium text-ink-muted hover:bg-canvas">
                  Evidence-supported ({without.length})
                </summary>
                <FindingList findings={without} selected={selected} onSelect={select} />
              </details>
            </Card>
            <div className="min-w-0">
              {selected ? <FindingPanel patientId={patientId} findingId={selected} runId={data!.results_run_id} /> : (
                <Card><EmptyState icon={<CheckCircle2 />} title="No potential discrepancies" description="The rules found nothing to reconcile in these records." /></Card>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function FindingList({ title, findings, selected, onSelect }: { title?: string; findings: FindingSummary[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <div>
      {title && (
        <div className="flex items-baseline justify-between border-b border-line px-4 py-2.5">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">{title}</h2>
          <span className="text-[12px] tabular-nums text-ink-faint">{findings.length}</span>
        </div>
      )}
      {findings.length === 0 ? (
        <p className="px-4 py-4 text-[13px] text-ink-muted">None.</p>
      ) : (
        <ul className="divide-y divide-line" aria-label={title ?? "Evidence-supported subjects"}>
          {findings.map((f) => (
            <li key={f.finding_id}>
              <button type="button" onClick={() => onSelect(f.finding_id)} aria-current={f.finding_id === selected || undefined}
                data-testid="finding-row"
                className={cn("flex w-full items-start gap-2 px-4 py-2.5 text-left hover:bg-canvas", f.finding_id === selected && "bg-brand-soft hover:bg-brand-soft")}>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[13px] font-medium text-ink">{capitalize(f.subject)}</span>
                    {f.high_risk && f.priority !== null && <Badge tone="review"><ShieldAlert />High risk</Badge>}
                  </div>
                  <div className="mt-0.5 text-[11px] text-ink-faint">{FINDING_CATEGORY_LABELS[f.category]} · {f.claim_count} record{f.claim_count === 1 ? "" : "s"}</div>
                  {f.issue_types.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {f.issue_types.map((t) => <Badge key={t} tone={KIND_TONE[ISSUE_KIND[t] ?? "integrity"]}>{ISSUE_LABELS[t] ?? t}</Badge>)}
                    </div>
                  )}
                  {f.issue_types.length === 0 && f.observation_rules.length > 0 && (
                    <div className="mt-0.5 text-[11px] text-ink-muted">{f.observation_rules.map((r) => OBSERVATION_LABELS[r] ?? r).join(", ")}</div>
                  )}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  {f.state && f.priority !== null && <EvidenceStateBadge state={f.state} />}
                  {f.priority !== null && <ReviewBadge status={f.review.status} changed={f.review.changed_since_review} />}
                  <ChevronRight className="size-4 text-ink-faint" aria-hidden />
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ReviewBadge({ status, changed }: { status: ReviewStatus; changed: boolean }) {
  if (changed) return <Badge tone="conflicting">Changed since review</Badge>;
  return <Badge tone={status === "reviewed" ? "supported" : status === "flagged" ? "review" : "pending"}>{REVIEW_LABELS[status]}</Badge>;
}

function FindingPanel({ patientId, findingId, runId }: { patientId: string; findingId: string; runId: string | null }) {
  const q = useFinding(patientId, findingId);
  // After a re-run the list and the detail refetch separately; until both come from the same run, show neither
  // state, so a name is never paired with an evidence state from another run.
  const otherRun = q.data !== undefined && q.data.results_run_id !== runId;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.isPending || otherRun) return <Card className="space-y-3 p-5" aria-busy="true" data-testid="finding-loading"><Skeleton className="h-6 w-48" /><Skeleton className="h-40" /></Card>;
  const f = q.data;
  const byId = new Map(f.claims.map((c) => [c.claim_id, c]));
  const cited = new Set(f.issues.flatMap((i) => i.claim_ids));
  const others = f.claims.filter((c) => !cited.has(c.claim_id));

  return (
    <Card aria-label={`Finding ${capitalize(f.subject)}`}>
      <CardHeader className="flex-wrap items-start">
        <div className="min-w-0">
          <h2 className="text-[16px] font-semibold text-ink">{capitalize(f.subject)}</h2>
          <p className="text-[12px] text-ink-muted">
            {FINDING_CATEGORY_LABELS[f.category]} · {f.claims.length} record{f.claims.length === 1 ? "" : "s"} · <span className="font-mono">{f.finding_id}</span>
          </p>
          {f.high_risk && f.risk_reason && <p className="mt-1 text-[12px] text-review">High risk: {f.risk_reason} (prototype setting, not a clinical standard)</p>}
        </div>
        {f.state && (
          <div className="flex items-center gap-2" data-testid="finding-state">
            <EvidenceStateBadge state={f.state} />
            {f.gate_rule && <span className="font-mono text-[11px] text-ink-faint">{f.gate_rule}</span>}
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-6">
        {f.gate_rationale && (
          <p className="rounded-md border border-line bg-canvas px-3 py-2 text-[13px] text-ink" data-testid="gate-rationale">
            <span className="font-medium">Why this state: </span>{f.gate_rationale}
            <span className="block text-[11px] text-ink-faint">Decided by the first matching gate rule. States describe what the records establish, not clinical correctness.</span>
          </p>
        )}
        {f.issues.length === 0 ? (
          <p className="flex gap-2 text-[13px] text-ink-muted [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:text-supported"><CheckCircle2 />No potential discrepancy found by the rules for this subject.</p>
        ) : (
          <section aria-label="Potential discrepancies" className="space-y-4">
            {f.issues.map((issue, n) => {
              const sides = issue.claim_ids.map((id) => byId.get(id)).filter((c) => c !== undefined);
              return (
                <div key={`${issue.rule_id}-${n}`} className="rounded-md border border-line" data-testid="issue">
                  <div className="space-y-1 border-b border-line px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={KIND_TONE[issue.kind]}>{KIND_LABELS[issue.kind]}</Badge>
                      <span className="text-[13px] font-medium text-ink">{ISSUE_LABELS[issue.issue_type] ?? issue.issue_type}</span>
                      <span className="ml-auto font-mono text-[11px] text-ink-faint">{issue.rule_id}</span>
                    </div>
                    <p className="text-[13px] text-ink">{issue.description}</p>
                  </div>
                  {sides.length > 0 && (
                    <div className={cn("grid gap-3 p-3", sides.length >= 3 ? "lg:grid-cols-3" : sides.length === 2 ? "md:grid-cols-2" : "")} data-testid="issue-sources">
                      {sides.map((c, i) => <SourceCard key={c.claim_id} claim={c} label={sides.length > 1 ? String.fromCharCode(65 + i) : undefined} />)}
                    </div>
                  )}
                </div>
              );
            })}
          </section>
        )}

        {f.observations.length > 0 && (
          <section aria-label="Examined and not flagged">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">Examined and not flagged</h3>
            <ul className="space-y-2">
              {f.observations.map((o, i) => (
                <li key={i} className="flex gap-2 rounded-md border border-line bg-canvas px-3 py-2 text-[13px] text-ink [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-ink-faint">
                  <Info /><span><span className="font-medium">{OBSERVATION_LABELS[o.rule_id] ?? o.rule_id}</span> <span className="font-mono text-[11px] text-ink-faint">{o.rule_id}</span><br />{o.text}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {f.investigation.length > 0 && (
          <section aria-label="Retrieval check">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">Retrieval check for missed evidence</h3>
            <ul className="space-y-1.5">
              {f.investigation.map((s, i) => (
                <li key={i} className="flex gap-2 text-[12px] text-ink-muted [&_svg]:mt-0.5 [&_svg]:size-3.5 [&_svg]:shrink-0">
                  <Search /><span>{s.outcome} <span className="text-ink-faint">({s.hits.length} section{s.hits.length === 1 ? "" : "s"} matched “{s.query}”)</span></span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {others.length > 0 && (
          <section aria-label="Other records for this subject">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">
              {f.issues.length ? "Other records for this subject" : "Records for this subject"} ({others.length})
            </h3>
            <div className="grid gap-3 md:grid-cols-2">{others.map((c) => <SourceCard key={c.claim_id} claim={c} />)}</div>
          </section>
        )}
        {f.missing_claim_ids.length > 0 && (
          <p className="text-[12px] text-conflicting">{f.missing_claim_ids.length} cited record(s) are no longer stored because their document was removed. Re-run the analysis.</p>
        )}

        {f.priority !== null && <ReviewPanel patientId={patientId} finding={f} />}
      </CardContent>
    </Card>
  );
}

function ReviewPanel({ patientId, finding: f }: { patientId: string; finding: FindingDetail }) {
  const save = useSetReview(patientId);
  const [status, setStatus] = useState<ReviewStatus>(f.review.status);
  const [note, setNote] = useState(f.review.note ?? "");
  const [saved, setSaved] = useState(false);
  // another finding: start fresh
  useEffect(() => setSaved(false), [f.finding_id]);
  // follow the stored value (after a save, or a change made elsewhere)
  useEffect(() => {
    setStatus(f.review.status);
    setNote(f.review.note ?? "");
  }, [f.finding_id, f.review.status, f.review.note]);
  const dirty = status !== f.review.status || note.trim() !== (f.review.note ?? "");

  return (
    <section aria-label="Review" className="space-y-3 rounded-md border border-line bg-canvas p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">Review status</h3>
        {f.review.updated_at && <span className="text-[11px] text-ink-faint">last set {formatDateTime(f.review.updated_at)}</span>}
      </div>
      {f.review.changed_since_review && (
        <p role="status" className="text-[12px] text-conflicting">This item changed after its status was set (a later analysis found different issues). Please look again.</p>
      )}
      <div role="radiogroup" aria-label="Review status" className="flex flex-wrap gap-2">
        {(Object.keys(REVIEW_LABELS) as ReviewStatus[]).map((s) => (
          <label key={s} className={cn("flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[13px]", status === s ? "border-brand-line bg-brand-soft text-brand" : "border-line bg-surface text-ink-muted")}>
            <input type="radio" name={`review-${f.finding_id}`} value={s} checked={status === s} onChange={() => { setStatus(s); setSaved(false); }} className="accent-[var(--color-brand)]" />
            {REVIEW_LABELS[s]}
          </label>
        ))}
      </div>
      <label className="block">
        <span className="text-[12px] text-ink-muted">Note (optional)</span>
        <textarea value={note} maxLength={NOTE_LIMIT} rows={3} onChange={(e) => { setNote(e.target.value); setSaved(false); }}
          className="mt-1 block w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-[13px] text-ink focus:border-brand focus:outline-none" />
        <span className="text-[11px] tabular-nums text-ink-faint">{note.length}/{NOTE_LIMIT}</span>
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" disabled={!dirty} loading={save.isPending}
          onClick={() => save.mutate({ findingId: f.finding_id, status, note: note.trim() || null }, { onSuccess: () => setSaved(true) })}>
          Save review status
        </Button>
        {saved && !dirty && <span role="status" className="text-[12px] text-supported">Saved</span>}
      </div>
      {save.isError && <ErrorState error={save.error} />}
      <p className="text-[11px] text-ink-faint">
        A review status records that a person looked at this item. It is not medical approval and does not change the finding or the records.
      </p>
    </section>
  );
}
