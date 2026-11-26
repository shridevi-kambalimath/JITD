import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { FindingDetail, FindingSummary, ReconciliationResponse } from "@/api/reconciliation";
import { baseline, emptyReconciliation, json, makeClaim, makeDoc, mockApi, renderApp } from "@/test/utils";

const LIST = "GET /api/patients/SYN-0001/documents";
const RECON = "GET /api/patients/SYN-0001/reconciliation";
const docs = [makeDoc("DOC-A", "processed", "Admission Note")];

function summary(id: string, extra: Partial<FindingSummary> = {}): FindingSummary {
  return { finding_id: id, category: "medication", subject: id.split("-").pop()!, high_risk: false, risk_reason: null, issue_types: [],
    issues_by_kind: {}, observation_rules: [], claim_count: 2, priority: null,
    review: { status: "pending_review", note: null, updated_at: null, changed_since_review: false },
    state: "EVIDENCE_SUPPORTED", gate_rule: "GATE-07", gate_rationale: "2 verified source claim(s); no conflict or gap detected by the rules.", ...extra };
}

const warfarinS = summary("FND-MED-warfarin", { high_risk: true, risk_reason: "drug class 'anticoagulant' is configured as high risk",
  issue_types: ["medication_status_conflict"], issues_by_kind: { conflict: 1 }, priority: 1, claim_count: 3,
  state: "REVIEW_REQUIRED", gate_rule: "GATE-03", gate_rationale: "Records conflict (medication_status_conflict) on a high-risk item. The system does not choose between records." });
const ckdS = summary("FND-DX-chronic-kidney-disease", { category: "diagnosis", subject: "chronic kidney disease",
  issue_types: ["diagnosis_status_conflict"], issues_by_kind: { conflict: 1 }, priority: 2, state: "CONFLICTING_EVIDENCE", gate_rule: "GATE-04",
  review: { status: "reviewed", note: "seen", updated_at: "2026-11-25T10:00:00Z", changed_since_review: true } });
const pneumoniaS = summary("FND-DX-pneumonia", { category: "diagnosis", subject: "pneumonia", observation_rules: ["DX-EVOL-01"] });

function recon(extra: Partial<ReconciliationResponse> = {}): ReconciliationResponse {
  return emptyReconciliation({ results_run_id: "RUN-AAAAAAAAAAAA", is_current: true,
    counts: { findings: 3, with_issues: 2, conflict: 2, gap: 0, integrity: 0, pending_review: 2,
      REVIEW_REQUIRED: 1, CONFLICTING_EVIDENCE: 1, INSUFFICIENT_EVIDENCE: 0, EVIDENCE_SUPPORTED: 1 }, findings: [warfarinS, ckdS, pneumoniaS], ...extra });
}

const held = makeClaim("CLM-H", { document_type: "Progress Note", document_date: "2026-03-12", attributes: { kind: "medication", action: "held", list_context: "inpatient" },
  source: { document_id: "DOC-P", passage_id: "DOC-P:P010", section: "PLAN", char_start: 0, char_end: 50, evidence_text: "Warfarin held due to upper gastrointestinal bleed.",
    entity_char_start: 0, entity_char_end: 8 } });
const active = makeClaim("CLM-A", { document_type: "Imported Medication List", document_date: "2026-03-14",
  attributes: { kind: "medication", action: "listed_active", list_context: "imported" },
  source: { document_id: "DOC-I", passage_id: "DOC-I:P002", section: "MEDICATION LIST", char_start: 100, char_end: 141,
    evidence_text: "Warfarin 5 mg orally once daily - Active.", entity_char_start: 100, entity_char_end: 108 } });
const admission = makeClaim("CLM-ADM", { attributes: { kind: "medication", action: "listed_active", list_context: "admission" } });

const warfarinD: FindingDetail = { ...warfarinS, claims: [admission, held, active], missing_claim_ids: [], results_run_id: "RUN-AAAAAAAAAAAA", is_current: true,
  issues: [{ issue_type: "medication_status_conflict", kind: "conflict", rule_id: "MED-STATUS-01",
    description: "Warfarin documented as held (Progress Note, 2026-03-12) but listed as active (Imported Medication List, 2026-03-14). No restart is documented between these dates.",
    claim_ids: ["CLM-H", "CLM-A"] }],
  observations: [], investigation: [{ rule_id: "INV-01", query: "warfarin restarted resumed recommenced", scope: "section", hits: [],
    outcome: "No uncaptured 'restarted' evidence for warfarin in 3 section(s) searched." }] };
