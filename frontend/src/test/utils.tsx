import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import type { AnalysisRun, AnalysisStatus, Claim, LlmConfig } from "@/api/analysis";
import type { DocumentDetail, DocumentSummary } from "@/api/documents";
import type { ReconciliationResponse } from "@/api/reconciliation";
import type { TimelineEntry, TimelineResponse } from "@/api/timeline";
import type { EvidenceSummary, OverviewResponse, ReviewQueue } from "@/api/workspace";
import { routes } from "@/App";
import { WorkspaceProvider } from "@/context/workspace";

type Handler = (init?: RequestInit) => Response | Promise<Response>;

export function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

export function envelope(status: number, code: string, message: string, requestId = "req-test-1"): Response {
  return json(status, { error: { code, message, details: null, request_id: requestId } }, { "X-Request-ID": requestId });
}

export const healthy = {
  "GET /api/health": () => json(200, { status: "ok", app: "MEDUSA-X", version: __APP_VERSION__, environment: "test", max_upload_bytes: 5_000_000 }),
  "GET /api/health/ready": () =>
    json(200, { status: "ready", database: { path: "x.db", reachable: true, schema_version: 2, expected_version: 2, error: null } }),
};

// ---------------------------------------------------------------- analysis fixtures
export function llmConfig(extra: Partial<LlmConfig> = {}): LlmConfig {
  return { provider: "none", model: null, status: "disabled", reason: null, api_key_set: false, custom_base_url: false, ...extra };
}

export function makeRun(extra: Partial<AnalysisRun> = {}): AnalysisRun {
  return { run_id: "RUN-AAAAAAAAAAAA", patient_id: "SYN-0001", status: "completed", started_at: "2026-11-25T09:00:00Z",
    finished_at: "2026-11-25T09:00:01Z", extractor: "rules", llm_status: "disabled", llm_error: null, document_fingerprint: "f",
    stats: { documents_analyzed: 2, passages: 10, claims_total: 5, claims_by_method: { rule: 5, llm: 0 }, documents_skipped: [], llm: {} },
    error: null, ...extra };
}

export function analysisStatus(extra: Partial<AnalysisStatus> = {}): AnalysisStatus {
  return { patient_id: "SYN-0001", latest_run: null, results_run: null, is_current: false, stale_reason: null, ...extra };
}

export function makeClaim(id: string, extra: Partial<Claim> = {}): Claim {
  return { claim_id: id, patient_id: "SYN-0001", claim_type: "medication", entity: "warfarin", surface: "Warfarin",
    attributes: { kind: "medication" },
    source: { document_id: "DOC-A", passage_id: "DOC-A:P004", section: "PLAN", char_start: 58, char_end: 72, evidence_text: "Warfarin held.",
      entity_char_start: 58, entity_char_end: 66 },
    document_date: "2026-03-10", document_type: "Progress Note",
    event_date: { value: null, precision: "unknown", approximate: false, raw_text: null, basis: "none", note: null },
    extraction_method: "rule:med-1", ...extra };
}

export function emptyTimeline(extra: Partial<TimelineResponse> = {}): TimelineResponse {
  return { patient_id: "SYN-0001", results_run_id: null, is_current: false, stale_reason: null, total: 0, excluded_unverified: 0, by_basis: {}, by_category: {},
    entries: [], ...extra };
}

export function makeEntry(id: string, extra: Partial<TimelineEntry> = {}): TimelineEntry {
  return { claim_id: id, category: "diagnosis", label: "Diagnosis documented as present: hypertension", entity: "hypertension",
    quote: "Hypertension", assertion: "present", extraction_method: "rule:dx-1", ordering_basis: "document_date", when: "2026-03-10",
    when_precision: "day", when_approximate: false,
    event_date: { value: null, precision: "unknown", approximate: false, raw_text: null, basis: "none", note: null },
    document_date: "2026-03-10", document_id: "DOC-A", document_type: "Admission Note", section: "PAST MEDICAL HISTORY",
    passage_id: "DOC-A:P003", ...extra };
}

