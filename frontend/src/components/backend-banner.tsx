import { useQueryClient } from "@tanstack/react-query";
import { DatabaseZap, PlugZap, ServerCrash } from "lucide-react";
import { useEffect, useRef } from "react";
import { APP_VERSION, type BackendLevel, useBackendStatus } from "@/api/backend-status";
import { useHealth } from "@/api/health";
import { cn } from "@/lib/utils";

/**
 * Explains a backend problem once, at the top of the page, with the fix.
 * Individual panels still show their own errors; this says why they are all failing.
 */
export function BackendBanner({ className }: { className?: string }) {
  const { level, detail } = useBackendStatus();
  const health = useHealth();
  useRefreshOnRecovery(level);
  if (level === "degraded") {
    return (
      <div role="status" className={cn("border-b border-review-line bg-review-soft", className)}>
        <div className="flex items-start gap-3 px-5 py-3 text-[13px] lg:px-8">
          <DatabaseZap className="mt-0.5 size-4 shrink-0 text-review" aria-hidden />
          <div className="min-w-0">
            <p className="font-medium text-review">The database is not ready: {detail}</p>
            <p className="mt-0.5 text-ink">
              If the database file was deleted, your next action creates an empty one; then load the demo bundle again. If this
              persists, restart the backend. This page reconnects automatically.
            </p>
          </div>
        </div>
      </div>
    );
  }
  if (level === "mismatch") {
    return (
      <div role="status" className={cn("border-b border-conflicting-line bg-conflicting-soft", className)}>
        <div className="flex items-start gap-3 px-5 py-3 text-[13px] lg:px-8">
          <PlugZap className="mt-0.5 size-4 shrink-0 text-conflicting" aria-hidden />
          <div className="min-w-0">
            <p className="font-medium text-conflicting">Frontend and backend are from different builds</p>
            <p className="mt-0.5 text-ink">
              This screen is <strong>v{APP_VERSION}</strong>, the backend is <strong>v{health.data?.version}</strong>. A server from another
              project folder is probably still running. Stop all MEDUSA-X terminals, then start both from the same folder
              (VS Code: <kbd className="font-mono text-[12px]">Ctrl+Shift+B</kbd>).
            </p>
          </div>
        </div>
      </div>
    );
  }
  if (level !== "incompatible" && level !== "down") return null;

  const incompatible = level === "incompatible";
  return (
    <div role="status" className={cn("border-b border-review-line bg-review-soft", className)}>
      <div className="flex items-start gap-3 px-5 py-3 text-[13px] lg:px-8">
        {incompatible ? <PlugZap className="mt-0.5 size-4 shrink-0 text-review" aria-hidden /> : <ServerCrash className="mt-0.5 size-4 shrink-0 text-review" aria-hidden />}
        <div className="min-w-0">
          <p className="font-medium text-review">
            {incompatible ? "The server on the API port is not this version of MEDUSA-X" : "The MEDUSA-X backend is not running"}
          </p>
          <p className="mt-0.5 text-ink">
            {incompatible ? (
              <>
                Something answered, but it has no <code className="font-mono text-[12px]">/api/health</code> endpoint.
                Usually an older MEDUSA-X backend (stage 1 or 2) is still running. Stop it (<kbd className="font-mono text-[12px]">Ctrl+C</kbd> in its
                terminal), then start the backend from <strong>this</strong> project: <code className="font-mono text-[12px]">cd backend</code>,{" "}
                <code className="font-mono text-[12px]">python -m medusa</code>.
              </>
            ) : (
              <>
                Start it in a second terminal: <code className="font-mono text-[12px]">cd backend</code>, then{" "}
                <code className="font-mono text-[12px]">python -m medusa</code>. This page reconnects automatically.
              </>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}

/** When the backend comes back (offline, wrong server or database problem, then healthy), refetch everything once,
 * so panels that showed errors while it was away recover without a page reload. */
function useRefreshOnRecovery(level: BackendLevel) {
  const qc = useQueryClient();
  const previous = useRef<BackendLevel>(level);
  useEffect(() => {
    const was = previous.current;
    previous.current = level;
    if (level === "ok" && (was === "down" || was === "incompatible" || was === "degraded")) {
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "health" });
    }
  }, [level, qc]);
}
