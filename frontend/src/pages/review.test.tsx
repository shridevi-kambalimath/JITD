import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { FindingSummary } from "@/api/reconciliation";
import type { ReviewQueue } from "@/api/workspace";
import { baseline, emptyReviewQueue, envelope, json, makeClaim, mockApi, renderApp } from "@/test/utils";

const QUEUE = "GET /api/patients/SYN-0001/review-queue";

function finding(id: string, state: FindingSummary["state"], extra: Partial<FindingSummary> = {}): FindingSummary {
  return { finding_id: id, category: "medication", subject: id.split("-").slice(2).join(" "), high_risk: false, risk_reason: null,
    issue_types: ["medication_dose_discrepancy"], issues_by_kind: { conflict: 1 }, observation_rules: [], claim_count: 2,
    priority: state === "REVIEW_REQUIRED" ? 1 : state === "CONFLICTING_EVIDENCE" ? 2 : 3,
    review: { status: "pending_review", note: null, updated_at: null, changed_since_review: false }, state, gate_rule: "GATE-04", gate_rationale: "x", ...extra };
}

const warfarin = finding("FND-MED-warfarin", "REVIEW_REQUIRED", { high_risk: true, gate_rule: "GATE-03", issue_types: ["medication_status_conflict"] });
const metformin = finding("FND-MED-metformin", "CONFLICTING_EVIDENCE", { review: { status: "reviewed", note: "seen by ward", updated_at: "2026-11-25T10:00:00Z", changed_since_review: false } });
const amlodipine = finding("FND-MED-amlodipine", "INSUFFICIENT_EVIDENCE", { issue_types: ["unexplained_discharge_omission"], gate_rule: "GATE-06",
  review: { status: "flagged", note: null, updated_at: "2026-11-25T10:00:00Z", changed_since_review: true } });
const bad = makeClaim("CLM-BAD000000000", { entity: "atorvastatin", verified: false, failed_checks: ["V3_span_exact_match"] });

function queue(extra: Partial<ReviewQueue> = {}): ReviewQueue {
  return emptyReviewQueue({ results_run_id: "RUN-AAAAAAAAAAAA", is_current: true,
    counts: { review_required: 1, conflicting: 1, insufficient: 1, unverified_claims: 1, uncertain_dates: 1, pending_review: 2 },
    findings: [warfarin, metformin, amlodipine], unverified_claims: [bad],
    uncertain_dates: [{ claim_id: "CLM-FEV000000000", category: "symptom", entity: "fever", surface: "Fever", document_id: "DOC-A",
      document_type: "Admission Note", document_date: "2026-03-10", reason: "approximate date",
      event_date: { value: "2026-03-07", precision: "day", approximate: true, raw_text: "approximately 3 days prior to admission", basis: "relative", note: null } }],
    ...extra });
}

