import type { Claim, ClaimCategory, DateValue } from "@/api/analysis";

export const CATEGORY_LABELS: Record<ClaimCategory, string> = {
  medication: "Medication",
  diagnosis: "Diagnosis",
  allergy: "Allergy",
  lab_result: "Lab result",
  symptom: "Symptom",
  procedure: "Procedure",
  encounter: "Encounter",
  record_reference: "Record reference",
};

const BASIS: Record<DateValue["basis"], string> = {
  explicit: "stated in the passage",
  relative: "resolved from a relative expression",
  document_header: "from the document header",
  none: "no date stated",
};

/** "2026-03-11", "~2026-03-07", "2019 (year only)", "not resolved" (a date is written but has no anchor) or "undated". Never falls back to the document date. */
export function formatEventDate(d: DateValue): string {
  if (!d.value) return d.raw_text ? "not resolved" : "undated";
  const v = d.precision === "year" ? d.value.slice(0, 4) : d.precision === "month" ? d.value.slice(0, 7) : d.value;
  const suffix = d.precision === "year" ? " (year only)" : d.precision === "month" ? " (month only)" : "";
  return `${d.approximate ? "~" : ""}${v}${suffix}`;
}

/** Tooltip text explaining where an event date came from. */
export function describeEventDate(d: DateValue): string {
  return [BASIS[d.basis], d.raw_text ? `"${d.raw_text}"` : null, d.note].filter(Boolean).join(" · ");
}

/** "Rule" or "LLM", plus the precise method for a tooltip. */
export function methodLabel(c: Pick<Claim, "extraction_method">): { short: "Rule" | "LLM"; detail: string } {
  const llm = c.extraction_method.startsWith("llm:");
  return llm
    ? { short: "LLM", detail: `Proposed by ${c.extraction_method.slice(4)}; quote verified word for word against the source passage` }
    : { short: "Rule", detail: `Deterministic rule ${c.extraction_method.slice(5)}` };
}
