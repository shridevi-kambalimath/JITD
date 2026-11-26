import { AlertTriangle, CheckCircle2, HelpCircle, ShieldAlert } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link } from "react-router";
import type { EvidenceState } from "@/components/status-badge";

/**
 * Part-to-whole of reconciled subjects by evidence state, most severe first.
 * Status fills from the dataviz reference status palette (critical, serious, warning, good); two of them sit below
 * 3:1 on white and warning/serious are close in hue, so state is never carried by color alone: every segment has a
 * hover/focus tooltip and the legend below it is the table view (icon + label + count + share).
 */
const ORDER: { state: EvidenceState; label: string; fill: string; icon: ReactNode }[] = [
  { state: "REVIEW_REQUIRED", label: "Review required", fill: "#dc3c3d", icon: <ShieldAlert /> },
  { state: "CONFLICTING_EVIDENCE", label: "Conflicting evidence", fill: "#f18a59", icon: <AlertTriangle /> },
  { state: "INSUFFICIENT_EVIDENCE", label: "Insufficient evidence", fill: "#fbb315", icon: <HelpCircle /> },
  { state: "EVIDENCE_SUPPORTED", label: "Evidence-supported", fill: "#0aac23", icon: <CheckCircle2 /> },
];

export function EvidenceStateBar({ counts, total }: { counts: Record<EvidenceState, number>; total: number }) {
  const [hover, setHover] = useState<EvidenceState | null>(null);
  const parts = ORDER.filter((o) => counts[o.state] > 0);
  const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);
  const active = ORDER.find((o) => o.state === hover);
  return (
    <figure className="space-y-3" aria-label="Evidence states of reconciled subjects">
      <div className="relative">
        <div className="flex h-4 w-full gap-[2px]" role="group" aria-label="Evidence state shares (each segment opens its list)" data-testid="state-bar">
          {parts.map((o, i) => (
            <Link
              key={o.state}
              to={o.state === "EVIDENCE_SUPPORTED" ? "/workspace/reconciliation" : "/workspace/review"}
              aria-label={`${o.label}: ${counts[o.state]} of ${total}`}
              onMouseEnter={() => setHover(o.state)} onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(o.state)} onBlur={() => setHover(null)}
              className={`block h-full min-w-[6px] outline-offset-2 ${i === 0 ? "rounded-l" : ""} ${i === parts.length - 1 ? "rounded-r" : ""}`}
              style={{ flexGrow: counts[o.state], flexBasis: 0, background: o.fill }}
              data-testid={`state-segment-${o.state}`}
            />
          ))}
        </div>
        {active && (
          <div role="tooltip" className="pointer-events-none absolute bottom-6 left-0 z-10 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12px] text-ink shadow-panel">
            {active.label}: <span className="font-semibold tabular-nums">{counts[active.state]}</span> of {total} ({pct(counts[active.state])}%)
          </div>
        )}
      </div>
      <figcaption>
        <ul className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px] sm:grid-cols-4" aria-label="Evidence state counts">
          {ORDER.map((o) => (
            <li key={o.state} className="flex items-center gap-1.5 text-ink [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-ink-muted" data-testid={`state-count-${o.state}`}>
              <span className="size-2.5 shrink-0 rounded-sm" style={{ background: o.fill }} aria-hidden />
              {o.icon}
              <span>{o.label}</span>
              <span className="ml-auto font-semibold tabular-nums">{counts[o.state]}</span>
              <span className="w-9 text-right tabular-nums text-ink-faint">{pct(counts[o.state])}%</span>
            </li>
          ))}
        </ul>
      </figcaption>
    </figure>
  );
}
