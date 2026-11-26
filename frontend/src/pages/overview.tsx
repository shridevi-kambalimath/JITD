import { CheckCircle2, FileText, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import type { LlmConfig } from "@/api/analysis";
import { useDocuments, useLoadDemo } from "@/api/documents";
import { useHealth, useReadiness } from "@/api/health";
import { type OverviewResponse, useOverview } from "@/api/workspace";
import { AnalysisSummary } from "@/components/analysis-summary";
import { EmptyState } from "@/components/empty-state";
import { EvidenceStateBar } from "@/components/evidence-state-bar";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { RunAnalysisButton } from "@/components/run-analysis-button";
import { DocumentStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspace } from "@/context/workspace";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

/** "unreachable" only when nothing answered; an HTTP error means a server answered but is not this API. */
function failureText(error: unknown): string {
  return error instanceof ApiError && !error.isNetworkError ? `wrong server (HTTP ${error.status})` : "unreachable";
}

interface Stage {
  name: string;
  value: ReactNode;
  detail: ReactNode;
}

function PipelineStage({ stage, index }: { stage: Stage; index: number }) {
  return (
    <li className="bg-surface px-4 py-3.5" data-testid={`stage-${stage.name}`}>
      <span className="font-mono text-[11px] text-ink-faint">{String(index + 1).padStart(2, "0")}</span>
      <p className="mt-1.5 text-[13px] font-medium text-ink">{stage.name}</p>
      <p className="mt-1 text-[22px] font-semibold tabular-nums tracking-tight text-ink">{stage.value}</p>
      <p className="mt-0.5 text-[12px] text-ink-muted">{stage.detail}</p>
    </li>
  );
}

/** Every value comes from GET /overview; nothing is computed or defaulted to a number here. */
function buildStages(o: OverviewResponse): Stage[] {
  const analysed = o.analysis.results_run !== null;
  const stale = analysed && !o.analysis.is_current ? <span className="text-conflicting"> · stale</span> : null;
  const none = { value: "–", detail: "not analysed yet" };
  return [
    {
      name: "Documents",
      value: o.documents.processed,
      detail: <>processed{o.documents.failed > 0 && <span className="text-review"> · {o.documents.failed} failed</span>}</>,
    },
    analysed
      ? { name: "Claims & events", value: o.claims.total, detail: <>{o.claims.rule} rule · {o.claims.llm} LLM{stale}</> }
      : { name: "Claims & events", ...none },
    analysed
      ? {
          name: "Timeline entries",
          value: o.timeline.entries,
          detail: <><Link to="/workspace/timeline" className="hover:text-brand hover:underline">{o.timeline.by_event_date} by event date · {o.timeline.by_document_date} by document date</Link>{stale}</>,
        }
      : { name: "Timeline entries", ...none },
    analysed
      ? {
          name: "Discrepancies",
          value: o.reconciliation.needs_attention,
          detail: (
            <>
              <Link to="/workspace/reconciliation" className="hover:text-brand hover:underline">
                {o.reconciliation.REVIEW_REQUIRED} review · {o.reconciliation.CONFLICTING_EVIDENCE} conflicting · {o.reconciliation.INSUFFICIENT_EVIDENCE} insufficient
              </Link>
              {stale}
            </>
          ),
        }
      : { name: "Discrepancies", ...none },
    analysed
      ? {
          name: "Verified claims",
          value: o.claims.verified,
          detail: <>of {o.claims.total} · {o.claims.failed_verification > 0 ? <span className="text-review">{o.claims.failed_verification} failed checks</span> : "all hard checks pass"}{stale}</>,
        }
      : { name: "Verified claims", ...none },
    analysed
      ? {
          name: "Needs review",
          value: o.reconciliation.pending_review,
          detail: <><Link to="/workspace/review" className="hover:text-brand hover:underline">pending of {o.reconciliation.needs_attention} items</Link>{stale}</>,
        }
      : { name: "Needs review", ...none },
  ];
}

function extractionRow(cfg: LlmConfig | undefined, isError: boolean): { value: string; ok: boolean; pending: boolean } {
  if (isError) return { value: "unknown", ok: false, pending: false };
  if (!cfg) return { value: "checking", ok: false, pending: true };
  if (cfg.status === "disabled") return { value: "rules only (LLM off)", ok: true, pending: false };
  if (cfg.status === "misconfigured") return { value: `LLM misconfigured: ${cfg.reason ?? "check .env"}`, ok: false, pending: false };
  return { value: `rules + LLM · ${cfg.provider}/${cfg.model}`, ok: true, pending: false };
}

export function OverviewPage() {
  const { patientId } = useWorkspace();
  const docs = useDocuments(patientId);
  const demo = useLoadDemo();
  const health = useHealth();
  const ready = useReadiness();
  const overview = useOverview(patientId);
  const o = overview.data;
  const list = docs.data ?? [];
  const stages = o ? buildStages(o) : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        description={<>Record bundle for patient <span className="font-mono text-ink">{patientId}</span>. Every number on this page is read from the backend.</>}
      />

      {overview.isError ? (
        <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
      ) : (
        <Card>
          <CardHeader className="flex-wrap items-start">
            <CardTitle>Evidence pipeline</CardTitle>
            {o && <RunAnalysisButton patientId={patientId} processedCount={o.documents.processed} hasResults={o.analysis.results_run !== null} />}
          </CardHeader>
          {!o ? (
            <div className="grid grid-cols-2 gap-px bg-line sm:grid-cols-3 lg:grid-cols-6" aria-busy="true">
              {Array.from({ length: 6 }, (_, i) => (
                <div key={i} className="bg-surface px-4 py-3.5">
                  <Skeleton className="h-3 w-16" />
                  <Skeleton className="mt-3 h-6 w-10" />
                </div>
              ))}
            </div>
          ) : (
            <ol className="grid grid-cols-2 gap-px bg-line sm:grid-cols-3 lg:grid-cols-6">
              {stages.map((s, i) => <PipelineStage key={s.name} stage={s} index={i} />)}
            </ol>
          )}
          {o && o.reconciliation.subjects > 0 && (
            <CardContent className="border-t border-line">
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">
                Evidence states · {o.reconciliation.subjects} reconciled subjects
              </h3>
              <EvidenceStateBar counts={o.reconciliation} total={o.reconciliation.subjects} />
            </CardContent>
          )}
          {o && (
            <CardContent className="border-t border-line">
              <AnalysisSummary status={o.analysis} />
            </CardContent>
          )}
        </Card>
      )}

      {/* minmax(0,1fr): let the table scroll inside its card instead of widening the page */}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Card>
          <CardHeader>
            <CardTitle>Documents</CardTitle>
            {list.length > 0 && <span className="text-[12px] text-ink-muted">{list.length} total</span>}
          </CardHeader>
          {docs.isPending ? (
            <CardContent className="space-y-2">
              {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-8" />)}
            </CardContent>
          ) : docs.isError ? (
            <CardContent><ErrorState error={docs.error} onRetry={() => docs.refetch()} /></CardContent>
          ) : list.length === 0 ? (
            <EmptyState
              icon={<FileText />}
              title="No documents for this patient yet"
              description={<>Load the synthetic demo bundle to see the pipeline on fictional records, or upload your own synthetic files on the <Link to="/workspace/documents" className="text-brand underline underline-offset-2">Documents</Link> screen.</>}
              action={
                <div className="space-y-3">
                  <Button onClick={() => demo.mutate(patientId)} loading={demo.isPending}>Load synthetic demo bundle</Button>
                  {demo.isError && <ErrorState error={demo.error} />}
                </div>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead className="border-b border-line text-[11px] uppercase tracking-[0.06em] text-ink-faint">
                  <tr>
                    <th className="px-5 py-2 font-medium">Document</th>
                    <th className="px-3 py-2 font-medium">Document date</th>
                    <th className="px-3 py-2 font-medium">Source file</th>
                    <th className="px-5 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {list.map((d) => (
                    <tr key={d.document_id} className="hover:bg-canvas">
                      <td className="px-5 py-2.5">
                        <Link to={`/workspace/documents?doc=${d.document_id}`} className="font-medium text-ink hover:text-brand hover:underline">
                          {d.document_type ?? <span className="text-ink-faint">Unknown type</span>}
                        </Link>
                        <div className="font-mono text-[11px] text-ink-faint">{d.document_id}</div>
                      </td>
                      <td className="px-3 py-2.5 tabular-nums text-ink-muted">{d.document_date ?? "–"}</td>
                      <td className="px-3 py-2.5 text-ink-muted">{d.filename}</td>
                      <td className="px-5 py-2.5">
                        <DocumentStatusBadge status={d.status} />
                        {d.error_code && <div className="mt-0.5 font-mono text-[11px] text-review">{d.error_code}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-2.5 text-[13px]">
              <SystemRow label="API" ok={health.isSuccess} value={health.data ? `online · v${health.data.version}` : health.isError ? failureText(health.error) : "checking"} />
              <SystemRow
                label="Database"
                ok={ready.data?.status === "ready"}
                value={ready.data ? (ready.data.status === "ready" ? `ready · schema v${ready.data.database.schema_version}` : ready.data.database.error ?? "not ready") : ready.isError ? failureText(ready.error) : "checking"}
              />
              <SystemRow label="Environment" ok={health.isSuccess} pending={!health.isSuccess} value={health.data?.environment ?? "unknown"} />
              <SystemRow label="Extraction" {...extractionRow(o?.llm, overview.isError)} />
            </dl>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function SystemRow({ label, value, ok, pending = false }: { label: string; value: string; ok: boolean; pending?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="flex items-center gap-1.5 text-right text-ink [&_svg]:size-3.5">
        {!pending && (ok ? <CheckCircle2 className="text-supported" /> : <XCircle className="text-review" />)}
        <span className={cn(pending && "text-ink-faint")}>{value}</span>
      </dd>
    </div>
  );
}
