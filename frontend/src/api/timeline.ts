import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { analysisKeys, type ClaimCategory, type DateValue } from "@/api/analysis";
import { apiRequest } from "@/lib/api";

/** Mirrors backend/medusa/schemas/timeline.py */
export type OrderingBasis = "event_date" | "document_date" | "undated";

export interface TimelineEntry {
  claim_id: string;
  category: ClaimCategory;
  label: string;
  entity: string;
  quote: string;
  assertion: string | null;
  extraction_method: string;
  ordering_basis: OrderingBasis;
  when: string;
  when_precision: "day" | "month" | "year" | "unknown";
  when_approximate: boolean;
  event_date: DateValue;
  document_date: string | null;
  document_id: string;
  document_type: string;
  section: string;
  passage_id: string;
}

export interface TimelineResponse {
  patient_id: string;
  results_run_id: string | null;
  is_current: boolean;
  stale_reason: string | null;
  total: number;
  excluded_unverified: number;
  by_basis: Partial<Record<OrderingBasis, number>>;
  by_category: Partial<Record<ClaimCategory, number>>;
  entries: TimelineEntry[];
}

export interface TimelineFilters {
  category?: ClaimCategory | null;
  q?: string;
}

export function getTimeline(patientId: string, f: TimelineFilters = {}) {
  const params = new URLSearchParams();
  if (f.category) params.set("category", f.category);
  if (f.q?.trim()) params.set("q", f.q.trim());
  const qs = params.toString();
  return apiRequest<TimelineResponse>(`/patients/${encodeURIComponent(patientId)}/timeline${qs ? `?${qs}` : ""}`);
}

/** Lives under analysisKeys.all, so every analysis run and document change refreshes it. */
export const timelineKey = (patientId: string, f: TimelineFilters = {}) =>
  [...analysisKeys.all, "timeline", patientId, f.category ?? "*", f.q?.trim() ?? ""] as const;

export function useTimeline(patientId: string, f: TimelineFilters = {}) {
  return useQuery({
    queryKey: timelineKey(patientId, f),
    queryFn: () => getTimeline(patientId, f),
    placeholderData: keepPreviousData, // keep the list on screen while a new filter loads
  });
}
