import { AlertTriangle, ArrowLeft, CheckCircle2, ExternalLink, MinusCircle, XCircle } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router";
import { type EvidenceView, useEvidence } from "@/api/analysis";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { EvidenceStateBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspace } from "@/context/workspace";
import { CATEGORY_LABELS, describeEventDate, formatEventDate, methodLabel } from "@/lib/claims";
import { capitalize } from "@/lib/reconciliation";
import { placementText } from "@/lib/timeline";
import { checkLabel } from "@/lib/verification";
import { cn } from "@/lib/utils";

export function EvidencePage() {
  const { claimId = "" } = useParams();
  const { patientId } = useWorkspace();
  const navigate = useNavigate();
  const q = useEvidence(patientId, claimId);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Evidence inspector"
        description="One claim against its source: the exact stored text, every verification check (re-run now), both dates, and where the claim is used. It shows what the record says, not whether it is clinically right."
        actions={
          <button type="button" onClick={() => navigate(-1)} className="inline-flex items-center gap-1 text-[13px] text-brand hover:underline [&_svg]:size-4">
            <ArrowLeft aria-hidden />Back
          </button>
        }
      />
      {q.isPending ? (
        <Card className="space-y-3 p-5" aria-busy="true"><Skeleton className="h-6 w-64" /><Skeleton className="h-40" /><Skeleton className="h-40" /></Card>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <Inspector view={q.data} />
      )}
    </div>
  );
}

