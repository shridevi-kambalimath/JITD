import { useQuery } from "@tanstack/react-query";
import { type AnalysisStatus, analysisKeys, type Claim, type DateValue, type LlmConfig } from "@/api/analysis";
import type { FindingSummary } from "@/api/reconciliation";
import type { EvidenceState } from "@/components/status-badge";
import { API_BASE, apiRequest } from "@/lib/api";

/** Mirrors backend/medusa/schemas/workspace.py and schemas/summary.py */
export interface OverviewResponse {
  patient_id: string;
  documents: { total: number; processed: number; failed: number; in_progress: number };
  analysis: AnalysisStatus;
  claims: { total: number; rule: number; llm: number; verified: number; failed_verification: number };
  timeline: { entries: number; by_event_date: number; by_document_date: number; undated: number; excluded_unverified: number };
  reconciliation: { subjects: number; needs_attention: number; pending_review: number } & Record<EvidenceState, number>;
  llm: LlmConfig;
}

export interface UncertainDate {
  claim_id: string;
  category: string;
  entity: string;
  surface: string;
  document_id: string;
  document_type: string;
  document_date: string | null;
  event_date: DateValue;
  reason: string;
}

export interface ReviewQueue {
  patient_id: string;
  results_run_id: string | null;
  is_current: boolean;
  stale_reason: string | null;
  counts: { review_required: number; conflicting: number; insufficient: number; unverified_claims: number; uncertain_dates: number; pending_review: number };
  findings: FindingSummary[];
  unverified_claims: Claim[];
  uncertain_dates: UncertainDate[];
}

export interface Citation { claim_id: string; document_id: string; document_type: string; section: string; passage_id: string; label: string }
export interface SummaryLine { text: string; state: EvidenceState | null; finding_id: string | null; citations: Citation[]; kind: "content" | "count" }
export interface SummarySection { key: string; title: string; description: string; lines: SummaryLine[] }
export interface EvidenceSummary {
  patient_id: string;
  results_run_id: string | null;
  is_current: boolean;
  stale_reason: string | null;
  generated_at: string;
  disclaimer: string;
  sections: SummarySection[];
}

const enc = encodeURIComponent;
export const summaryMarkdownUrl = (patientId: string) => `${API_BASE}/patients/${enc(patientId)}/summary.md`;

export function useOverview(patientId: string) {
  return useQuery({ queryKey: [...analysisKeys.all, "overview", patientId], queryFn: () => apiRequest<OverviewResponse>(`/patients/${enc(patientId)}/overview`) });
}

export function useReviewQueue(patientId: string) {
  return useQuery({ queryKey: [...analysisKeys.all, "review-queue", patientId], queryFn: () => apiRequest<ReviewQueue>(`/patients/${enc(patientId)}/review-queue`) });
}

export function useSummary(patientId: string) {
  return useQuery({ queryKey: [...analysisKeys.all, "summary", patientId], queryFn: () => apiRequest<EvidenceSummary>(`/patients/${enc(patientId)}/summary`) });
}
