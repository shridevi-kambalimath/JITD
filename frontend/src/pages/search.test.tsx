import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { SearchResponse } from "@/api/search";
import { baseline, json, makeEntry, mockApi, renderApp } from "@/test/utils";

const SEARCH = "GET /api/patients/SYN-0001/search";
const glycomet = "Glycomet 500 mg orally twice daily.";

function response(extra: Partial<SearchResponse> = {}): SearchResponse {
  const finding = { finding_id: "FND-MED-metformin", subject: "metformin", state: "CONFLICTING_EVIDENCE" as const };
  const ref = { category: "medication", entity: "metformin", extraction_method: "rule:med-1", verified: true, finding };
  const passages = Array.from({ length: 7 }, (_, i) => ({
    passage_id: `DOC-A:P00${i}`, document_id: "DOC-A", document_type: i === 0 ? "Admission Note" : "Discharge Summary", document_date: "2026-03-10",
    section: "HOME MEDICATIONS", text: i === 0 ? glycomet : `Metformin line ${i}.`, score: 3.27 - i * 0.1,
    matches: (i === 0 ? [[0, 8]] : [[0, 9]]) as [number, number][], section_matched: false,
    claims: [{ ...ref, claim_id: `CLM-00000000000${i}`, surface: i === 0 ? "Glycomet" : "Metformin" }],
  }));
  return { patient_id: "SYN-0001", query: "metformin", terms: ["metformin", "glycomet", "glucophage"], expanded: ["glycomet", "glucophage"],
    scope: "all", results_run_id: "RUN-AAAAAAAAAAAA", is_current: true, note: null,
    counts: { passages: 7, claims: 1, timeline: 1, reconciliation: 1 }, passages,
    claims: [{ ...ref, claim_id: "CLM-000000000000", surface: "Glycomet", document_id: "DOC-A", document_type: "Admission Note", document_date: "2026-03-10",
      event_when: null, passage_text: glycomet, score: 3.27 }],
    timeline: [{ ...makeEntry("CLM-000000000000", { category: "medication", label: "Medication listed active: metformin (written as “Glycomet”)" }), score: 3.27 }],
    reconciliation: [{ ...finding, category: "medication", gate_rule: "GATE-04", issue_types: ["medication_dose_discrepancy"], score: 3.27 }],
    ...extra };
}

describe("Evidence Search", () => {
  it("is in the sidebar and offers example searches before the first query", async () => {
    const calls = mockApi({ ...baseline, [SEARCH]: () => json(200, response()) });
    const { router } = renderApp("/workspace/overview");
    const nav = (await screen.findAllByRole("navigation", { name: "Workspace" }))[0]!;
    await userEvent.click(within(nav).getByRole("link", { name: /evidence search/i }));
    expect(await screen.findByText("Search the patient's records")).toBeInTheDocument();
    expect(calls).not.toContain(SEARCH);
    await userEvent.click(screen.getByRole("button", { name: "metformin" }));
    expect(router.state.location.search).toBe("?q=metformin");
    expect(await screen.findByTestId("search-summary")).toHaveTextContent("7 passages for “metformin” · also matched glycomet, glucophage");
  });

  it("exit criterion: metformin finds the Glycomet line, marked, with its claim, state and source links", async () => {
    const calls = mockApi({ ...baseline, [SEARCH]: () => json(200, response()) });
    renderApp("/workspace/search");
    await userEvent.type(screen.getByRole("searchbox", { name: "Search the records" }), "metformin{Enter}");
    const hits = await screen.findAllByTestId("passage-hit");
    expect(hits).toHaveLength(5); // the All tab previews five
    expect(within(hits[0]!).getByTestId("passage-text").querySelector("mark")!.textContent).toBe("Glycomet");
    expect(hits[0]).toHaveTextContent("Admission Note2026-03-10HOME MEDICATIONS");
    const chip = within(hits[0]!).getByTestId("claim-chip");
    expect(chip).toHaveTextContent("metforminConflicting evidence");
    expect(within(chip).getByRole("link", { name: "Inspect metformin" })).toHaveAttribute("href", "/workspace/evidence/CLM-000000000000");
    expect(within(hits[0]!).getByRole("link", { name: /open document/i })).toHaveAttribute("href", "/workspace/documents?doc=DOC-A&claim=CLM-000000000000");
    expect(screen.getByTestId("claim-hit")).toHaveTextContent("written as “Glycomet”");
    expect(screen.getByTestId("finding-hit")).toHaveTextContent("Conflicting evidenceGATE-04Dose differs between lists");
    expect(within(screen.getByTestId("timeline-hit")).getByRole("link", { name: /inspect evidence/i })).toBeInTheDocument();
    expect(calls.urls.some((u) => u.endsWith("/search?q=metformin"))).toBe(true);
  });

  it("switches result tabs and shows everything in a tab", async () => {
    mockApi({ ...baseline, [SEARCH]: () => json(200, response()) });
    const { router } = renderApp("/workspace/search?q=metformin");
    await screen.findAllByTestId("passage-hit");
    await userEvent.click(screen.getByRole("button", { name: /show all 7 passages/i }));
    expect(router.state.location.search).toBe("?q=metformin&tab=passages");
    expect(screen.getAllByTestId("passage-hit")).toHaveLength(7);
    expect(screen.queryByTestId("claim-hit")).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: /reconciliation\s*1/i }));
    expect(screen.getByTestId("finding-hit")).toBeInTheDocument();
    expect(screen.queryByTestId("passage-hit")).toBeNull();
  });

  it("says when nothing matches or nothing has been analysed", async () => {
    let body = response({ counts: { passages: 0, claims: 0, timeline: 0, reconciliation: 0 }, passages: [], claims: [], timeline: [], reconciliation: [],
      expanded: [], note: "No passage in these records mentions the search terms." });
    mockApi({ ...baseline, [SEARCH]: () => json(200, body) });
    const { router } = renderApp("/workspace/search?q=zebra");
    expect(await screen.findByTestId("search-note")).toHaveTextContent("No passage in these records mentions the search terms.");
    body = { ...body, results_run_id: null, note: "Nothing to search yet. Run the analysis first." };
    await router.navigate("/workspace/search?q=kidney");
    await waitFor(() => expect(screen.getByTestId("search-note")).toHaveTextContent("Run the analysis first."));
  });

  it("warns when results come from an out-of-date analysis", async () => {
    mockApi({ ...baseline, [SEARCH]: () => json(200, response({ is_current: false })) });
    renderApp("/workspace/search?q=metformin");
    expect(await screen.findByText(/analysis that is out of date/)).toBeInTheDocument();
  });
});