describe("Review Queue", () => {
  it("shows loading, then groups items by evidence state with failed claims and uncertain dates", async () => {
    mockApi({ ...baseline, [QUEUE]: () => json(200, queue()) });
    renderApp("/workspace/review");
    expect(document.querySelector("[aria-busy='true']")).not.toBeNull();
    expect(await screen.findByTestId("queue-counts")).toHaveTextContent("2 pending review · 1 review required · 1 conflicting · 1 insufficient · 1 failed verification · 1 uncertain dates");
    expect(within(screen.getByTestId("group-REVIEW_REQUIRED")).getByText("Warfarin")).toBeInTheDocument();
    expect(within(screen.getByTestId("group-REVIEW_REQUIRED")).getByText("High risk")).toBeInTheDocument();
    expect(within(screen.getByTestId("group-CONFLICTING_EVIDENCE")).getByText("Note: seen by ward")).toBeInTheDocument();
    expect(within(screen.getByTestId("group-INSUFFICIENT_EVIDENCE")).getByText(/Changed since its status was set/)).toBeInTheDocument();
    expect(screen.getByTestId("group-unverified")).toHaveTextContent("atorvastatin");
    expect(screen.getByTestId("group-unverified")).toHaveTextContent("failed V3_span_exact_match");
    const date = screen.getByTestId("uncertain-date");
    expect(date).toHaveTextContent("~2026-03-07Feverapproximate date");
    expect(screen.getByText(/it is not medical approval and never changes the evidence state/)).toBeInTheDocument();
  });

  it("persists a status change and refreshes", async () => {
    let current = queue();
    const bodies: unknown[] = [];
    mockApi({ ...baseline, [QUEUE]: () => json(200, current),
      "PUT /api/patients/SYN-0001/reviews/FND-MED-warfarin": (init?: RequestInit) => {
        const body = JSON.parse(String(init!.body));
        bodies.push(body);
        current = queue({ findings: [{ ...warfarin, review: { ...warfarin.review, status: body.status } }, metformin, amlodipine],
          counts: { ...queue().counts, pending_review: 1 } });
        return json(200, { ...warfarin.review, status: body.status });
      } });
    renderApp("/workspace/review");
    const select = await screen.findByRole("combobox", { name: "Review status for warfarin" });
    await userEvent.selectOptions(select, "flagged");
    await waitFor(() => expect(bodies).toEqual([{ status: "flagged", note: null }]));
    await waitFor(() => expect(screen.getByTestId("queue-counts")).toHaveTextContent(/^1 pending review/));
    expect(screen.getByRole("combobox", { name: "Review status for warfarin" })).toHaveValue("flagged");
  });

  it("filters by review status (changed items count as pending)", async () => {
    mockApi({ ...baseline, [QUEUE]: () => json(200, queue()) });
    renderApp("/workspace/review");
    await screen.findByTestId("queue-counts");
    await userEvent.click(screen.getByRole("button", { name: "Pending review" }));
    expect(screen.getAllByTestId("review-item").map((i) => i.textContent?.split("Medication")[0])).toEqual(["Warfarin", "Amlodipine"]);
    await userEvent.click(screen.getByRole("button", { name: "Reviewed" }));
    expect(screen.getAllByTestId("review-item")).toHaveLength(1);
    expect(within(screen.getByTestId("group-REVIEW_REQUIRED")).getByText("None with this review status.")).toBeInTheDocument();
  });

  it("navigates from an item to its sources and from a claim to its evidence", async () => {
    mockApi({ ...baseline, [QUEUE]: () => json(200, queue()) });
    const { router } = renderApp("/workspace/review");
    const item = (await screen.findAllByTestId("review-item"))[0]!;
    expect(within(item).getByRole("link", { name: "Warfarin" })).toHaveAttribute("href", "/workspace/reconciliation?finding=FND-MED-warfarin");
    await userEvent.click(within(screen.getByTestId("uncertain-date")).getByRole("link", { name: /inspect evidence/i }));
    expect(router.state.location.pathname).toBe("/workspace/evidence/CLM-FEV000000000");
  });

  it("empty before analysis, and an error state with retry", async () => {
    let fail = false;
    mockApi({ ...baseline, [QUEUE]: () => (fail ? envelope(500, "internal_error", "boom", "rid-q") : json(200, emptyReviewQueue())) });
    const a = renderApp("/workspace/review");
    expect(await screen.findByText("Nothing to review yet")).toBeInTheDocument();
    a.unmount();
    fail = true;
    renderApp("/workspace/review");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("rid-q");
    fail = false;
    await userEvent.click(within(alert).getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Nothing to review yet")).toBeInTheDocument();
  });

  it("says so when nothing needs review", async () => {
    mockApi({ ...baseline, [QUEUE]: () => json(200, queue({ findings: [], unverified_claims: [], uncertain_dates: [],
      counts: { review_required: 0, conflicting: 0, insufficient: 0, unverified_claims: 0, uncertain_dates: 0, pending_review: 0 } })) });
    renderApp("/workspace/review");
    expect(await screen.findByText("No discrepancies to review")).toBeInTheDocument();
    expect(screen.getByTestId("group-unverified")).toHaveTextContent("None: every claim passed its hard checks.");
  });
});
