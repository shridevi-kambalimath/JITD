import { useHealth, useReadiness } from "@/api/health";
import { ApiError } from "@/lib/api";

export type BackendLevel = "ok" | "degraded" | "mismatch" | "incompatible" | "down" | "checking";

export const APP_VERSION = __APP_VERSION__;

export interface BackendStatus {
  level: BackendLevel;
  label: string;
  detail: string;
}

/**
 * One interpretation of backend health, shared by the status light and the explanatory banner.
 *
 * "down" means nothing answered. "incompatible" means a server answered but has no /api/health:
 * in practice an older MEDUSA-X build (before routes moved under /api) or another program on the port.
 */
export function useBackendStatus(): BackendStatus {
  const health = useHealth();
  const ready = useReadiness();
  const err = health.error ?? ready.error;

  if (err instanceof ApiError && !err.isNetworkError && err.status === 404) {
    return {
      level: "incompatible",
      label: "Incompatible backend",
      detail: "A server is answering on the API port, but it has no /api/health endpoint.",
    };
  }
  if (err) {
    return { level: "down", label: "Backend offline", detail: "The API is not reachable." };
  }
  if (ready.data && ready.data.status !== "ready") {
    return { level: "degraded", label: "Database not ready", detail: ready.data.database.error ?? "Schema version mismatch" };
  }
  if (health.data && health.data.version !== APP_VERSION) {
    return {
      level: "mismatch",
      label: "Version mismatch",
      detail: `This screen is v${APP_VERSION}; the backend answering on the API port is v${health.data.version}.`,
    };
  }
  if (health.data && ready.data) {
    return {
      level: "ok",
      label: "Backend online",
      detail: `v${health.data.version} · ${health.data.environment} · schema v${ready.data.database.schema_version}`,
    };
  }
  return { level: "checking", label: "Checking backend", detail: "" };
}
