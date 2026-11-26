import type { FindingCategory, IssueKind, ReviewStatus } from "@/api/reconciliation";

/** Neutral wording: what differs or is missing in the records, never which record is right. */
export const ISSUE_LABELS: Record<string, string> = {
  medication_status_conflict: "Medication status differs",
  medication_dose_discrepancy: "Dose differs between lists",
  diagnosis_status_conflict: "Diagnosis status differs",
  allergy_conflict: "Allergy records differ",
  unexplained_discharge_omission: "Not on discharge list, no stop documented",
  diagnosis_not_established: "Never confirmed or excluded",
  missing_referenced_record: "Referenced record not in bundle",
  unverified_claim: "Claim failed verification",
  possible_unextracted_evidence: "Possible evidence not extracted",
};

export const ISSUE_KIND: Record<string, IssueKind> = {
  medication_status_conflict: "conflict",
  medication_dose_discrepancy: "conflict",
  diagnosis_status_conflict: "conflict",
  allergy_conflict: "conflict",
  unexplained_discharge_omission: "gap",
  diagnosis_not_established: "gap",
  missing_referenced_record: "gap",
  unverified_claim: "integrity",
  possible_unextracted_evidence: "integrity",
};

export const KIND_TONE = { conflict: "conflicting", gap: "insufficient", integrity: "review" } as const;

export const KIND_LABELS: Record<IssueKind, string> = {
  conflict: "Records differ",
  gap: "Information missing",
  integrity: "Extraction check",
};

export const FINDING_CATEGORY_LABELS: Record<FindingCategory, string> = {
  medication: "Medication",
  diagnosis: "Diagnosis",
  allergy: "Allergy",
  family_history: "Family history",
  record_reference: "Referenced record",
};

export const REVIEW_LABELS: Record<ReviewStatus, string> = {
  pending_review: "Pending review",
  reviewed: "Reviewed",
  flagged: "Flagged for follow-up",
};

export const OBSERVATION_LABELS: Record<string, string> = {
  "MED-CHANGE-01": "Documented regimen change",
  "DX-EVOL-01": "Diagnostic evolution",
  "DX-FAMILY-01": "Family history, not the patient",
  "REF-01": "Referenced record is present",
};

export const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
