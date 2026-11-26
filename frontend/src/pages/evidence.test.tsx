import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { EvidenceView } from "@/api/analysis";
import { SourceCard } from "@/components/source-card";
import { analysisStatus, baseline, emptyTimeline, json, makeClaim, makeDetail, makeDoc, makeEntry, makeRun, mockApi, renderApp } from "@/test/utils";

const LIST = "GET /api/patients/SYN-0001/documents";
const text = "PLAN:\nWarfarin held due to upper gastrointestinal bleed.\nStarted pantoprazole 40 mg IV twice daily.";
const pStart = text.indexOf("Warfarin");
const passage = "Warfarin held due to upper gastrointestinal bleed.";
const claim = makeClaim("CLM-AAAAAAAAAAAA", { document_type: "Progress Note", document_date: "2026-03-12",
  attributes: { kind: "medication", action: "held", list_context: "inpatient" }, verified: true, failed_checks: [],
  source: { document_id: "DOC-P", passage_id: "DOC-P:P010", section: "PLAN", char_start: pStart, char_end: pStart + passage.length,
    evidence_text: passage, entity_char_start: pStart, entity_char_end: pStart + 8 } });
const doc = makeDoc("DOC-P", "processed", "Progress Note");
const checks = [
  ["V1_source_document_exists", true, "hard", "document DOC-P"], ["V2_passage_exists", true, "hard", "passage DOC-P:P010"],
  ["V3_span_exact_match", true, "hard", "stored text matches cited span"], ["V4_span_within_passage", true, "hard", "inside"],
  ["V5_entity_grounded", true, "hard", "entity text at offsets is 'Warfarin'"], ["V6_event_not_after_document", true, "hard", "not applicable"],
  ["V7_retrievable", true, "advisory", "passage in top 10 keyword hits"],
] as const;

function view(extra: Partial<EvidenceView> = {}): EvidenceView {
  return { claim, document: doc, passage: { passage_id: "DOC-P:P010", document_id: "DOC-P", section: "PLAN", char_start: pStart, char_end: pStart + passage.length, text: passage },
    context_before: text.slice(0, pStart), evidence_text: passage, context_after: text.slice(pStart + passage.length),
    verification: { claim_id: claim.claim_id, verified: true, checks: checks.map(([check_id, passed, severity, detail]) => ({ check_id, passed, severity, detail })) },
    verified_at_analysis: true, verification_changed: false,
    timeline_entry: makeEntry(claim.claim_id, { category: "medication", label: "Medication held: warfarin, regimen not stated [inpatient list]", when: "2026-03-12" }),
    related_findings: [{ finding_id: "FND-MED-warfarin", subject: "warfarin", category: "medication", state: "REVIEW_REQUIRED", gate_rule: "GATE-03", role: "cited by an issue" }],
    ...extra };
}
const EV = `GET /api/patients/SYN-0001/claims/${claim.claim_id}/evidence`;

