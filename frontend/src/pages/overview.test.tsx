import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { DocumentSummary } from "@/api/documents";
import { analysedOverview, analysisStatus, baseline, envelope, json, makeOverview, makeRun, mockApi, renderApp } from "@/test/utils";

function doc(id: string, status: DocumentSummary["status"], type: string | null, error: string | null = null): DocumentSummary {
  return { document_id: id, patient_id: "SYN-0001", filename: `${id}.txt`, file_format: "txt", size_bytes: 100, sha256: "x",
    status, document_type: type, document_date: type ? "2026-03-10" : null, source_document_id: null, extraction_method: "utf8_text",
    page_count: null, char_count: 100, warnings: [], error_code: error, error_message: error ? "msg" : null,
    uploaded_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
}

describe("Overview", () => {
  it("shows real document counts and never invents numbers for stages without results", async () => {
    mockApi({
      ...baseline,
      "GET /api/patients/SYN-0001/documents": () => json(200, [
        doc("DOC-A", "processed", "Admission Note"), doc("DOC-B", "processed", "Laboratory Report"), doc("DOC-C", "failed", null, "no_text_layer"),
      ]),
      "GET /api/patients/SYN-0001/overview": () => json(200, makeOverview({ documents: { total: 3, processed: 2, failed: 1, in_progress: 0 } })),
    });
    renderApp("/workspace/overview");
    const docsStage = await screen.findByTestId("stage-Documents");
    expect(docsStage).toHaveTextContent("2");
    expect(docsStage).toHaveTextContent("1 failed");
    const claims = screen.getByTestId("stage-Claims & events");
    expect(claims).toHaveTextContent("not analysed yet");
    expect(within(claims).queryByText("0")).toBeNull();
    expect(screen.getByTestId("stage-Timeline entries")).toHaveTextContent("not analysed yet");
    expect(screen.getByTestId("stage-Discrepancies")).toHaveTextContent("not analysed yet");
    expect(screen.getByTestId("stage-Verified claims")).toHaveTextContent("not analysed yet");
    expect(screen.queryByText(/^Phase \d+$/)).toBeNull(); // every pipeline stage is built now
    expect(screen.getByText("no_text_layer")).toBeInTheDocument();
    expect(screen.getByText("3 total")).toBeInTheDocument();
    expect(screen.queryByTestId("state-bar")).toBeNull(); // no bar without reconciled subjects
  });

  it("shows every stage and the evidence-state distribution from GET /overview", async () => {
    mockApi({ ...baseline, "GET /api/patients/SYN-0001/documents": () => json(200, []),
      "GET /api/patients/SYN-0001/overview": () => json(200, analysedOverview()) });
    renderApp("/workspace/overview");
    const stage = (name: string) => screen.findByTestId(`stage-${name}`);
    expect(await stage("Documents")).toHaveTextContent(/^01Documents6processed$/);
    expect(await stage("Claims & events")).toHaveTextContent(/^02Claims & events4848 rule · 0 LLM$/);
    expect(await stage("Timeline entries")).toHaveTextContent(/^03Timeline entries4818 by event date · 30 by document date$/);
    expect(await stage("Discrepancies")).toHaveTextContent(/^04Discrepancies72 review · 2 conflicting · 3 insufficient$/);
    expect(await stage("Verified claims")).toHaveTextContent(/^05Verified claims48of 48 · all hard checks pass$/);
    expect(await stage("Needs review")).toHaveTextContent(/^06Needs review7pending of 7 items$/);
    expect(screen.getByTestId("state-count-REVIEW_REQUIRED")).toHaveTextContent("Review required212%");
    expect(screen.getByTestId("state-count-EVIDENCE_SUPPORTED")).toHaveTextContent("Evidence-supported1059%");
    const segments = screen.getByTestId("state-bar").querySelectorAll("a");
    expect([...segments].map((a) => a.getAttribute("aria-label"))).toEqual([
      "Review required: 2 of 17", "Conflicting evidence: 2 of 17", "Insufficient evidence: 3 of 17", "Evidence-supported: 10 of 17"]);
    expect((segments[3] as HTMLElement).style.flexGrow).toBe("10");
    await userEvent.hover(segments[2]!);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Insufficient evidence: 3 of 17 (18%)");
    expect(segments[0]).toHaveAttribute("href", "/workspace/review");
  });

  it("shows failed verification and stale results on the stages", async () => {
    mockApi({ ...baseline, "GET /api/patients/SYN-0001/documents": () => json(200, []),
      "GET /api/patients/SYN-0001/overview": () => json(200, analysedOverview({
        claims: { total: 48, rule: 48, llm: 0, verified: 47, failed_verification: 1 },
        reconciliation: { subjects: 17, needs_attention: 7, pending_review: 5, EVIDENCE_SUPPORTED: 10, CONFLICTING_EVIDENCE: 2, INSUFFICIENT_EVIDENCE: 3, REVIEW_REQUIRED: 2 },
        analysis: analysisStatus({ latest_run: makeRun(), results_run: makeRun(), is_current: false, stale_reason: "Documents changed." }) })) });
    renderApp("/workspace/overview");
    const verified = await screen.findByTestId("stage-Verified claims");
    expect(verified).toHaveTextContent(/^05Verified claims47of 48 · 1 failed checks · stale$/);
    expect(screen.getByTestId("stage-Timeline entries")).toHaveTextContent("stale");
    expect(screen.getByTestId("stage-Needs review")).toHaveTextContent(/^06Needs review5pending of 7 items · stale$/);
  });

  it("shows a retryable error when the overview cannot be loaded", async () => {
    let fail = true;
    mockApi({ ...baseline, "GET /api/patients/SYN-0001/documents": () => json(200, []),
      "GET /api/patients/SYN-0001/overview": () => (fail ? envelope(500, "internal_error", "Internal server error", "rid-ov") : json(200, makeOverview())) });
    renderApp("/workspace/overview");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("rid-ov");
    fail = false;
    await userEvent.click(within(alert).getByRole("button", { name: /retry/i }));
    expect(await screen.findByTestId("stage-Documents")).toBeInTheDocument();
  });

  it("shows an empty state that loads the demo bundle and refreshes", async () => {
    let docs: DocumentSummary[] = [];
    mockApi({
      ...baseline,
      "GET /api/patients/SYN-0001/documents": () => json(200, docs),
      "POST /api/patients/SYN-0001/demo/load": () => {
        docs = [doc("DOC-A", "processed", "Admission Note")];
        return json(200, { patient_id: "SYN-0001", loaded: docs, skipped_existing: [], rejected: [] });
      },
    });
    renderApp("/workspace/overview");
    await userEvent.click(await screen.findByRole("button", { name: /load synthetic demo bundle/i }));
    expect(await screen.findByText("Admission Note")).toBeInTheDocument();
  });

  it("shows a retryable error when documents cannot be loaded", async () => {
    let fail = true;
    mockApi({
      ...baseline,
      "GET /api/patients/SYN-0001/documents": () => (fail ? envelope(500, "internal_error", "Internal server error", "rid-500") : json(200, [])),
    });
    renderApp("/workspace/overview");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("internal_error");
    expect(alert).toHaveTextContent("rid-500");
    fail = false;
    await userEvent.click(within(alert).getByRole("button", { name: /retry/i }));
    expect(await screen.findByText(/no documents for this patient yet/i)).toBeInTheDocument();
  });

  it("follows the active patient", async () => {
    const calls = mockApi({
      ...baseline,
      "GET /api/patients/SYN-0001/documents": () => json(200, []),
      "GET /api/patients/SYN-0042/documents": () => json(200, [doc("DOC-Z", "processed", "Discharge Summary")]),
    });
    renderApp("/workspace/overview");
    await screen.findByText(/no documents for this patient yet/i);
    const sidebar = screen.getAllByLabelText("Change patient record")[0]!;
    await userEvent.click(sidebar);
    const input = screen.getByLabelText("Patient record");
    await userEvent.clear(input);
    await userEvent.type(input, "bad id!");
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "SYN-0042{Enter}");
    expect(await screen.findByText("Discharge Summary")).toBeInTheDocument();
    await waitFor(() => expect(calls).toContain("GET /api/patients/SYN-0042/documents"));
  });
});
