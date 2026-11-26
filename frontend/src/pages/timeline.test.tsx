import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { TimelineResponse } from "@/api/timeline";
import { analysisStatus, baseline, emptyTimeline, json, makeClaim, makeDetail, makeDoc, makeEntry, makeRun, mockApi, renderApp } from "@/test/utils";

const TL = "GET /api/patients/SYN-0001/timeline";
const LIST = "GET /api/patients/SYN-0001/documents";

const tb = makeEntry("CLM-TB", { label: "Diagnosis documented as historical: tuberculosis", entity: "tuberculosis", quote: "tuberculosis",
  assertion: "historical", ordering_basis: "event_date", when: "2015", when_precision: "year",
  event_date: { value: "2015-01-01", precision: "year", approximate: false, raw_text: "in 2015", basis: "explicit", note: "year only" } });
const fever = makeEntry("CLM-FEV", { category: "symptom", label: "Symptom documented: fever", entity: "fever", quote: "Fever", assertion: null,
  ordering_basis: "event_date", when: "~2026-03-07", when_approximate: true,
  event_date: { value: "2026-03-07", precision: "day", approximate: true, raw_text: "for 3 days", basis: "relative", note: "relative to admission" } });
const htn = makeEntry("CLM-HTN");
const hb = makeEntry("CLM-HB", { category: "lab_result", label: "Lab result: hemoglobin 7.9 g/dL, flagged L in the report", entity: "hemoglobin",
  quote: "Hemoglobin", assertion: null, ordering_basis: "event_date", when: "2026-03-11", document_date: "2026-03-12",
  document_id: "DOC-L", document_type: "Laboratory Report", section: "RESULTS",
  event_date: { value: "2026-03-11", precision: "day", approximate: false, raw_text: "COLLECTION DATE: 2026-03-11", basis: "document_header", note: null } });
const llm = makeEntry("CLM-LLM", { label: "Diagnosis: focal consolidation (documented as absent)", entity: "focal consolidation", assertion: "absent",
  extraction_method: "llm:anthropic/claude-x", when: "2026-03-11", document_date: "2026-03-11" });

function full(extra: Partial<TimelineResponse> = {}): TimelineResponse {
  const entries = [tb, fever, htn, hb, llm];
  return emptyTimeline({ results_run_id: "RUN-AAAAAAAAAAAA", is_current: true, total: 5, by_basis: { event_date: 3, document_date: 2 },
    by_category: { diagnosis: 3, symptom: 1, lab_result: 1 }, entries, ...extra });
}

const docs = [makeDoc("DOC-A", "processed", "Admission Note")];