const pneumoniaD: FindingDetail = { ...pneumoniaS, claims: [], missing_claim_ids: [], results_run_id: "RUN-AAAAAAAAAAAA", is_current: true, issues: [],
  observations: [{ rule_id: "DX-EVOL-01", text: "Documented sequence: possible (Admission Note, 2026-03-10); absent (Radiology Report, 2026-03-11). A 'possible' assertion followed by a definite one is diagnostic evolution, not a conflict.", claim_ids: [] }],
  investigation: [] };
const ckdD: FindingDetail = { ...ckdS, claims: [], missing_claim_ids: [], results_run_id: "RUN-AAAAAAAAAAAA", is_current: true,
  issues: [{ issue_type: "diagnosis_status_conflict", kind: "conflict", rule_id: "DX-STATUS-01", description: "Chronic kidney disease documented as present and as absent.", claim_ids: [] }],
  observations: [], investigation: [] };

function api(extra = {}) {
  return mockApi({ ...baseline, [LIST]: () => json(200, docs), [RECON]: () => json(200, recon()),
    "GET /api/patients/SYN-0001/reconciliation/FND-MED-warfarin": () => json(200, warfarinD),
    "GET /api/patients/SYN-0001/reconciliation/FND-DX-pneumonia": () => json(200, pneumoniaD),
    "GET /api/patients/SYN-0001/reconciliation/FND-DX-chronic-kidney-disease": () => json(200, ckdD), ...extra });
}

