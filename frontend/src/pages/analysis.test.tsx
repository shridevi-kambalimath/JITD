import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Claim } from "@/api/analysis";
import { analysedOverview, analysisStatus, baseline, envelope, json, llmConfig, makeClaim, makeDetail, makeDoc, makeOverview, makeRun, mockApi, renderApp } from "@/test/utils";

const LIST = "GET /api/patients/SYN-0001/documents";
const LATEST = "GET /api/patients/SYN-0001/analysis/latest";
const RUN = "POST /api/patients/SYN-0001/analysis";
const OVERVIEW = "GET /api/patients/SYN-0001/overview";
const CLAIMS = "GET /api/patients/SYN-0001/claims";
const processed = [makeDoc("DOC-A", "processed", "Progress Note"), makeDoc("DOC-B", "processed", "Laboratory Report")];

describe("Overview: analysis", () => {
  it("runs the analysis and then shows the stored counts by extraction method", async () => {
    let overview = makeOverview({ documents: { total: 2, processed: 2, failed: 0, in_progress: 0 } });
    const calls = mockApi({
      ...baseline,
      [LIST]: () => json(200, processed),
      [OVERVIEW]: () => json(200, overview),
      [RUN]: () => {
        const run = makeRun();
        overview = analysedOverview({ claims: { total: 49, rule: 48, llm: 1, verified: 49, failed_verification: 0 },
          analysis: analysisStatus({ latest_run: run, results_run: run, is_current: true }) });
        return json(200, run);
      },
    });
    renderApp("/workspace/overview");
    const stage = await screen.findByTestId("stage-Claims & events");
    await waitFor(() => expect(stage).toHaveTextContent("not analysed yet"));
    await userEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await waitFor(() => expect(stage).toHaveTextContent("49"));
    expect(stage).toHaveTextContent("48 rule · 1 LLM");
    expect(calls.filter((c) => c === RUN)).toHaveLength(1);
    expect(screen.getByRole("button", { name: /re-run analysis/i })).toBeInTheDocument();
    expect(screen.getByTestId("analysis-summary")).toHaveTextContent("RUN-AAAAAAAAAAAA");
  });

  it("cannot be started without processed documents, and says why", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, [makeDoc("DOC-F", "failed", null)]),
      [OVERVIEW]: () => json(200, makeOverview({ documents: { total: 1, processed: 0, failed: 1, in_progress: 0 } })) });
    renderApp("/workspace/overview");
    const button = await screen.findByRole("button", { name: "Run analysis" });
    expect(button).toBeDisabled();
    expect(screen.getByText("Needs at least one processed document")).toBeInTheDocument();
  });

  it("shows the backend error when a run is refused", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, processed),
      [OVERVIEW]: () => json(200, makeOverview({ documents: { total: 2, processed: 2, failed: 0, in_progress: 0 } })),
      [RUN]: () => envelope(409, "conflict", "An analysis run for SYN-0001 is already in progress.", "rid-409") });
    renderApp("/workspace/overview");
    await userEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("already in progress");
    expect(alert).toHaveTextContent("rid-409");
  });

  it("flags stale results, a failed latest run and an LLM that was not used", async () => {
    const results = makeRun({ llm_status: "failed", llm_error: "auth: Provider rejected the credentials (HTTP 401)." });
    const failed = makeRun({ run_id: "RUN-BBBBBBBBBBBB", status: "failed", error: "RuntimeError: disk full" });
    mockApi({ ...baseline, [LIST]: () => json(200, processed),
      [OVERVIEW]: () => json(200, analysedOverview({ analysis: analysisStatus({ latest_run: failed, results_run: results, is_current: false,
        stale_reason: "Documents were added, removed or re-uploaded after this analysis. Run it again." }) })) });
    renderApp("/workspace/overview");
    const summary = await screen.findByTestId("analysis-summary");
    expect(summary).toHaveTextContent("RUN-BBBBBBBBBBBB) failed: RuntimeError: disk full");
    expect(summary).toHaveTextContent("results below are from the previous successful run");
    expect(summary).toHaveTextContent("Stale: Documents were added");
    expect(summary).toHaveTextContent("LLM extraction was not used (auth: Provider rejected");
    expect(screen.getByTestId("stage-Claims & events")).toHaveTextContent("stale");
  });

  it("reports the extraction configuration from the backend", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, []),
      [OVERVIEW]: () => json(200, makeOverview({ llm: llmConfig({ provider: "anthropic", model: "claude-x", status: "misconfigured",
        reason: "MEDUSA_LLM_API_KEY is not set (required for anthropic)." }) })) });
    renderApp("/workspace/overview");
    expect(await screen.findByText(/LLM misconfigured: MEDUSA_LLM_API_KEY is not set/)).toBeInTheDocument();
  });

  it("shows rules plus model when the LLM is configured", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, []),
      [OVERVIEW]: () => json(200, makeOverview({ llm: llmConfig({ provider: "openai_compatible", model: "llama3", status: "configured" }) })) });
    renderApp("/workspace/overview");
    expect(await screen.findByText("rules + LLM · openai_compatible/llama3")).toBeInTheDocument();
  });
});

