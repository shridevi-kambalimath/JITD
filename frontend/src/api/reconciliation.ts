import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { analysisKeys, type Claim } from "@/api/analysis";
import type { EvidenceState } from "@/components/status-badge";
import { apiRequest } from "@/lib/api";

/** Mirrors backend/medusa/schemas/reconciliation.py and the Finding parts of schemas/domain.py */
export type FindingCategory = "medication" | "diagnosis" | "allergy" | "family_history" | "record_reference";
export type IssueKind = "conflict" | "gap" | "integrity";
export type ReviewStatus = "pending_review" | "reviewed" | "flagged";

export interface Review {
  status: ReviewStatus;
  note: string | null;
  updated_at: string | null;
  changed_since_review: boolean;
}

export interface FindingSummary {
  finding_id: string;
  category: FindingCategory;
  subject: string;
  high_risk: boolean;
  risk_reason: string | null;
  issue_types: string[];
  issues_by_kind: Partial<Record<IssueKind, number>>;
  observation_rules: string[];
  claim_count: number;
  priority: number | null;
  review: Review;
  state: EvidenceState | null;
  gate_rule: string | null;
  gate_rationale: string | null;
}

export interface ReconciliationResponse {
  patient_id: string;
  results_run_id: string | null;
  is_current: boolean;
  stale_reason: string | null;
  counts: { findings: number; with_issues: number; conflict: number; gap: number; integrity: number; pending_review: number } & Partial<Record<EvidenceState, number>>;
  findings: FindingSummary[];
}

export interface Issue {
  issue_type: string;
  kind: IssueKind;
  rule_id: string;
  description: string;
  claim_ids: string[];
}

export interface Observation {
  rule_id: string;
  text: string;
  claim_ids: string[];
}

export interface InvestigationStep {
  rule_id: string;
  query: string;
  scope: "passage" | "section";
  hits: { passage_id: string; document_id: string; section: string; score: number; text: string }[];
  outcome: string;
}

export interface FindingDetail extends FindingSummary {
  issues: Issue[];
  observations: Observation[];
  investigation: InvestigationStep[];
  claims: Claim[];
  missing_claim_ids: string[];
  results_run_id: string | null;
  is_current: boolean;
}

const enc = encodeURIComponent;

export const getReconciliation = (patientId: string) => apiRequest<ReconciliationResponse>(`/patients/${enc(patientId)}/reconciliation`);
export const getFinding = (patientId: string, findingId: string) =>
  apiRequest<FindingDetail>(`/patients/${enc(patientId)}/reconciliation/${enc(findingId)}`);
export const putReview = (patientId: string, findingId: string, body: { status: ReviewStatus; note: string | null }) =>
  apiRequest<Review>(`/patients/${enc(patientId)}/reviews/${enc(findingId)}`, { method: "PUT", body });

/** Under analysisKeys.all: every analysis run, document change and review refreshes these. */
export const reconciliationKeys = {
  list: (patientId: string) => [...analysisKeys.all, "reconciliation", patientId] as const,
  detail: (patientId: string, findingId: string) => [...analysisKeys.all, "finding", patientId, findingId] as const,
};

export function useReconciliation(patientId: string) {
  return useQuery({ queryKey: reconciliationKeys.list(patientId), queryFn: () => getReconciliation(patientId) });
}

export function useFinding(patientId: string, findingId: string | null) {
  return useQuery({
    queryKey: reconciliationKeys.detail(patientId, findingId ?? ""),
    queryFn: () => getFinding(patientId, findingId!),
    enabled: findingId !== null,
    // no keepPreviousData: while a newly selected finding loads, the panel must not show the previous one's state
  });
}

export function useSetReview(patientId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ findingId, status, note }: { findingId: string; status: ReviewStatus; note: string | null }) =>
      putReview(patientId, findingId, { status, note }),
    onSuccess: () => qc.invalidateQueries({ queryKey: analysisKeys.all }),
  });
}