describe("Clinical Timeline", () => {
  it("is reachable from the sidebar now that it is built", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, docs) });
    const { router } = renderApp("/workspace/overview");
    const nav = (await screen.findAllByRole("navigation", { name: "Workspace" }))[0]!;
    await userEvent.click(within(nav).getByRole("link", { name: /clinical timeline/i }));
    expect(router.state.location.pathname).toBe("/workspace/timeline");
    expect(await screen.findByRole("heading", { name: "Clinical Timeline" })).toBeInTheDocument();
  });

  it("asks for an analysis before there is anything to show", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, docs) });
    renderApp("/workspace/timeline");
    expect(await screen.findByText("No timeline yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });

  it("shows entries by date with their basis, precision and source", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, docs), [TL]: () => json(200, full()) });
    renderApp("/workspace/timeline");
    const groups = await screen.findAllByTestId("timeline-group");
    expect(groups.map((g) => g.textContent?.slice(0, 11))).toEqual(["20151 entry", "~2026-03-07", "2026-03-101", "2026-03-112"]);
    expect(screen.getByTestId("timeline-counts")).toHaveTextContent("5 entries · 3 placed by a stated event date · 2 by document date only");

    const entries = screen.getAllByTestId("timeline-entry");
    const byId = (text: string) => entries.find((e) => e.textContent?.includes(text))!;
    expect(within(byId("tuberculosis")).getByText("year only")).toBeInTheDocument();
    expect(within(byId("fever")).getByText("approximate")).toBeInTheDocument();
    expect(byId("fever")).toHaveTextContent("Event date resolved from a relative expression");
    expect(byId("hemoglobin")).toHaveTextContent("Collected 2026-03-11 · report dated 2026-03-12");
    expect(byId("hypertension")).toHaveAttribute("data-basis", "document_date");
    expect(byId("hypertension")).toHaveTextContent("No event date in the passage; placed by the document date");
    expect(within(byId("focal consolidation")).getByText("LLM")).toBeInTheDocument();
    expect(within(byId("focal consolidation")).getByText("absent")).toBeInTheDocument();
    expect(within(byId("hemoglobin")).getByRole("link", { name: /view source/i }))
      .toHaveAttribute("href", "/workspace/documents?doc=DOC-L&claim=CLM-HB");
  });

  it("filters by category and search on the server", async () => {
    const calls = mockApi({
      ...baseline, [LIST]: () => json(200, docs),
      [TL]: () => {
        const url = calls.urls[calls.urls.length - 1]!;
        if (url.includes("category=lab_result")) return json(200, full({ entries: [hb] }));
        if (url.includes("q=")) return json(200, full({ entries: [] }));
        return json(200, full());
      },
    });
    renderApp("/workspace/timeline");
    await screen.findAllByTestId("timeline-entry");
    await userEvent.click(screen.getByRole("button", { name: /lab result 1/i }));
    await waitFor(() => expect(screen.getAllByTestId("timeline-entry")).toHaveLength(1));
    expect(screen.getByRole("button", { name: /lab result 1/i })).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(screen.getByRole("button", { name: /^all 5/i }));
    await userEvent.type(screen.getByRole("searchbox", { name: /search the timeline/i }), "zzz");
    expect(await screen.findByText("No entries match")).toBeInTheDocument();
    expect(calls.urls.some((u) => u.endsWith("timeline?q=zzz"))).toBe(true);
    expect(calls.urls.some((u) => /q=z(&|$)/.test(u))).toBe(false); // debounced: no request per keystroke

    await userEvent.click(screen.getByRole("button", { name: /clear filters/i }));
    await waitFor(() => expect(screen.getAllByTestId("timeline-entry")).toHaveLength(5));
  });

  it("warns when the timeline is stale", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, docs),
      [TL]: () => json(200, full({ is_current: false, stale_reason: "Documents were added, removed or re-uploaded after this analysis. Run it again." })) });
    renderApp("/workspace/timeline");
    expect(await screen.findByText(/This timeline may be out of date: Documents were added/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /re-run analysis/i })).toBeInTheDocument();
  });

  it("View source opens the document with that claim highlighted", async () => {
    const text = "DOCUMENT TYPE: Laboratory Report\n---\nRESULTS:\nHemoglobin 7.9 g/dL L";
    const lab = makeDoc("DOC-L", "processed", "Laboratory Report");
    const start = text.indexOf("Hemoglobin");
    const claim = makeClaim("CLM-HB", { claim_type: "lab_result", entity: "hemoglobin", surface: "Hemoglobin", attributes: { kind: "lab_result" },
      source: { document_id: "DOC-L", passage_id: "DOC-L:P002", section: "RESULTS", char_start: start, char_end: text.length,
        evidence_text: text.slice(start), entity_char_start: start, entity_char_end: start + 10 } });
    mockApi({ ...baseline, [LIST]: () => json(200, [lab]), [TL]: () => json(200, full()),
      "GET /api/documents/DOC-L": () => json(200, makeDetail(lab, { extracted_text: text })),
      "GET /api/patients/SYN-0001/analysis/latest": () => json(200, analysisStatus({ results_run: makeRun(), latest_run: makeRun(), is_current: true })),
      "GET /api/patients/SYN-0001/claims": () => json(200, [claim]) });
    const { router } = renderApp("/workspace/timeline");
    const hbEntry = (await screen.findAllByTestId("timeline-entry")).find((e) => e.textContent?.includes("hemoglobin"))!;
    await userEvent.click(within(hbEntry).getByRole("link", { name: /view source/i }));
    expect(router.state.location.pathname).toBe("/workspace/documents");
    const mark = await screen.findByTestId("source-highlight");
    expect(mark.textContent).toBe("Hemoglobin");
    expect(screen.getByRole("button", { name: "Hide in text" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("Documents: claims at a glance", () => {
  it("shows claim counts on processed document cards and the passage with the quoted words marked", async () => {
    const a = makeDoc("DOC-A", "processed", "Progress Note");
    const f = makeDoc("DOC-F", "failed", null);
    const passage = "Warfarin held due to bleeding.";
    const c1 = makeClaim("CLM-1", { source: { ...makeClaim("x").source, char_start: 100, char_end: 130, evidence_text: passage,
      entity_char_start: 100, entity_char_end: 108 } });
    const c2 = makeClaim("CLM-2", { entity: "bleeding", surface: "bleeding", claim_type: "diagnosis", attributes: { kind: "diagnosis", assertion: "present" },
      source: { ...c1.source, entity_char_start: 121, entity_char_end: 129 } });
    mockApi({ ...baseline, [LIST]: () => json(200, [a, f]),
      "GET /api/documents/DOC-A": () => json(200, makeDetail(a)),
      "GET /api/patients/SYN-0001/analysis/latest": () => json(200, analysisStatus({ results_run: makeRun(), latest_run: makeRun(), is_current: true })),
      "GET /api/patients/SYN-0001/claims": () => json(200, [c1, c2]) });
    renderApp("/workspace/documents?doc=DOC-A");
    const counts = await screen.findAllByTestId("claim-count");
    expect(counts.map((c) => c.textContent)).toEqual(["2 claims"]); // none on the failed card
    const passages = await screen.findAllByTestId("claim-passage");
    expect(passages[0]!.querySelector("mark")!.textContent).toBe("Warfarin");
    expect(passages[1]!.querySelector("mark")!.textContent).toBe("bleeding");
    expect(passages[0]).toHaveTextContent(passage);
  });

  it("says claims are available in the empty viewer", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, [makeDoc("DOC-A", "processed", "Progress Note")]) });
    renderApp("/workspace/documents");
    expect(await screen.findByText(/extracted claims with the exact source words/)).toBeInTheDocument();
  });
});