function Inspector({ view: v }: { view: EvidenceView }) {
  const c = v.claim;
  const method = methodLabel(c);
  const hard = v.verification.checks.filter((k) => k.severity === "hard");
  const failedHard = hard.filter((k) => !k.passed);
  const a = c.source.entity_char_start - v.passage.char_start;
  const b = c.source.entity_char_end - v.passage.char_start;
  const markable = a >= 0 && b <= v.evidence_text.length && a < b;

  return (
    <>
      {v.verification_changed && (
        <p role="alert" className="flex gap-2 rounded-md border border-review-line bg-review-soft px-3 py-2 text-[13px] text-ink [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-review">
          <AlertTriangle />
          <span>The stored text no longer matches what the analysis verified. This claim {v.verified_at_analysis ? "passed" : "failed"} verification during the analysis but {v.verification.verified ? "passes" : "fails"} now. Re-run the analysis.</span>
        </p>
      )}

      <Card>
        <CardHeader className="flex-wrap items-start">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="neutral">{CATEGORY_LABELS[c.claim_type]}</Badge>
              <h2 className="text-[17px] font-semibold text-ink">{capitalize(c.entity)}</h2>
              {c.attributes.assertion && c.attributes.assertion !== "present" && <Badge tone="insufficient">{String(c.attributes.assertion)}</Badge>}
              <Badge tone={method.short === "LLM" ? "pending" : "brand"} title={method.detail}>{method.short}</Badge>
            </div>
            <p className="font-mono text-[11px] text-ink-faint">{c.claim_id} · {c.extraction_method}</p>
          </div>
          <div data-testid="verification-status">
            {v.verification.verified ? (
              <Badge tone="supported"><CheckCircle2 />Verified: {hard.length} of {hard.length} hard checks pass</Badge>
            ) : (
              <Badge tone="review"><XCircle />Failed verification: {failedHard.length} hard check{failedHard.length === 1 ? "" : "s"}</Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <section aria-label="Source" className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">Source</h3>
              <Link to={`/workspace/documents?doc=${encodeURIComponent(v.document.document_id)}&claim=${encodeURIComponent(c.claim_id)}`}
                className="inline-flex items-center gap-1 text-[12px] text-brand hover:underline [&_svg]:size-3.5">
                {v.document.document_type ?? v.document.filename} · {v.document.filename} <ExternalLink aria-hidden />
              </Link>
            </div>
            <pre className="whitespace-pre-wrap break-words rounded-md border border-line bg-canvas px-4 py-3 font-mono text-[12px] leading-relaxed" data-testid="evidence-context">
              <span className="text-ink-faint">{v.context_before}</span>
              <span className="rounded-sm bg-brand-soft text-ink ring-1 ring-brand-line" data-testid="evidence-passage">
                {markable ? (
                  <>
                    {v.evidence_text.slice(0, a)}
                    <mark className="bg-transparent font-bold text-ink underline decoration-brand decoration-2 underline-offset-2" data-testid="evidence-entity">{v.evidence_text.slice(a, b)}</mark>
                    {v.evidence_text.slice(b)}
                  </>
                ) : v.evidence_text}
              </span>
              <span className="text-ink-faint">{v.context_after}</span>
            </pre>
            <dl className="grid gap-x-6 gap-y-1.5 text-[13px] sm:grid-cols-2" aria-label="Claim facts">
              <Fact k="Section" v={c.source.section} />
              <Fact k="Passage" v={`${v.passage.passage_id.split(":").pop()} · chars ${v.passage.char_start}–${v.passage.char_end}`} mono />
              <Fact k="Quoted words" v={`“${c.surface}” · chars ${c.source.entity_char_start}–${c.source.entity_char_end}`} mono />
              <Fact k="Document date" v={c.document_date ?? "not stated"} mono />
              <Fact k="Event date" v={formatEventDate(c.event_date)} mono title={describeEventDate(c.event_date)} />
              <Fact k="Event date basis" v={describeEventDate(c.event_date) || "none"} />
            </dl>
          </section>

          <section aria-label="Verification checks" className="min-w-0">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">Verification checks</h3>
            <ul className="divide-y divide-line rounded-md border border-line">
              {v.verification.checks.map((k) => (
                <li key={k.check_id} className="flex gap-2.5 px-3 py-2 text-[13px] [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0" data-testid="check">
                  {k.passed ? <CheckCircle2 className="text-supported" /> : k.severity === "advisory" ? <MinusCircle className="text-conflicting" /> : <XCircle className="text-review" />}
                  <div className="min-w-0">
                    <p className="text-ink">{checkLabel(k.check_id)}{!k.passed && <span className="sr-only"> (failed)</span>}</p>
                    <p className="break-words text-[12px] text-ink-muted">{k.detail}</p>
                  </div>
                  <span className="ml-auto shrink-0 font-mono text-[10px] text-ink-faint">{k.check_id.split("_")[0]}</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-ink-faint">Hard checks decide whether a claim can be used; the advisory check never does.</p>
          </section>
        </CardContent>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>On the timeline</CardTitle></CardHeader>
          <CardContent className="text-[13px]" data-testid="evidence-timeline">
            {v.timeline_entry ? (
              <div className="space-y-1">
                <p><span className="font-mono font-semibold text-ink">{v.timeline_entry.when}</span> · {v.timeline_entry.label}</p>
                <p className="text-[12px] text-ink-muted">{placementText(v.timeline_entry)}</p>
                <Link to="/workspace/timeline" className="text-[12px] text-brand hover:underline">Open the timeline</Link>
              </div>
            ) : (
              <p className="text-ink-muted">Not on the timeline: the claim does not pass verification.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Used in reconciliation</CardTitle></CardHeader>
          <CardContent className="text-[13px]">
            {v.related_findings.length === 0 ? (
              <p className="text-ink-muted">{c.extraction_method.startsWith("llm:") ? "LLM claims are shown as evidence but not reconciled." : "Not part of any reconciliation item."}</p>
            ) : (
              <ul className="space-y-2" aria-label="Related findings">
                {v.related_findings.map((f) => (
                  <li key={f.finding_id} className="flex flex-wrap items-center gap-2">
                    <Link to={`/workspace/reconciliation?finding=${encodeURIComponent(f.finding_id)}`} className="font-medium text-brand hover:underline">{capitalize(f.subject)}</Link>
                    {f.state && <EvidenceStateBadge state={f.state} />}
                    {f.gate_rule && <span className="font-mono text-[11px] text-ink-faint">{f.gate_rule}</span>}
                    <span className="text-[12px] text-ink-muted">({f.role})</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function Fact({ k, v, mono, title }: { k: string; v: string; mono?: boolean; title?: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-line py-1 sm:block sm:border-0 sm:py-0">
      <dt className="text-[12px] text-ink-muted">{k}</dt>
      <dd className={cn("text-right text-ink sm:text-left", mono && "font-mono text-[12px]")} title={title}>{v}</dd>
    </div>
  );
}
