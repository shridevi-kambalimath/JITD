import { Crosshair, Microscope } from "lucide-react";
import { Link } from "react-router";
import { type Claim, useAnalysisStatus, useClaims } from "@/api/analysis";
import { ErrorState } from "@/components/error-state";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { CATEGORY_LABELS, describeEventDate, formatEventDate, methodLabel } from "@/lib/claims";
import { PassageWithMark } from "@/components/passage";
import { cn } from "@/lib/utils";
import { evidenceHref } from "@/lib/verification";

/**
 * Claims extracted from one document. Each row links back to its exact source span: selecting it
 * highlights the quoted words in the extracted text. Shows what the record says, not whether it is right.
 */
export function ClaimsList({ patientId, documentId, selected, onSelect }: {
  patientId: string;
  documentId: string;
  selected: string | null;
  onSelect: (claimId: string | null) => void;
}) {
  const status = useAnalysisStatus(patientId);
  const claims = useClaims(patientId, documentId);
  const analysed = !!status.data?.results_run;

  return (
    <section aria-label="Extracted claims">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">
          Extracted claims{claims.data && claims.data.length > 0 && <span className="ml-1.5 tabular-nums">({claims.data.length})</span>}
        </h3>
        <span className="text-[11px] text-ink-faint">what the document states; not a judgement of correctness</span>
      </div>
      {claims.isPending || status.isPending ? (
        <div className="space-y-2" aria-busy="true">
          {Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-10" />)}
        </div>
      ) : claims.isError ? (
        <ErrorState error={claims.error} onRetry={() => claims.refetch()} />
      ) : claims.data.length === 0 ? (
        <p className="rounded-md border border-line bg-canvas px-4 py-4 text-[13px] text-ink-muted">
          {analysed
            ? status.data?.is_current
              ? "The analysis found no claims in this document."
              : "No stored claims for this document. It was added after the last analysis; run the analysis again from the Overview."
            : "This patient has not been analysed yet. Run the analysis from the Overview."}
        </p>
      ) : (
        <>
          {status.data && !status.data.is_current && (
            <p className="mb-2 text-[12px] text-conflicting">These claims may be stale: {status.data.stale_reason}</p>
          )}
          <ul className="divide-y divide-line rounded-md border border-line">
            {claims.data.map((c) => (
              <ClaimRow key={c.claim_id} claim={c} active={selected === c.claim_id} onToggle={() => onSelect(selected === c.claim_id ? null : c.claim_id)} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function ClaimRow({ claim: c, active, onToggle }: { claim: Claim; active: boolean; onToggle: () => void }) {
  const method = methodLabel(c);
  const assertion = c.attributes.assertion;
  return (
    <li className={cn("px-3 py-2.5 text-[13px]", active && "bg-brand-soft")} data-testid="claim-row">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Badge tone="neutral">{CATEGORY_LABELS[c.claim_type]}</Badge>
        <span className="font-medium text-ink">{c.entity}</span>
        {assertion && assertion !== "present" && <Badge tone="insufficient">{assertion}</Badge>}
        {c.verified === false && <Badge tone="review" title={`Failed: ${(c.failed_checks ?? []).join(", ")}`}>Failed verification</Badge>}
        <span className="ml-auto flex items-center gap-2">
          <span className="tabular-nums text-[12px] text-ink-muted" title={describeEventDate(c.event_date)}>
            {formatEventDate(c.event_date)}
          </span>
          <Badge tone={method.short === "LLM" ? "pending" : "brand"} title={method.detail}>{method.short}</Badge>
        </span>
      </div>
      <div className="mt-1 flex items-start gap-2">
        <p className="min-w-0 flex-1 break-words font-mono text-[12px] leading-relaxed text-ink-muted" data-testid="claim-passage">
          <PassageWithMark claim={c} />
        </p>
        <button
          type="button"
          onClick={onToggle}
          aria-pressed={active}
          className="inline-flex shrink-0 items-center gap-1 rounded-sm px-1.5 py-0.5 text-[12px] text-brand hover:bg-brand-soft [&_svg]:size-3.5"
        >
          <Crosshair aria-hidden />
          {active ? "Hide in text" : "Show in text"}
        </button>
        <Link to={evidenceHref(c.claim_id)} className="inline-flex shrink-0 items-center gap-1 rounded-sm px-1.5 py-0.5 text-[12px] text-brand hover:bg-brand-soft [&_svg]:size-3.5">
          <Microscope aria-hidden />Inspect
        </Link>
      </div>
      <p className="mt-0.5 font-mono text-[11px] text-ink-faint">
        {c.source.section} · {c.source.passage_id.split(":").pop()} · chars {c.source.entity_char_start}–{c.source.entity_char_end}
      </p>
    </li>
  );
}
