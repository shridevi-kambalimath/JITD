import { type BackendLevel, useBackendStatus } from "@/api/backend-status";
import { cn } from "@/lib/utils";

const DOT: Record<BackendLevel, string> = {
  ok: "bg-supported",
  degraded: "bg-conflicting",
  mismatch: "bg-conflicting",
  incompatible: "bg-review",
  down: "bg-review",
  checking: "bg-ink-faint animate-pulse",
};

/** Live backend status from /api/health and /api/health/ready. */
export function HealthIndicator({ className }: { className?: string }) {
  const { level, label, detail } = useBackendStatus();
  return (
    <div className={cn("flex items-center gap-2 text-[12px]", className)} title={detail} data-level={level}>
      <span className={cn("size-2 rounded-full", DOT[level])} aria-hidden />
      <span className="text-ink-muted">{label}</span>
    </div>
  );
}