describe("Reconciliation", () => {
  it("is reachable from the sidebar", async () => {
    api();
    const { router } = renderApp("/workspace/overview");
    const nav = (await screen.findAllByRole("navigation", { name: "Workspace" }))[0]!;
    await userEvent.click(within(nav).getByRole("link", { name: /reconciliation/i }));
    expect(router.state.location.pathname).toBe("/workspace/reconciliation");
  });

  it("asks for an analysis first", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, docs) });
    renderApp("/workspace/reconciliation");
    expect(await screen.findByText("Nothing reconciled yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });

  it("lists potential discrepancies first and opens the most urgent one with both sources side by side", async () => {
    api();
    renderApp("/workspace/reconciliation");
    expect(await screen.findByTestId("reconciliation-counts")).toHaveTextContent("3 subjects: 1 review required · 1 conflicting evidence · 0 insufficient evidence · 1 evidence-supported · 2 pending review");
    const issuesList = screen.getByRole("list", { name: "Needs attention" });
    const rows = within(issuesList).getAllByTestId("finding-row");
    expect(rows.map((r) => r.textContent?.slice(0, 22))).toEqual(["WarfarinHigh riskMedic", "Chronic kidney disease"]);
    expect(within(rows[0]!).getByText("Review required")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Conflicting evidence")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Changed since review")).toBeInTheDocument();
    expect(screen.getByText("Evidence-supported (1)")).toBeInTheDocument();

    const panel = await screen.findByLabelText("Finding Warfarin");
    expect(panel).toHaveTextContent("High risk: drug class 'anticoagulant' is configured as high risk (prototype setting, not a clinical standard)");
    expect(within(panel).getByTestId("finding-state")).toHaveTextContent("Review requiredGATE-03");
    expect(within(panel).getByTestId("gate-rationale")).toHaveTextContent("The system does not choose between records.");
    const issue = within(panel).getByTestId("issue");
    expect(issue).toHaveTextContent("Records differ");
    expect(issue).toHaveTextContent("Medication status differs");
    expect(issue).toHaveTextContent("No restart is documented between these dates.");
    const cards = within(within(issue).getByTestId("issue-sources")).getAllByTestId("source-card");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent("AProgress Note2026-03-12");
    expect(cards[0]).toHaveTextContent("held · inpatient list");
    expect(cards[1]).toHaveTextContent("BImported Medication List2026-03-14");
    expect(within(cards[0]!).getByTestId("source-passage").querySelector("mark")!.textContent).toBe("Warfarin");
    expect(within(cards[1]!).getByRole("link", { name: /open document/i })).toHaveAttribute("href", "/workspace/documents?doc=DOC-I&claim=CLM-A");
    expect(within(panel).getByRole("region", { name: "Other records for this subject" })).toHaveTextContent("(1)");
    expect(panel).toHaveTextContent("No uncaptured 'restarted' evidence for warfarin");
    expect(document.body.textContent!.toLowerCase()).not.toMatch(/incorrect|wrong record|is wrong|error in the record/);
  });

  it("explains subjects that were examined and not flagged", async () => {
    api();
    renderApp("/workspace/reconciliation");
    await screen.findByLabelText("Finding Warfarin");
    await userEvent.click(screen.getByText("Evidence-supported (1)"));
    await userEvent.click(screen.getByRole("button", { name: /pneumonia/i }));
    const panel = await screen.findByLabelText("Finding Pneumonia");
    expect(panel).toHaveTextContent("No potential discrepancy found by the rules");
    expect(within(panel).getByRole("region", { name: "Examined and not flagged" })).toHaveTextContent("Diagnostic evolution");
    expect(within(panel).queryByRole("region", { name: "Review" })).toBeNull();
  });

  it("never shows the previously selected finding's state while the next one loads", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    api({ "GET /api/patients/SYN-0001/reconciliation/FND-DX-chronic-kidney-disease": async () => { await gate; return json(200, ckdD); } });
    renderApp("/workspace/reconciliation");
    await screen.findByLabelText("Finding Warfarin");
    await userEvent.click(screen.getByRole("button", { name: /chronic kidney disease/i }));
    expect(await screen.findByTestId("finding-loading")).toBeInTheDocument();
    expect(screen.queryByLabelText("Finding Warfarin")).toBeNull();
    expect(screen.queryByTestId("finding-state")).toBeNull();
    release();
    const panel = await screen.findByLabelText("Finding Chronic kidney disease");
    expect(within(panel).getByTestId("finding-state")).toHaveTextContent("Conflicting evidence");
  });

  it("shows a finding only when it comes from the same analysis run as the list", async () => {
    api({ "GET /api/patients/SYN-0001/reconciliation/FND-MED-warfarin": () => json(200, { ...warfarinD, results_run_id: "RUN-OLDOLDOLDOLD" }) });
    renderApp("/workspace/reconciliation");
    expect(await screen.findByTestId("finding-loading")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("finding-state")).toBeNull();
    expect(screen.queryByLabelText("Finding Warfarin")).toBeNull();
  });

  it("records a review status with a note and says it is not medical approval", async () => {
    const bodies: unknown[] = [];
    let current = warfarinD;
    api({
      "GET /api/patients/SYN-0001/reconciliation/FND-MED-warfarin": () => json(200, current),
      "PUT /api/patients/SYN-0001/reviews/FND-MED-warfarin": (init?: RequestInit) => {
        const body = JSON.parse(String(init!.body));
        bodies.push(body);
        current = { ...warfarinD, review: { ...body, updated_at: "2026-11-25T12:00:00Z", changed_since_review: false } };
        return json(200, current.review);
      },
    });
    renderApp("/workspace/reconciliation");
    const review = await screen.findByRole("region", { name: "Review" });
    expect(review).toHaveTextContent("It is not medical approval and does not change the finding or the records.");
    const save = within(review).getByRole("button", { name: /save review status/i });
    expect(save).toBeDisabled();
    await userEvent.click(within(review).getByRole("radio", { name: "Flagged for follow-up" }));
    await userEvent.type(within(review).getByRole("textbox"), "  Ask ward about restart  ");
    await userEvent.click(save);
    await waitFor(() => expect(bodies).toEqual([{ status: "flagged", note: "Ask ward about restart" }]));
    expect(await within(review).findByText("Saved")).toBeInTheDocument();
  });

  it("asks for another look when a finding changed after review", async () => {
    api();
    renderApp("/workspace/reconciliation?finding=FND-DX-chronic-kidney-disease");
    const review = await screen.findByRole("region", { name: "Review" });
    expect(review).toHaveTextContent("This item changed after its status was set");
    expect(within(review).getByRole("radio", { name: "Reviewed" })).toBeChecked();
  });

  it("warns when results are stale", async () => {
    api({ [RECON]: () => json(200, recon({ is_current: false, stale_reason: "Documents changed." })) });
    renderApp("/workspace/reconciliation");
    expect(await screen.findByText("These results may be out of date: Documents changed.")).toBeInTheDocument();
  });
});
