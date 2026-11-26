import { Play, RefreshCw } from "lucide-react";
import { useRunAnalysis } from "@/api/analysis";
import { ErrorState } from "@/components/error-state";
import { Button } from "@/components/ui/button";

/**
 * Starts segmentation and claim extraction for the patient's processed documents.
 * Disabled (with the reason shown) when there is nothing to analyse.
 */
export function RunAnalysisButton({ patientId, processedCount, hasResults }: { patientId: string; processedCount: number; hasResults: boolean }) {
  const run = useRunAnalysis();
  const nothing = processedCount === 0;
  return (
    <div className="flex flex-col items-end gap-1.5">
      <Button
        size="sm"
        variant={hasResults ? "secondary" : "primary"}
        onClick={() => run.mutate(patientId)}
        loading={run.isPending}
        disabled={nothing}
        title={nothing ? "No processed documents to analyse" : undefined}
      >
        {!run.isPending && (hasResults ? <RefreshCw /> : <Play />)}
        {run.isPending ? "Analysing…" : hasResults ? "Re-run analysis" : "Run analysis"}
      </Button>
      {nothing && <span className="text-[11px] text-ink-faint">Needs at least one processed document</span>}
      {run.isError && <ErrorState className="mt-1 w-full max-w-sm text-left" error={run.error} />}
    </div>
  );
}
