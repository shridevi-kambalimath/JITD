import type { TimelineEntry } from "@/api/timeline";
import { describeEventDate } from "@/lib/claims";

/** Plain-language reason this entry sits where it does. Never claims more certainty than the record. */
export function placementText(e: TimelineEntry): string {
  if (e.ordering_basis === "document_date") {
    return e.event_date.raw_text
      ? `Date written as “${e.event_date.raw_text}” cannot be resolved; placed by the document date`
      : "No event date in the passage; placed by the document date";
  }
  if (e.ordering_basis === "undated") return "No event date and no document date; listed last";
  if (e.category === "lab_result" && e.event_date.basis === "document_header") {
    return `Collected ${e.when}${e.document_date ? ` · report dated ${e.document_date}` : ""}`;
  }
  const differs = e.document_date && e.document_date !== e.event_date.value;
  return `Event date ${describeEventDate(e.event_date)}${differs ? ` · document dated ${e.document_date}` : ""}`;
}

export function precisionTag(e: TimelineEntry): string | null {
  if (e.ordering_basis !== "event_date") return null;
  if (e.when_precision === "year") return "year only";
  if (e.when_precision === "month") return "month only";
  if (e.when_approximate) return "approximate";
  return null;
}

/** Consecutive entries with the same displayed date form one group; the server already sorted them. */
export function groupByWhen(entries: TimelineEntry[]): { when: string; entries: TimelineEntry[] }[] {
  const groups: { when: string; entries: TimelineEntry[] }[] = [];
  for (const e of entries) {
    const last = groups[groups.length - 1];
    if (last && last.when === e.when) last.entries.push(e);
    else groups.push({ when: e.when, entries: [e] });
  }
  return groups;
}