describe("Document viewer: extracted claims", () => {
  const doc = makeDoc("DOC-A", "processed", "Progress Note");
  const text = "DOCUMENT TYPE: Progress Note\nPATIENT ID: SYN-0001\n---\nPLAN:\nWarfarin held. Fever since about 3 days.";
  const warfarin = makeClaim("CLM-1", { surface: "Warfarin", source: { ...makeClaim("x").source, entity_char_start: text.indexOf("Warfarin"), entity_char_end: text.indexOf("Warfarin") + 8 } });
  const fever: Claim = makeClaim("CLM-2", {
    claim_type: "symptom", entity: "fever", surface: "Fever", attributes: { kind: "llm", assertion: "present", model_assertion: "present" },
    source: { ...warfarin.source, entity_char_start: text.indexOf("Fever"), entity_char_end: text.indexOf("Fever") + 5 },
    event_date: { value: "2026-03-07", precision: "day", approximate: true, raw_text: "about 3 days", basis: "relative", note: null },
    extraction_method: "llm:anthropic/claude-x",
  });
  const negated = makeClaim("CLM-3", { claim_type: "diagnosis", entity: "chronic kidney disease", surface: "chronic kidney disease",
    attributes: { kind: "diagnosis", assertion: "absent" } });

  function setup(claims: Claim[], status = analysisStatus({ results_run: makeRun(), latest_run: makeRun(), is_current: true })) {
    return mockApi({ ...baseline, [LIST]: () => json(200, [doc]), "GET /api/documents/DOC-A": () => json(200, makeDetail(doc, { extracted_text: text })),
      [LATEST]: () => json(200, status), [CLAIMS]: () => json(200, claims) });
  }

  it("lists claims with category, method, assertion and event date", async () => {
    setup([warfarin, fever, negated]);
    renderApp("/workspace/documents?doc=DOC-A");
    const rows = await screen.findAllByTestId("claim-row");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText("Medication")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Rule")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("undated")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("LLM")).toHaveAttribute("title", expect.stringContaining("anthropic/claude-x"));
    expect(within(rows[1]!).getByText("~2026-03-07")).toHaveAttribute("title", expect.stringContaining("relative"));
    expect(within(rows[2]!).getByText("absent")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Extracted claims" })).toHaveTextContent("(3)");
  });

  it("highlights the exact source words for a claim, and clears them again", async () => {
    setup([warfarin, fever]);
    renderApp("/workspace/documents?doc=DOC-A");
    const rows = await screen.findAllByTestId("claim-row");
    expect(screen.queryByTestId("source-highlight")).toBeNull();
    await userEvent.click(within(rows[1]!).getByRole("button", { name: "Show in text" }));
    expect(screen.getByTestId("source-highlight").textContent).toBe("Fever"); // exact span, no whitespace slack
    await userEvent.click(within(rows[0]!).getByRole("button", { name: "Show in text" }));
    expect(screen.getByTestId("source-highlight").textContent).toBe("Warfarin");
    await userEvent.click(within(rows[0]!).getByRole("button", { name: "Hide in text" }));
    expect(screen.queryByTestId("source-highlight")).toBeNull();
  });

  it("explains an empty list instead of showing nothing", async () => {
    setup([], analysisStatus());
    renderApp("/workspace/documents?doc=DOC-A");
    expect(await screen.findByText(/has not been analysed yet/)).toBeInTheDocument();
  });

  it("says when the document arrived after the last analysis", async () => {
    setup([], analysisStatus({ results_run: makeRun(), latest_run: makeRun(), is_current: false, stale_reason: "Documents changed." }));
    renderApp("/workspace/documents?doc=DOC-A");
    expect(await screen.findByText(/added after the last analysis/)).toBeInTheDocument();
  });

  it("does not request claims for a failed document", async () => {
    const failed = makeDoc("DOC-F", "failed", null);
    const calls = mockApi({ ...baseline, [LIST]: () => json(200, [failed]), "GET /api/documents/DOC-F": () => json(200, makeDetail(failed)) });
    renderApp("/workspace/documents?doc=DOC-F");
    expect(await screen.findByText("Processing failed")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Extracted claims" })).toBeNull();
    expect(calls.urls.some((u) => u.includes("document_id="))).toBe(false); // the list-wide count query is fine
  });
});