export function emptyReconciliation(extra: Partial<ReconciliationResponse> = {}): ReconciliationResponse {
  return { patient_id: "SYN-0001", results_run_id: null, is_current: false, stale_reason: null,
    counts: { findings: 0, with_issues: 0, conflict: 0, gap: 0, integrity: 0, pending_review: 0 }, findings: [], ...extra };
}

export function makeOverview(extra: Partial<OverviewResponse> = {}): OverviewResponse {
  return { patient_id: "SYN-0001", documents: { total: 0, processed: 0, failed: 0, in_progress: 0 }, analysis: analysisStatus(),
    claims: { total: 0, rule: 0, llm: 0, verified: 0, failed_verification: 0 },
    timeline: { entries: 0, by_event_date: 0, by_document_date: 0, undated: 0, excluded_unverified: 0 },
    reconciliation: { subjects: 0, needs_attention: 0, pending_review: 0, EVIDENCE_SUPPORTED: 0, CONFLICTING_EVIDENCE: 0, INSUFFICIENT_EVIDENCE: 0, REVIEW_REQUIRED: 0 },
    llm: llmConfig(), ...extra };
}

/** An analysed demo-like overview: 6 documents, 48 claims, 17 subjects. */
export function analysedOverview(extra: Partial<OverviewResponse> = {}): OverviewResponse {
  return makeOverview({ documents: { total: 6, processed: 6, failed: 0, in_progress: 0 },
    analysis: analysisStatus({ latest_run: makeRun(), results_run: makeRun(), is_current: true }),
    claims: { total: 48, rule: 48, llm: 0, verified: 48, failed_verification: 0 },
    timeline: { entries: 48, by_event_date: 18, by_document_date: 30, undated: 0, excluded_unverified: 0 },
    reconciliation: { subjects: 17, needs_attention: 7, pending_review: 7, EVIDENCE_SUPPORTED: 10, CONFLICTING_EVIDENCE: 2, INSUFFICIENT_EVIDENCE: 3, REVIEW_REQUIRED: 2 },
    ...extra });
}

export function emptyReviewQueue(extra: Partial<ReviewQueue> = {}): ReviewQueue {
  return { patient_id: "SYN-0001", results_run_id: null, is_current: false, stale_reason: null,
    counts: { review_required: 0, conflicting: 0, insufficient: 0, unverified_claims: 0, uncertain_dates: 0, pending_review: 0 },
    findings: [], unverified_claims: [], uncertain_dates: [], ...extra };
}

export function emptySummary(extra: Partial<EvidenceSummary> = {}): EvidenceSummary {
  return { patient_id: "SYN-0001", results_run_id: null, is_current: false, stale_reason: null, generated_at: "2026-11-25T10:00:00Z",
    disclaimer: "Synthetic demonstration data. MEDUSA-X does not diagnose.", sections: [], ...extra };
}

/** Analysis endpoints for a patient that has never been analysed, with the LLM switched off. */
export const noAnalysis = {
  "GET /api/analysis/config": () => json(200, llmConfig()),
  "GET /api/patients/SYN-0001/analysis/latest": () => json(200, analysisStatus()),
  "GET /api/patients/SYN-0001/claims": () => json(200, []),
  "GET /api/patients/SYN-0001/timeline": () => json(200, emptyTimeline()),
  "GET /api/patients/SYN-0001/reconciliation": () => json(200, emptyReconciliation()),
  "GET /api/patients/SYN-0001/overview": () => json(200, makeOverview()),
  "GET /api/patients/SYN-0001/review-queue": () => json(200, emptyReviewQueue()),
  "GET /api/patients/SYN-0001/summary": () => json(200, emptySummary()),
};

