import { AlertTriangle, Info, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import type { AnalysisRun, AnalysisStatus } from "@/api/analysis";
import { formatDateTime } from "@/lib/utils";

const LLM_TEXT: Record<AnalysisRun["llm_status"], string> = {
  disabled: "LLM off (rules only)",
  misconfigured: "LLM misconfigured, not used",
  ok: "LLM ok",
  partial: "LLM partly failed",
  failed: "LLM failed, not used",
};

/** One-line account of the run behind the stored claims, plus anything the user must know about it. */
export function AnalysisSummary({ status }: { status: AnalysisStatus }) {
  const { latest_run: latest, results_run: results } = status;
  if (!latest) {
    return <p className="text-[12px] text-ink-muted">No analysis has been run for this patient yet.</p>;
  }
  const llm = results?.stats.llm;
  return (
    <div className="space-y-2 text-[12px]" data-testid="analysis-summary">
      {results && (
        <p className="text-ink-muted">
          Results from <span className="font-mono text-ink">{results.run_id}</span> · {formatDateTime(results.finished_at ?? results.started_at)} · extractor{" "}
          <span className="font-mono text-ink">{results.extractor}</span> · {LLM_TEXT[results.llm_status]}
          {llm && llm.accepted !== undefined && (
            <> · LLM proposals: {llm.accepted} kept, {llm.agreed_with_rules ?? 0} matched rules, {llm.rejected ?? 0} rejected (quote not in source)</>
          )}
        </p>
      )}
      {latest.status === "failed" && (
        <Note tone="review" icon={<XCircle />}>
          The latest run ({latest.run_id}) failed: {latest.error ?? "unknown error"}.{" "}
          {results ? "The results below are from the previous successful run." : "No results are stored."}
        </Note>
      )}
      {results && !status.is_current && (
        <Note tone="conflicting" icon={<AlertTriangle />}>
          Stale: {status.stale_reason}
        </Note>
      )}
      {results && (results.llm_status === "failed" || results.llm_status === "partial" || results.llm_status === "misconfigured") && (
        <Note tone="conflicting" icon={<Info />}>
          {results.llm_status === "partial" ? "LLM extraction failed for some documents" : "LLM extraction was not used"}
          {results.llm_error ? ` (${results.llm_error})` : ""}. Rule-based claims are complete; LLM additions are missing where it failed.
        </Note>
      )}
    </div>
  );
}

function Note({ tone, icon, children }: { tone: "review" | "conflicting"; icon: ReactNode; children: ReactNode }) {
  const cls = tone === "review" ? "border-review-line bg-review-soft [&_svg]:text-review" : "border-conflicting-line bg-conflicting-soft [&_svg]:text-conflicting";
  return (
    <p role="status" className={`flex gap-2 rounded-md border px-3 py-2 text-ink [&_svg]:mt-0.5 [&_svg]:size-3.5 [&_svg]:shrink-0 ${cls}`}>
      {icon}
      <span>{children}</span>
    </p>
  );
}
