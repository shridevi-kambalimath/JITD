import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

/** Mirrors backend/medusa/schemas/common.py */
export interface HealthResponse {
  status: "ok";
  app: string;
  version: string;
  environment: string;
  max_upload_bytes: number;
}

export interface DatabaseCheck {
  path: string;
  reachable: boolean;
  schema_version: number;
  expected_version: number;
  error: string | null;
}

export interface ReadinessResponse {
  status: "ready" | "unavailable";
  database: DatabaseCheck;
}

export const getHealth = () => apiRequest<HealthResponse>("/health");
export const getReadiness = () => apiRequest<ReadinessResponse>("/health/ready", { allowStatus: [503] });

export const healthKeys = { health: ["health"] as const, readiness: ["health", "ready"] as const };

/** Poll slowly while healthy, every few seconds while not, so the app notices a restarted backend quickly. */
export const HEALTHY_POLL_MS = 30_000;
export const RECOVERY_POLL_MS = 3_000;

export function useHealth() {
  return useQuery({
    queryKey: healthKeys.health,
    queryFn: getHealth,
    refetchInterval: (q) => (q.state.status === "error" ? RECOVERY_POLL_MS : HEALTHY_POLL_MS),
    retry: false,
  });
}

export function useReadiness() {
  return useQuery({
    queryKey: healthKeys.readiness,
    queryFn: getReadiness,
    refetchInterval: (q) => (q.state.status === "error" || q.state.data?.status !== "ready" ? RECOVERY_POLL_MS : HEALTHY_POLL_MS / 2),
    retry: false,
  });
}