/** Health plus empty analysis: the default backend for page tests. */
export const baseline = { ...healthy, ...noAnalysis };

/**
 * Replaces fetch with a router keyed by "METHOD /path" (query string ignored). Unhandled requests fail
 * loudly so a test can never pass by accident on an unexpected call. Returns the call log.
 */
export function mockApi(handlers: Record<string, Handler>) {
  // keys without query strings; .urls keeps the full request URLs for tests that check parameters
  const calls: string[] & { urls: string[] } = Object.assign([] as string[], { urls: [] as string[] });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const key = `${(init?.method ?? "GET").toUpperCase()} ${url.split("?")[0]}`;
    calls.push(key);
    calls.urls.push(url);
    const handler = handlers[key];
    if (!handler) throw new Error(`Unhandled request in test: ${key}`);
    return handler(init);
  });
  return calls;
}

export function renderApp(path: string, { patientId = "SYN-0001" }: { patientId?: string } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <WorkspaceProvider initialPatientId={patientId}>
        <RouterProvider router={router} />
      </WorkspaceProvider>
    </QueryClientProvider>,
  );
  return { ...utils, router, queryClient };
}

// ---------------------------------------------------------------- documents fixtures
export function makeDoc(id: string, status: DocumentSummary["status"], type: string | null, extra: Partial<DocumentSummary> = {}): DocumentSummary {
  return { document_id: id, patient_id: "SYN-0001", filename: `${id.toLowerCase()}.txt`, file_format: "txt", size_bytes: 1200, sha256: "x",
    status, document_type: type, document_date: type ? "2026-03-10" : null, source_document_id: null, extraction_method: "utf8_text",
    page_count: null, char_count: 120, warnings: [], error_code: status === "failed" ? "missing_header" : null,
    error_message: status === "failed" ? "No document header found." : null, uploaded_at: "2026-11-25T08:00:00Z", updated_at: "2026-11-25T08:00:00Z",
    ...extra };
}

export function makeDetail(summary: DocumentSummary, extra: Partial<DocumentDetail> = {}): DocumentDetail {
  const processed = summary.status === "processed";
  return { ...summary,
    metadata: processed ? { "DOCUMENT TYPE": summary.document_type ?? "", "PATIENT ID": "SYN-0001", "DOCUMENT DATE": summary.document_date ?? "" } : {},
    extracted_text: processed ? "DOCUMENT TYPE: Progress Note\nPATIENT ID: SYN-0001\n---\nPLAN:\nWarfarin held." : null,
    page_spans: [],
    events: [{ status: "uploaded", detail: "txt file", at: "2026-11-25T08:00:00Z" }, { status: "processing", detail: null, at: "2026-11-25T08:00:01Z" },
      { status: summary.status, detail: processed ? "120 characters extracted" : "missing_header: No document header found.", at: "2026-11-25T08:00:02Z" }],
    ...extra };
}

// ---------------------------------------------------------------- uploads (XMLHttpRequest)
type UploadReply = { status: number; body: unknown } | "network-error";

/** Replaces XMLHttpRequest. Each send emits progress 50% then 100%, then the reply the responder chooses. */
export function mockUpload(responder: (file: File) => UploadReply) {
  const sent: string[] = [];
  class FakeXHR {
    upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    status = 0;
    responseText = "";
    open() {}
    setRequestHeader() {}
    getResponseHeader(name: string) { return name.toLowerCase() === "x-request-id" ? "rid-upload" : null; }
    abort() {}
    send(form: FormData) {
      const file = form.get("file") as File;
      sent.push(file.name);
      setTimeout(() => {
        this.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
        this.upload.onprogress?.({ lengthComputable: true, loaded: 100, total: 100 });
        const reply = responder(file);
        if (reply === "network-error") return this.onerror?.();
        this.status = reply.status;
        this.responseText = JSON.stringify(reply.body);
        this.onload?.();
      }, 0);
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  return sent;
}