describe("Evidence inspector", () => {
  it("shows the stored source with the passage and words marked, every check, both dates and where the claim is used", async () => {
    mockApi({ ...baseline, [EV]: () => json(200, view()) });
    renderApp(`/workspace/evidence/${claim.claim_id}`);
    expect(await screen.findByTestId("verification-status")).toHaveTextContent("Verified: 6 of 6 hard checks pass");
    expect(screen.getByTestId("evidence-passage")).toHaveTextContent(passage);
    expect(screen.getByTestId("evidence-entity").textContent).toBe("Warfarin");
    expect(screen.getByTestId("evidence-context")).toHaveTextContent("Started pantoprazole");
    const facts = screen.getByLabelText("Claim facts");
    expect(facts).toHaveTextContent("Document date2026-03-12");
    expect(facts).toHaveTextContent("Event dateundated");
    expect(facts).toHaveTextContent(`chars ${pStart}–${pStart + 8}`);
    expect(screen.getAllByTestId("check")).toHaveLength(7);
    expect(screen.getByText("Cited text matches the stored document exactly")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-timeline")).toHaveTextContent("2026-03-12 · Medication held: warfarin");
    const related = screen.getByRole("list", { name: "Related findings" });
    expect(within(related).getByRole("link", { name: "Warfarin" })).toHaveAttribute("href", "/workspace/reconciliation?finding=FND-MED-warfarin");
    expect(related).toHaveTextContent("Review requiredGATE-03(cited by an issue)");
    expect(screen.getByRole("link", { name: /Progress Note · doc-p.txt/ })).toHaveAttribute("href", `/workspace/documents?doc=DOC-P&claim=${claim.claim_id}`);
  });

  it("makes a tampered span visible: failed checks, no timeline entry, and a warning that it changed since analysis", async () => {
    const failing = view({
      verification: { claim_id: claim.claim_id, verified: false, checks: checks.map(([check_id, passed, severity, detail]) => ({
        check_id, severity, passed: check_id === "V3_span_exact_match" ? false : passed,
        detail: check_id === "V3_span_exact_match" ? "stored text is 'Warfarin given due to upper gastrointestinal bleed'" : detail })) },
      verification_changed: true, timeline_entry: null,
    });
    mockApi({ ...baseline, [EV]: () => json(200, failing) });
    renderApp(`/workspace/evidence/${claim.claim_id}`);
    expect(await screen.findByRole("alert")).toHaveTextContent("passed verification during the analysis but fails now");
    expect(screen.getByTestId("verification-status")).toHaveTextContent("Failed verification: 1 hard check");
    const v3 = screen.getAllByTestId("check").find((c) => c.textContent?.includes("Cited text matches"))!;
    expect(v3).toHaveTextContent("(failed)");
    expect(v3).toHaveTextContent("stored text is 'Warfarin given");
    expect(screen.getByTestId("evidence-timeline")).toHaveTextContent("Not on the timeline: the claim does not pass verification.");
  });

  it("reports an unknown claim", async () => {
    mockApi({ ...baseline, [EV]: () => json(404, { error: { code: "not_found", message: "Claim not found", details: null, request_id: "r1" } }) });
    renderApp(`/workspace/evidence/${claim.claim_id}`);
    expect(await screen.findByRole("alert")).toHaveTextContent("not_found");
  });
});

describe("Every claim on screen links to its evidence", () => {
  it("from a document's claim list, the timeline and a reconciliation source card", async () => {
    const recLatest = () => json(200, analysisStatus({ results_run: makeRun(), latest_run: makeRun(), is_current: true }));
    mockApi({ ...baseline, [LIST]: () => json(200, [doc]), "GET /api/documents/DOC-P": () => json(200, makeDetail(doc, { extracted_text: text })),
      "GET /api/patients/SYN-0001/analysis/latest": recLatest, "GET /api/patients/SYN-0001/claims": () => json(200, [claim]),
      "GET /api/patients/SYN-0001/timeline": () => json(200, emptyTimeline({ results_run_id: "RUN-AAAAAAAAAAAA", is_current: true, total: 1,
        by_basis: { document_date: 1 }, by_category: { medication: 1 }, entries: [makeEntry(claim.claim_id, { category: "medication" })] })),
      [EV]: () => json(200, view()) });
    const { router } = renderApp("/workspace/documents?doc=DOC-P");
    const row = await screen.findByTestId("claim-row");
    await userEvent.click(within(row).getByRole("link", { name: /inspect/i }));
    expect(router.state.location.pathname).toBe(`/workspace/evidence/${claim.claim_id}`);
    expect(await screen.findByTestId("verification-status")).toBeInTheDocument();

    await router.navigate("/workspace/timeline");
    const entry = await screen.findByTestId("timeline-entry");
    expect(within(entry).getByRole("link", { name: /inspect evidence/i })).toHaveAttribute("href", `/workspace/evidence/${claim.claim_id}`);
  });

  it("marks claims that failed verification", async () => {
    const bad = { ...claim, claim_id: "CLM-BBBBBBBBBBBB", verified: false, failed_checks: ["V3_span_exact_match"] };
    mockApi({ ...baseline, [LIST]: () => json(200, [doc]), "GET /api/documents/DOC-P": () => json(200, makeDetail(doc, { extracted_text: text })),
      "GET /api/patients/SYN-0001/analysis/latest": () => json(200, analysisStatus({ results_run: makeRun(), latest_run: makeRun(), is_current: true })),
      "GET /api/patients/SYN-0001/claims": () => json(200, [claim, bad]) });
    renderApp("/workspace/documents?doc=DOC-P");
    const rows = await screen.findAllByTestId("claim-row");
    expect(within(rows[1]!).getByText("Failed verification")).toHaveAttribute("title", "Failed: V3_span_exact_match");
    expect(within(rows[0]!).queryByText("Failed verification")).toBeNull();
  });
});

describe("SourceCard", () => {
  it("flags a claim that failed verification and links to its evidence", () => {
    render(<MemoryRouter><SourceCard claim={{ ...claim, verified: false, failed_checks: ["V3_span_exact_match"] }} label="A" /></MemoryRouter>);
    const card = screen.getByTestId("source-card");
    expect(within(card).getByText("Failed verification")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /inspect/i })).toHaveAttribute("href", `/workspace/evidence/${claim.claim_id}`);
  });
});
