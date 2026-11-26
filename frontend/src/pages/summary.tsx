import { AlertTriangle, Download, Microscope, ScrollText } from "lucide-react";
import { Link } from "react-router";
import { summaryMarkdownUrl, type SummaryLine, useSummary } from "@/api/workspace";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { EvidenceStateBadge } from "@/components/status-badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspace } from "@/context/workspace";
import { buttonVariants } from "@/components/ui/button";
import { formatDateTime } from "@/lib/utils";
import { evidenceHref } from "@/lib/verification";

export function SummaryPage() {
  const { patientId } = useWorkspace();
  const q = useSummary(patientId);
  const s = q.data;
  const analysed = !!s?.results_run_id;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Evidence Summary"
        description="A reconstruction assembled from templates over verified claims. Every line cites the passages it restates; conflicting and insufficient items keep their label. Nothing here is generated free text."
        actions={analysed ? (
          <a href={summaryMarkdownUrl(patientId)} download className={buttonVariants({ variant: "secondary", size: "sm" })}>
            <Download aria-hidden />Download Markdown
          </a>
        ) : undefined}
      />
      {q.isPending ? (
        <Card className="space-y-3 p-5" aria-busy="true">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-10" />)}</Card>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !analysed ? (
        <Card>
          <EmptyState icon={<ScrollText />} title="No summary yet"
            description={<>The summary is built from analysed, verified claims. Run the analysis from the <Link to="/workspace/overview" className="text-brand underline underline-offset-2">Overview</Link> first.</>} />
        </Card>
      ) : (
        <>
          <p role="note" className="rounded-md border border-line bg-canvas px-4 py-3 text-[13px] text-ink" data-testid="disclaimer">{s!.disclaimer}</p>
          {!s!.is_current && (
            <p role="status" className="flex gap-2 rounded-md border border-conflicting-line bg-conflicting-soft px-3 py-2 text-[13px] text-ink [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-conflicting">
              <AlertTriangle /><span>Out of date: {s!.stale_reason}</span>
            </p>
          )}
          <p className="text-[12px] text-ink-faint">Analysis run <span className="font-mono">{s!.results_run_id}</span> · generated {formatDateTime(s!.generated_at)}</p>
          {s!.sections.map((sec) => (
            <Card key={sec.key} aria-label={sec.title}>
              <div className="border-b border-line px-5 py-3">
                <h2 className="text-[15px] font-semibold text-ink">{sec.title}</h2>
                <p className="text-[12px] text-ink-muted">{sec.description}</p>
              </div>
              <CardContent>
                {sec.lines.length === 0 ? (
                  <p className="text-[13px] text-ink-muted">None identified by the rules.</p>
                ) : (
                  <ul className="space-y-2.5" data-testid={`section-${sec.key}`}>
                    {sec.lines.map((ln, i) => <Line key={i} line={ln} />)}
                  </ul>
                )}
              </CardContent>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}

function Line({ line: ln }: { line: SummaryLine }) {
  const text = ln.text.replace(/^\[(Review required|Conflicting evidence|Insufficient evidence)\] /, "");
  return (
    <li className="text-[13px] text-ink" data-testid="summary-line">
      <div className="flex flex-wrap items-start gap-2">
        {ln.state && ln.state !== "EVIDENCE_SUPPORTED" && <EvidenceStateBadge state={ln.state} />}
        <span className="min-w-0 flex-1">{text}</span>
      </div>
      {ln.citations.length > 0 && (
        <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px]" aria-label="Sources">
          {ln.citations.map((c) => (
            <Link key={c.claim_id} to={evidenceHref(c.claim_id)} className="inline-flex items-center gap-1 text-brand hover:underline [&_svg]:size-3">
              <Microscope aria-hidden />{c.label}
            </Link>
          ))}
        </p>
      )}
    </li>
  );
}
