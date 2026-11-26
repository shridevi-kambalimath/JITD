import { AlertTriangle, FileText, Microscope, Search as SearchIcon } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import type { ClaimRef, SearchResponse, SearchScope } from "@/api/search";
import { useSearch } from "@/api/search";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { EvidenceStateBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkspace } from "@/context/workspace";
import { CATEGORY_LABELS, methodLabel } from "@/lib/claims";
import { capitalize, ISSUE_LABELS } from "@/lib/reconciliation";
import { placementText } from "@/lib/timeline";
import { cn } from "@/lib/utils";
import { evidenceHref } from "@/lib/verification";

type Tab = "all" | SearchScope;
const TABS: { id: Tab; label: string }[] = [
  { id: "all", label: "All" },
  { id: "passages", label: "Passages" },
  { id: "claims", label: "Claims" },
  { id: "timeline", label: "Timeline" },
  { id: "reconciliation", label: "Reconciliation" },
];
const PREVIEW = 5;
const EXAMPLES = ["metformin", "warfarin", "allergies", "Hb", "kidney"];

export function SearchPage() {
  const { patientId } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "all") as Tab;
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);
  const search = useSearch(patientId, q);

  const go = (next: { q?: string; tab?: Tab }) => {
    const nq = next.q ?? q;
    const nt = next.tab ?? tab;
    setParams({ ...(nq ? { q: nq } : {}), ...(nt !== "all" ? { tab: nt } : {}) });
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = draft.trim();
    if (v) go({ q: v, tab: "all" });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Evidence Search"
        description="Find where the records mention something: passages ranked by keyword relevance (BM25), and the claims, timeline entries and reconciliation items they lead to. Brand and generic drug names and common lab abbreviations are matched both ways. Search shows where the records say something; it does not answer clinical questions."
      />
      <form onSubmit={submit} role="search" className="flex flex-wrap items-center gap-2">
        <label className="relative block min-w-0 flex-1 sm:max-w-xl">
          <span className="sr-only">Search the records</span>
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint" aria-hidden />
          <input type="search" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={200} autoFocus
            placeholder="e.g. metformin, allergies, Hb"
            className="h-10 w-full rounded-md border border-line-strong bg-surface pl-9 pr-3 text-[14px] text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none" />
        </label>
        <Button type="submit" disabled={!draft.trim()}>Search</Button>
      </form>

      {!q ? (
        <Card>
          <EmptyState icon={<SearchIcon />} title="Search the patient's records"
            description="Every result links to its exact source. Try one of these:"
            action={
              <div className="flex flex-wrap justify-center gap-2">
                {EXAMPLES.map((ex) => (
                  <button key={ex} type="button" onClick={() => go({ q: ex, tab: "all" })}
                    className="rounded-md border border-line px-2.5 py-1 text-[13px] text-brand hover:bg-brand-soft">{ex}</button>
                ))}
              </div>
            } />
        </Card>
      ) : search.isPending ? (
        <Card className="space-y-3 p-5" aria-busy="true">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-14" />)}</Card>
      ) : search.isError ? (
        <ErrorState error={search.error} onRetry={() => search.refetch()} />
      ) : (
        <Results data={search.data} tab={tab} onTab={(t) => go({ tab: t })} fetching={search.isFetching} />
      )}
    </div>
  );
}

