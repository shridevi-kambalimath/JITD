import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

/** Mirrors backend/medusa/schemas/analysis.py and the Claim model in schemas/domain.py */
export type LlmRunStatus = "disabled" | "misconfigured" | "ok" | "partial" | "failed";

export interface AnalysisStats {
  documents_analyzed?: number;
  documents_skipped?: { document_id: string; filename: string; status: string; reason: string }[];
  passages?: number;
  claims_total?: number;
  claims_by_category?: Record<string, number>;
  claims_by_method?: { rule: number; llm: number };
  notes?: string[];
  verification?: { verified: number; failed: number; failed_checks: Record<string, number>; advisory_not_met: Record<string, number> };
  findings?: { total: number; with_issues: number; high_risk_with_issues: number; by_state?: Record<string, number> };
  llm?: {
    provider?: string;
    documents_ok?: number;
    documents_failed?: number;
    accepted?: number;
    agreed_with_rules?: number;
    rejected?: number;
    errors?: { document_id: string; code: string; message: string }[];
  };
}

export interface AnalysisRun {
  run_id: string;
  patient_id: string;
  status: "running" | "completed" | "failed";
  started_at: string;
  finished_at: string | null;
  extractor: string;
  llm_status: LlmRunStatus;
  llm_error: string | null;
  document_fingerprint: string;
  stats: AnalysisStats;
  error: string | null;
}

export interface AnalysisStatus {
  patient_id: string;
  latest_run: AnalysisRun | null;
  results_run: AnalysisRun | null;
  is_current: boolean;
  stale_reason: string | null;
}

export interface LlmConfig {
  provider: "none" | "anthropic" | "openai_compatible";
  model: string | null;
  status: "disabled" | "misconfigured" | "configured";
  reason: string | null;
  api_key_set: boolean;
  custom_base_url: boolean;
}

export type ClaimCategory =
  | "medication" | "diagnosis" | "allergy" | "lab_result" | "symptom" | "procedure" | "encounter" | "record_reference";

export interface DateValue {
  value: string | null;
  precision: "day" | "month" | "year" | "unknown";
  approximate: boolean;
  raw_text: string | null;
  basis: "explicit" | "relative" | "document_header" | "none";
  note: string | null;
}

export interface Claim {
  claim_id: string;
  patient_id: string;
  claim_type: ClaimCategory;
  entity: string;
  surface: string;
  attributes: { kind: string; assertion?: string | null; model_assertion?: string | null; [k: string]: unknown };
  source: {
    document_id: string;
    passage_id: string;
    section: string;
    char_start: number;
    char_end: number;
    evidence_text: string;
    entity_char_start: number;
    entity_char_end: number;
  };
  document_date: string | null;
  document_type: string;
  event_date: DateValue;
  extraction_method: string;
  /** Deterministic verification for the run that produced it. null: stored before verification existed. */
  verified?: boolean | null;
  failed_checks?: string[];
}

export const isLlmClaim = (c: Claim) => c.extraction_method.startsWith("llm:");

const enc = encodeURIComponent;

export const getAnalysisStatus = (patientId: string) =>
  apiRequest<AnalysisStatus>(`/patients/${enc(patientId)}/analysis/latest`);
export const runAnalysis = (patientId: string) =>
  apiRequest<AnalysisRun>(`/patients/${enc(patientId)}/analysis`, { method: "POST" });
export const getLlmConfig = () => apiRequest<LlmConfig>("/analysis/config");
export const listClaims = (patientId: string, documentId?: string) =>
  apiRequest<Claim[]>(`/patients/${enc(patientId)}/claims${documentId ? `?document_id=${enc(documentId)}` : ""}`);

export const analysisKeys = {
  all: ["analysis"] as const,
  status: (patientId: string) => ["analysis", "status", patientId] as const,
  claims: (patientId: string, documentId?: string) => ["analysis", "claims", patientId, documentId ?? "*"] as const,
  config: ["analysis-config"] as const,
};

export function useAnalysisStatus(patientId: string) {
  return useQuery({ queryKey: analysisKeys.status(patientId), queryFn: () => getAnalysisStatus(patientId) });
}

export function useClaims(patientId: string, documentId?: string, enabled = true) {
  return useQuery({
    queryKey: analysisKeys.claims(patientId, documentId),
    queryFn: () => listClaims(patientId, documentId),
    enabled,
  });
}

export function useLlmConfig() {
  return useQuery({ queryKey: analysisKeys.config, queryFn: getLlmConfig, staleTime: 60_000 });
}

/**
 * The server's results were replaced (a new run, or a demo reset). Cached results that no screen is showing are
 * dropped, so opening one later fetches it instead of briefly showing the previous run's evidence state; results on
 * screen are refetched.
 */
export function replaceAnalysisResults(qc: QueryClient) {
  qc.removeQueries({ queryKey: analysisKeys.all, type: "inactive" });
  return qc.invalidateQueries({ queryKey: analysisKeys.all });
}

export function useRunAnalysis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: runAnalysis,
    // a failed run is recorded too, so refresh either way
    onSettled: () => replaceAnalysisResults(qc),
  });
}

// ---------------------------------------------------------------- evidence inspector
export interface CheckResult {
  check_id: string;
  passed: boolean;
  severity: "hard" | "advisory";
  detail: string;
}

export interface EvidenceView {
  claim: Claim;
  document: import("@/api/documents").DocumentSummary;
  passage: { passage_id: string; document_id: string; section: string; char_start: number; char_end: number; text: string };
  context_before: string;
  evidence_text: string;
  context_after: string;
  verification: { claim_id: string; verified: boolean; checks: CheckResult[] };
  verified_at_analysis: boolean | null;
  verification_changed: boolean;
  timeline_entry: import("@/api/timeline").TimelineEntry | null;
  related_findings: {
    finding_id: string;
    subject: string;
    category: string;
    state: import("@/components/status-badge").EvidenceState | null;
    gate_rule: string | null;
    role: string;
  }[];
}

export const getEvidence = (patientId: string, claimId: string) =>
  apiRequest<EvidenceView>(`/patients/${enc(patientId)}/claims/${enc(claimId)}/evidence`);

export function useEvidence(patientId: string, claimId: string) {
  return useQuery({ queryKey: [...analysisKeys.all, "evidence", patientId, claimId], queryFn: () => getEvidence(patientId, claimId) });
}
