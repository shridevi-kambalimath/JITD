import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { EvidenceSummary } from "@/api/workspace";
import { baseline, emptySummary, envelope, json, mockApi, renderApp } from "@/test/utils";

const SUMMARY = "GET /api/patients/SYN-0001/summary";
const cite = (id: string, label: string) => ({ claim_id: id, document_id: "DOC-A", document_type: "Admission Note", section: "HOME MEDICATIONS", passage_id: "DOC-A:P018", label });

function summary(extra: Partial<EvidenceSummary> = {}): EvidenceSummary {
  return emptySummary({ results_run_id: "RUN-AAAAAAAAAAAA", is_current: true,
    disclaimer: "Synthetic demonstration data. MEDUSA-X reconstructs what the supplied records state and where they disagree. It does not diagnose.",
    sections: [
      { key: "states", title: "Evidence states", description: "How many reconciled subjects fall in each state.",
        lines: [{ text: "Review required: 2 subject(s).", state: "REVIEW_REQUIRED", finding_id: null, citations: [], kind: "count" }] },
      { key: "medications", title: "Medication mentions", description: "Every documented mention.",
        lines: [
          { text: "[Conflicting evidence] Metformin: listed active as “Glycomet”, 500 mg oral twice daily (Admission Note, document dated 2026-03-10).",
            state: "CONFLICTING_EVIDENCE", finding_id: "FND-MED-metformin", citations: [cite("CLM-MET000000000", "Admission Note, HOME MEDICATIONS, P018")], kind: "content" },
          { text: "Atorvastatin: listed active as “Atorva”, 20 mg oral at night (Admission Note, document dated 2026-03-10).",
            state: "EVIDENCE_SUPPORTED", finding_id: "FND-MED-atorvastatin", citations: [cite("CLM-ATO000000000", "Admission Note, HOME MEDICATIONS, P019")], kind: "content" },
        ] },
      { key: "procedures", title: "Procedures", description: "Procedures documented as performed.", lines: [] },
    ], ...extra });
}

describe("Evidence Summary", () => {
  it("shows the disclaimer, labelled lines with clickable citations, empty sections and a Markdown download", async () => {
    mockApi({ ...baseline, [SUMMARY]: () => json(200, summary()) });
    const { router } = renderApp("/workspace/summary");
    expect(await screen.findByTestId("disclaimer")).toHaveTextContent("It does not diagnose.");
    const meds = screen.getByTestId("section-medications");
    const lines = within(meds).getAllByTestId("summary-line");
    expect(lines[0]).toHaveTextContent(/^Conflicting evidenceMetformin: listed active as “Glycomet”/); // badge, no bracket prefix
    expect(lines[1]).toHaveTextContent(/^Atorvastatin/); // supported lines carry no badge
    expect(screen.getByRole("region", { name: "Procedures" }) ?? null).toBeTruthy();
    expect(screen.getByText("None identified by the rules.")).toBeInTheDocument();
    const dl = screen.getByRole("link", { name: /download markdown/i });
    expect(dl).toHaveAttribute("href", "/api/patients/SYN-0001/summary.md");
    expect(dl).toHaveAttribute("download");
    await userEvent.click(within(lines[0]!).getByRole("link", { name: /Admission Note, HOME MEDICATIONS, P018/ }));
    expect(router.state.location.pathname).toBe("/workspace/evidence/CLM-MET000000000");
  });

  it("is empty before an analysis, without a download", async () => {
    mockApi({ ...baseline, [SUMMARY]: () => json(200, emptySummary()) });
    renderApp("/workspace/summary");
    expect(await screen.findByText("No summary yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /download markdown/i })).toBeNull();
  });

  it("marks an out-of-date summary and shows load errors", async () => {
    mockApi({ ...baseline, [SUMMARY]: () => json(200, summary({ is_current: false, stale_reason: "Documents changed." })) });
    const a = renderApp("/workspace/summary");
    expect(await screen.findByText("Out of date: Documents changed.")).toBeInTheDocument();
    a.unmount();
    mockApi({ ...baseline, [SUMMARY]: () => envelope(500, "internal_error", "boom", "rid-s") });
    renderApp("/workspace/summary");
    expect(await screen.findByRole("alert")).toHaveTextContent("rid-s");
  });
});