function Results({ data, tab, onTab, fetching }: { data: SearchResponse; tab: Tab; onTab: (t: Tab) => void; fetching: boolean }) {
  const total = data.counts.passages;
  const show = (scope: SearchScope) => tab === "all" || tab === scope;
  const limit = tab === "all" ? PREVIEW : Infinity;
  return (
    <div className={cn("space-y-4", fetching && "opacity-60")}>
      {!data.is_current && data.results_run_id && (
        <p role="status" className="flex gap-2 rounded-md border border-conflicting-line bg-conflicting-soft px-3 py-2 text-[13px] text-ink [&_svg]:mt-0.5 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-conflicting">
          <AlertTriangle /><span>Results come from an analysis that is out of date. Re-run it to include recent document changes.</span>
        </p>
      )}
      <p className="text-[13px] text-ink-muted" data-testid="search-summary">
        {total} passage{total === 1 ? "" : "s"} for <span className="font-medium text-ink">“{data.query}”</span>
        {data.expanded.length > 0 && <> · also matched <span className="font-mono text-ink">{data.expanded.join(", ")}</span></>}
      </p>
      {data.note && <p className="text-[13px] text-ink-muted" data-testid="search-note">{data.note}</p>}

      <div role="tablist" aria-label="Result type" className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => {
          const count = t.id === "all" ? null : data.counts[t.id];
          return (
            <button key={t.id} role="tab" type="button" aria-selected={tab === t.id} onClick={() => onTab(t.id)}
              className={cn("-mb-px border-b-2 px-3 py-2 text-[13px] font-medium", tab === t.id ? "border-brand text-brand" : "border-transparent text-ink-muted hover:text-ink")}>
              {t.label}{count !== null && <span className="ml-1 tabular-nums text-ink-faint">{count}</span>}
            </button>
          );
        })}
      </div>

      {show("passages") && data.counts.passages > 0 && (
        <Section title="Passages" count={data.counts.passages} limit={limit} onMore={() => onTab("passages")}>
          {data.passages.slice(0, limit).map((p) => (
            <li key={p.passage_id} className="space-y-1.5 px-4 py-3" data-testid="passage-hit">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-muted">
                <span className="font-medium text-ink">{p.document_type}</span>
                <span className="font-mono tabular-nums">{p.document_date ?? "undated"}</span>
                <span className={cn("font-mono", p.section_matched && "rounded-sm bg-brand-soft px-1 text-brand")}>{p.section}</span>
                <span className="ml-auto font-mono text-[11px] text-ink-faint" title="BM25 relevance score">score {p.score.toFixed(2)}</span>
              </div>
              <p className="font-mono text-[13px] leading-relaxed text-ink" data-testid="passage-text"><Highlight text={p.text} spans={p.matches} /></p>
              <div className="flex flex-wrap items-center gap-2">
                {p.claims.map((c) => <ClaimChip key={c.claim_id} claim={c} />)}
                <Link to={`/workspace/documents?doc=${encodeURIComponent(p.document_id)}${p.claims[0] ? `&claim=${encodeURIComponent(p.claims[0].claim_id)}` : ""}`}
                  className="ml-auto inline-flex items-center gap-1 text-[12px] text-brand hover:underline [&_svg]:size-3.5"><FileText aria-hidden />Open document</Link>
              </div>
            </li>
          ))}
        </Section>
      )}

      {show("claims") && data.counts.claims > 0 && (
        <Section title="Claims" count={data.counts.claims} limit={limit} onMore={() => onTab("claims")}>
          {data.claims.slice(0, limit).map((c) => (
            <li key={c.claim_id} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-3 text-[13px]" data-testid="claim-hit">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{CATEGORY_LABELS[c.category as keyof typeof CATEGORY_LABELS] ?? c.category}</Badge>
                  <span className="font-medium text-ink">{c.entity}</span>
                  {c.surface.toLowerCase() !== c.entity && <span className="text-[12px] text-ink-muted">written as “{c.surface}”</span>}
                  <Badge tone={methodLabel(c).short === "LLM" ? "pending" : "brand"}>{methodLabel(c).short}</Badge>
                  {c.verified === false && <Badge tone="review">Failed verification</Badge>}
                </div>
                <p className="text-[12px] text-ink-muted">{c.document_type} · {c.document_date ?? "undated"}{c.event_when ? ` · event ${c.event_when}` : ""}</p>
                <p className="font-mono text-[12px] text-ink-muted">{c.passage_text}</p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1.5">
                {c.finding?.state && <EvidenceStateBadge state={c.finding.state} />}
                <InspectLink claimId={c.claim_id} />
              </div>
            </li>
          ))}
        </Section>
      )}

      {show("timeline") && data.counts.timeline > 0 && (
        <Section title="Timeline entries" count={data.counts.timeline} limit={limit} onMore={() => onTab("timeline")}>
          {data.timeline.slice(0, limit).map((t) => (
            <li key={t.claim_id} className="flex flex-wrap items-start gap-3 px-4 py-3 text-[13px]" data-testid="timeline-hit">
              <span className="w-28 shrink-0 font-mono font-semibold tabular-nums text-ink">{t.when}</span>
              <div className="min-w-0 flex-1">
                <p className="text-ink">{t.label}</p>
                <p className="text-[12px] text-ink-muted">{placementText(t)} · {t.document_type}</p>
              </div>
              <InspectLink claimId={t.claim_id} />
            </li>
          ))}
        </Section>
      )}

      {show("reconciliation") && data.counts.reconciliation > 0 && (
        <Section title="Reconciliation items" count={data.counts.reconciliation} limit={limit} onMore={() => onTab("reconciliation")}>
          {data.reconciliation.slice(0, limit).map((f) => (
            <li key={f.finding_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-[13px]" data-testid="finding-hit">
              <Link to={`/workspace/reconciliation?finding=${encodeURIComponent(f.finding_id)}`} className="font-medium text-brand hover:underline">{capitalize(f.subject)}</Link>
              {f.state && <EvidenceStateBadge state={f.state} />}
              {f.gate_rule && <span className="font-mono text-[11px] text-ink-faint">{f.gate_rule}</span>}
              <span className="text-[12px] text-ink-muted">{f.issue_types.map((i) => ISSUE_LABELS[i] ?? i).join(" · ") || "no discrepancy found"}</span>
            </li>
          ))}
        </Section>
      )}

      {tab !== "all" && data.counts[tab] === 0 && !data.note && (
        <p className="text-[13px] text-ink-muted">No {TABS.find((t) => t.id === tab)!.label.toLowerCase()} results for this search.</p>
      )}
    </div>
  );
}

