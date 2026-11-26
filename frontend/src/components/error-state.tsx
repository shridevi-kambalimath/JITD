import { AlertOctagon, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Shows what failed, the stable error code and the request id to find it in the backend log. */
export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const api = error instanceof ApiError ? error : null;
  const message = api?.message ?? (error instanceof Error ? error.message : "Something went wrong.");
  return (
    <div role="alert" className={cn("flex items-start gap-3 rounded-md border border-review-line bg-review-soft px-4 py-3", className)}>
      <AlertOctagon className="mt-0.5 size-4 shrink-0 text-review" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-review">{api?.isNetworkError ? "Backend unreachable" : "Request failed"}</p>
        <p className="mt-0.5 text-[13px] text-ink">{message}</p>
        {api && (
          <p className="mt-1 font-mono text-[11px] text-ink-muted">
            {api.code}
            {api.requestId ? ` · request ${api.requestId}` : ""}
          </p>
        )}
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          <RotateCw />
          Retry
        </Button>
      )}
    </div>
  );
}
