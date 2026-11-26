import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { analysisKeys } from "@/api/analysis";
import type { TimelineEntry } from "@/api/timeline";
import type { EvidenceState } from "@/components/status-badge";
import { apiRequest } from "@/lib/api";

/** Mirrors backend/medusa/schemas/search.py */
export type SearchScope = "passages" | "claims" | "timeline" | "reconciliation";

export interface FindingRef { finding_id: string; subject: string; state: EvidenceState | null }

export interface ClaimRef {
  claim_id: string;
  category: string;
  entity: string;
  surface: string;
  extraction_method: string;
  verified: boolean | null;
  finding: FindingRef | null;
}

export interface PassageHit {
  passage_id: string;
  document_id: string;
  document_type: string;
  document_date: string | null;
  section: string;
  text: string;
  score: number;
  matches: [number, number][];
  section_matched: boolean;
  claims: ClaimRef[];
}

export interface ClaimHit extends ClaimRef {
  document_id: string;
  document_type: string;
  document_date: string | null;
  event_when: string | null;
  passage_text: string;
  score: number;
}

export interface TimelineHit extends TimelineEntry { score: number }

export interface FindingHit extends FindingRef {
  category: string;
  gate_rule: string | null;
  issue_types: string[];
  score: number;
}

export interface SearchResponse {
  patient_id: string;
  query: string;
  terms: string[];
  expanded: string[];
  scope: "all" | SearchScope;
  results_run_id: string | null;
  is_current: boolean;
  note: string | null;
  counts: Record<SearchScope, number>;
  passages: PassageHit[];
  claims: ClaimHit[];
  timeline: TimelineHit[];
  reconciliation: FindingHit[];
}

export const searchEvidence = (patientId: string, q: string) =>
  apiRequest<SearchResponse>(`/patients/${encodeURIComponent(patientId)}/search?q=${encodeURIComponent(q)}`);

export function useSearch(patientId: string, q: string) {
  return useQuery({
    queryKey: [...analysisKeys.all, "search", patientId, q],
    queryFn: () => searchEvidence(patientId, q),
    enabled: q.trim().length > 0,
    placeholderData: keepPreviousData,
  });
}