function Section({ title, count, limit, onMore, children }: { title: string; count: number; limit: number; onMore: () => void; children: ReactNode }) {
  return (
    <Card>
      <div className="flex items-baseline justify-between border-b border-line px-4 py-2.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-faint">{title}</h2>
        <span className="text-[12px] tabular-nums text-ink-faint">{count}</span>
      </div>
      <ul className="divide-y divide-line" aria-label={title}>{children}</ul>
      {count > limit && (
        <button type="button" onClick={onMore} className="w-full border-t border-line px-4 py-2 text-left text-[12px] text-brand hover:bg-canvas">
          Show all {count} {title.toLowerCase()}
        </button>
      )}
    </Card>
  );
}

function Highlight({ text, spans }: { text: string; spans: [number, number][] }) {
  const out: ReactNode[] = [];
  let at = 0;
  for (const [a, b] of [...spans].sort((x, y) => x[0] - y[0])) {
    if (a < at || b > text.length) continue;
    out.push(text.slice(at, a), <mark key={a} className="rounded-sm bg-brand-soft px-0.5 font-semibold text-ink">{text.slice(a, b)}</mark>);
    at = b;
  }
  out.push(text.slice(at));
  return <>{out}</>;
}

function ClaimChip({ claim: c }: { claim: ClaimRef }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-line bg-canvas px-2 py-0.5 text-[12px]" data-testid="claim-chip">
      <span className="text-ink">{c.entity}</span>
      {c.finding?.state && <EvidenceStateBadge state={c.finding.state} />}
      {c.verified === false && <Badge tone="review">Failed verification</Badge>}
      <Link to={evidenceHref(c.claim_id)} className="text-brand hover:underline" aria-label={`Inspect ${c.entity}`}><Microscope className="size-3.5" aria-hidden /></Link>
    </span>
  );
}

function InspectLink({ claimId }: { claimId: string }) {
  return (
    <Link to={evidenceHref(claimId)} className="inline-flex shrink-0 items-center gap-1 text-[12px] text-brand hover:underline [&_svg]:size-3.5">
      <Microscope aria-hidden />Inspect evidence
    </Link>
  );
}
