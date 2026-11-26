/** Plain names for the deterministic checks run on every claim. */
export const CHECK_LABELS: Record<string, string> = {
  V1_source_document_exists: "Source document exists for this patient",
  V2_passage_exists: "Cited passage exists in that document",
  V3_span_exact_match: "Cited text matches the stored document exactly",
  V4_span_within_passage: "Offsets lie inside the passage",
  V5_entity_grounded: "Quoted words are at the stated offsets",
  V6_event_not_after_document: "Event date is not after the document date",
  V7_retrievable: "Passage is found by keyword search (advisory)",
};

export const checkLabel = (id: string) => CHECK_LABELS[id] ?? id;

export const evidenceHref = (claimId: string) => `/workspace/evidence/${encodeURIComponent(claimId)}`;
