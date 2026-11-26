import { ExternalLink, Microscope } from "lucide-react";
import { Link } from "react-router";
import type { Claim } from "@/api/analysis";
import { PassageWithMark } from "@/components/passage";
import { Badge } from "@/components/ui/badge";
import { methodLabel } from "@/lib/claims";
import { cn } from "@/lib/utils";
import { evidenceHref } from "@/lib/verification";

/** What one record states, quoted from its source, with a way back to the full document. */
export function claimSummary(c: Claim): string {
  const a = c.attributes as Record<string, unknown>;
  if (a.kind === "medication") {
    const action = String(a.action).replace("_", " ");
    return a.list_context === "other" ? action : `${action} · ${String(a.list_context)} list`;
  }
  if (a.kind === "diagnosis") return `documented as ${String(a.assertion)}`;
  if (a.kind === "allergy") return a.no_known_allergies ? "no known drug allergies" : `allergy: ${String(a.substance)}`;
  if (a.kind === "record_reference") return a.available_in_bundle ? "referenced, present in bundle" : "referenced, not in bundle";
  return c.claim_type.replace("_", " ");
}

export function SourceCard({ claim: c, label, className }: { claim: Claim; label?: string; className?: string }) {
  const method = methodLabel(c);
  const date = c.event_date.value ? `${c.event_date.approximate ? "~" : ""}${c.event_date.value}` : c.document_date ?? "undated";
  return (
    <article className={cn("flex min-w-0 flex-col rounded-md border border-line bg-surface", className)} data-testid="source-card">
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line bg-subtle px-3 py-2">
        {label && <span className="font-mono text-[11px] font-semibold text-ink-faint">{label}</span>}
        <span className="text-[13px] font-medium text-ink">{c.document_type}</span>
        <span className="font-mono text-[12px] tabular-nums text-ink-muted" title={c.event_date.value ? "event date stated in the record" : "document date"}>
          {date}
        </span>
        {c.verified === false && <Badge tone="review">Failed verification</Badge>}
        <Badge className="ml-auto" tone={method.short === "LLM" ? "pending" : "brand"} title={method.detail}>{method.short}</Badge>
      </header>
      <div className="flex-1 space-y-1.5 px-3 py-2.5">
        <p className="text-[12px] font-medium text-ink-muted">{claimSummary(c)}</p>
        <p className="break-words font-mono text-[12px] leading-relaxed text-ink" data-testid="source-passage">
          <PassageWithMark claim={c} />
        </p>
      </div>
      <footer className="flex items-center justify-between gap-2 border-t border-line px-3 py-1.5 text-[11px] text-ink-faint">
        <span className="font-mono">{c.source.section}</span>
        <span className="flex items-center gap-3">
        <Link to={evidenceHref(c.claim_id)} className="inline-flex items-center gap-1 text-[12px] text-brand hover:underline [&_svg]:size-3.5">
          <Microscope aria-hidden />Inspect
        </Link>
        <Link
          to={`/workspace/documents?doc=${encodeURIComponent(c.source.document_id)}&claim=${encodeURIComponent(c.claim_id)}`}
          className="inline-flex items-center gap-1 text-[12px] text-brand hover:underline [&_svg]:size-3.5"
        >
          Open document <ExternalLink aria-hidden />
        </Link>
        </span>
      </footer>
    </article>
  );
}
