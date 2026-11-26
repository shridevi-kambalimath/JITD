import { describe, expect, it } from "vitest";
import { formatEventDate } from "@/lib/claims";
import { placementText } from "@/lib/timeline";
import { makeEntry } from "@/test/utils";

const vague = { value: null, precision: "unknown" as const, approximate: true, raw_text: "since last week", basis: "relative" as const,
  note: "vague relative expression with no fixed anchor; not resolved to a date" };

describe("ambiguous dates", () => {
  it("are shown as not resolved, never as a date", () => {
    expect(formatEventDate(vague)).toBe("not resolved");
    expect(formatEventDate({ ...vague, raw_text: null })).toBe("undated");
  });

  it("say on the timeline why the document date was used", () => {
    expect(placementText(makeEntry("CLM-1", { event_date: vague }))).toBe(
      "Date written as “since last week” cannot be resolved; placed by the document date");
    expect(placementText(makeEntry("CLM-2"))).toBe("No event date in the passage; placed by the document date");
  });
});
