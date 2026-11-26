import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { DocumentSummary } from "@/api/documents";
import { baseline, envelope, json, makeDetail, makeDoc, mockApi, mockUpload, renderApp } from "@/test/utils";

const LIST = "GET /api/patients/SYN-0001/documents";
const user = () => userEvent.setup({ applyAccept: false }); // let disallowed files reach the app's own check

function file(name: string, content = "synthetic") {
  return new File([content], name, { type: "application/octet-stream" });
}

describe("Documents screen", () => {
  it("is reachable from the sidebar now that it is built", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, []) });
    const { router } = renderApp("/workspace/overview");
    const nav = (await screen.findAllByRole("navigation", { name: "Workspace" }))[0]!;
    await user().click(within(nav).getByRole("link", { name: "Documents" }));
    expect(router.state.location.pathname).toBe("/workspace/documents");
    expect(await screen.findByRole("heading", { name: "Documents" })).toBeInTheDocument();
  });

  it("offers the demo bundle when empty and lists the loaded documents", async () => {
    let docs: DocumentSummary[] = [];
    mockApi({
      ...baseline,
      [LIST]: () => json(200, docs),
      "POST /api/patients/SYN-0001/demo/load": () => {
        docs = [makeDoc("DOC-A", "processed", "Admission Note")];
        return json(200, { patient_id: "SYN-0001", loaded: docs, skipped_existing: [], rejected: [], removed: 0 });
      },
    });
    renderApp("/workspace/documents");
    await user().click(await screen.findByRole("button", { name: /load synthetic demo bundle/i }));
    expect(await within(screen.getByRole("list", { name: "Documents" })).findByText("Admission Note")).toBeInTheDocument();
  });

  it("uploads a file with progress, refreshes the list and opens the new document", async () => {
    const created = makeDoc("DOC-NEW", "processed", "Progress Note");
    let docs: DocumentSummary[] = [];
    const calls = mockApi({ ...baseline, [LIST]: () => json(200, docs), "GET /api/documents/DOC-NEW": () => json(200, makeDetail(created)) });
    const sent = mockUpload(() => { docs = [created]; return { status: 201, body: makeDetail(created) }; });
    renderApp("/workspace/documents");
    await user().upload(await screen.findByLabelText("Choose documents to upload"), file("note.txt"));
    const row = await screen.findByText(/processed as progress note/i);
    expect(row).toBeInTheDocument();
    expect(sent).toEqual(["note.txt"]);
    expect(await screen.findByTestId("extracted-text")).toHaveTextContent("Warfarin held.");
    expect(calls.filter((c) => c === LIST).length).toBeGreaterThanOrEqual(2); // list refetched after upload
  });

  it("rejects a disallowed extension locally without sending anything", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, []) });
    const sent = mockUpload(() => { throw new Error("must not upload"); });
    renderApp("/workspace/documents");
    await user().upload(await screen.findByLabelText("Choose documents to upload"), file("notes.csv"));
    const results = await screen.findByRole("list", { name: "Upload results" });
    expect(results).toHaveTextContent("Rejected, not stored");
    expect(results).toHaveTextContent("unsupported_type");
    expect(sent).toEqual([]);
  });

  it("rejects a file over the backend's size limit locally, using the limit the backend reports", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, []),
      "GET /api/health": () => json(200, { status: "ok", app: "MEDUSA-X", version: __APP_VERSION__, environment: "test", max_upload_bytes: 1000 }) });
    const sent = mockUpload(() => { throw new Error("must not upload"); });
    renderApp("/workspace/documents");
    await screen.findByText("Backend online");
    await user().upload(await screen.findByLabelText("Choose documents to upload"), file("big.txt", "x".repeat(1001)));
    const results = await screen.findByRole("list", { name: "Upload results" });
    expect(results).toHaveTextContent("payload_too_large");
    expect(results).toHaveTextContent("the limit is 1,000 bytes");
    expect(sent).toEqual([]);
  });

  it("sends a file exactly at the limit (the server stays the authority)", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, []),
      "GET /api/health": () => json(200, { status: "ok", app: "MEDUSA-X", version: __APP_VERSION__, environment: "test", max_upload_bytes: 1000 }) });
    const sent = mockUpload(() => ({ status: 413, body: { error: { code: "payload_too_large", message: "Request body exceeds the 1,000 byte limit.", details: null, request_id: "r2" } } }));
    renderApp("/workspace/documents");
    await screen.findByText("Backend online");
    await user().upload(await screen.findByLabelText("Choose documents to upload"), file("edge.txt", "x".repeat(1000)));
    const results = await screen.findByRole("list", { name: "Upload results" });
    await waitFor(() => expect(results).toHaveTextContent("Request body exceeds the 1,000 byte limit."));
    expect(sent.length).toBe(1);
  });

  it("shows each server outcome: failed processing, rejection, duplicate, network error", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, []), "GET /api/documents/DOC-SCAN": () => json(200, makeDetail(makeDoc("DOC-SCAN", "failed", null))) });
    mockUpload((f) => {
      if (f.name === "scan.pdf") return { status: 201, body: makeDetail(makeDoc("DOC-SCAN", "failed", null, { error_code: "no_text_layer", error_message: "No extractable text on any of the 1 page(s)." })) };
      if (f.name === "big.txt") return { status: 413, body: { error: { code: "file_too_large", message: "File exceeds the 5,000,000 byte limit.", details: null, request_id: "r1" } } };
      if (f.name === "copy.txt") return { status: 409, body: { error: { code: "conflict", message: "This file has already been uploaded.", details: { document_id: "DOC-OLD", status: "processed" }, request_id: "r2" } } };
      return "network-error";
    });
    renderApp("/workspace/documents");
    await user().upload(await screen.findByLabelText("Choose documents to upload"), [file("scan.pdf"), file("big.txt"), file("copy.txt"), file("lost.txt")]);
    const rows = await screen.findByRole("list", { name: "Upload results" });
    await waitFor(() => expect(rows.querySelectorAll('[data-phase="uploading"],[data-phase="processing"]')).toHaveLength(0));
    const byName = (n: string) => within(rows).getByText(n).closest("li")!;
    expect(byName("scan.pdf")).toHaveTextContent("Stored, but processing failed");
    expect(byName("scan.pdf")).toHaveTextContent("no_text_layer");
    expect(byName("big.txt")).toHaveTextContent("file_too_large");
    expect(byName("copy.txt")).toHaveTextContent("Already uploaded");
    expect(byName("copy.txt")).toHaveTextContent("existing: DOC-OLD");
    expect(byName("lost.txt")).toHaveTextContent("network_error");
  });

  it("accepts files dropped onto the drop zone", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, []), "GET /api/documents/DOC-D": () => json(200, makeDetail(makeDoc("DOC-D", "processed", "Lab Report"))) });
    const sent = mockUpload(() => ({ status: 201, body: makeDetail(makeDoc("DOC-D", "processed", "Lab Report")) }));
    renderApp("/workspace/documents");
    fireEvent.drop(await screen.findByTestId("dropzone"), { dataTransfer: { files: [file("dropped.txt")] } });
    expect(await screen.findByText(/processed as lab report/i)).toBeInTheDocument();
    expect(sent).toEqual(["dropped.txt"]);
  });

  it("shows a failed document's error, and a PDF's pages and warnings", async () => {
    const failed = makeDoc("DOC-F", "failed", null);
    const pdf = makeDoc("DOC-P", "processed", "Discharge Summary", { file_format: "pdf", page_count: 2,
      warnings: ["Page 2 has no extractable text (it may be a scanned image); its content is not included."] });
    mockApi({
      ...baseline,
      [LIST]: () => json(200, [failed, pdf]),
      "GET /api/documents/DOC-F": () => json(200, makeDetail(failed)),
      "GET /api/documents/DOC-P": () => json(200, makeDetail(pdf, { extracted_text: "Page one text", page_spans: [[0, 13], [15, 15]] })),
    });
    renderApp("/workspace/documents?doc=DOC-F");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("missing_header");
    expect(screen.getByText("No text was extracted from this document.")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Status history" }).querySelectorAll("li")).toHaveLength(3);

    await user().click(screen.getByText("Discharge Summary"));
    expect(await screen.findByText("Page 2")).toBeInTheDocument();
    expect(screen.getByText("No extractable text on this page.")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Warnings" })).toHaveTextContent("Page 2 has no extractable text");
  });

  it("filters by status", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, [makeDoc("DOC-A", "processed", "Admission Note"), makeDoc("DOC-B", "failed", null)]) });
    renderApp("/workspace/documents");
    const list = await screen.findByRole("list", { name: "Documents" });
    expect(within(list).getAllByRole("button")).toHaveLength(2);
    await user().click(screen.getByRole("tab", { name: /failed/i }));
    expect(within(screen.getByRole("list", { name: "Documents" })).getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("list", { name: "Documents" })).toHaveTextContent("missing_header");
  });

  it("deletes only after confirmation", async () => {
    let docs = [makeDoc("DOC-A", "processed", "Admission Note")];
    const calls = mockApi({
      ...baseline,
      [LIST]: () => json(200, docs),
      "GET /api/documents/DOC-A": () => json(200, makeDetail(docs[0]!)),
      "DELETE /api/documents/DOC-A": () => { docs = []; return new Response(null, { status: 204 }); },
    });
    const { router } = renderApp("/workspace/documents?doc=DOC-A");
    await user().click(await screen.findByRole("button", { name: "Delete document" }));
    await user().click(screen.getByRole("button", { name: "Cancel" }));
    expect(calls).not.toContain("DELETE /api/documents/DOC-A");

    await user().click(screen.getByRole("button", { name: "Delete document" }));
    await user().click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(calls).toContain("DELETE /api/documents/DOC-A"));
    expect(await screen.findByText("No documents yet")).toBeInTheDocument();
    expect(router.state.location.search).toBe("");
  });

  it("resets the demo after confirmation and reports what changed", async () => {
    const calls = mockApi({
      ...baseline,
      [LIST]: () => json(200, [makeDoc("DOC-A", "processed", "Admission Note")]),
      "POST /api/patients/SYN-0001/demo/reset": () => json(200, { patient_id: "SYN-0001", loaded: [1, 2, 3, 4, 5, 6], skipped_existing: [], rejected: [], removed: 8 }),
    });
    renderApp("/workspace/documents");
    await user().click(await screen.findByRole("button", { name: /reset demo data/i }));
    await user().click(screen.getByRole("button", { name: "Reset" }));
    expect(await screen.findByText(/removed 8 documents, loaded 6/i)).toBeInTheDocument();
    expect(calls).toContain("POST /api/patients/SYN-0001/demo/reset");
  });

  it("shows the reset error when the backend refuses", async () => {
    mockApi({ ...baseline, [LIST]: () => json(200, []), "POST /api/patients/SYN-0001/demo/reset": () => envelope(404, "not_found", "No synthetic demo bundle for 'SYN-0001'") });
    renderApp("/workspace/documents");
    await user().click(await screen.findByRole("button", { name: /reset demo data/i }));
    await user().click(screen.getByRole("button", { name: "Reset" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No synthetic demo bundle");
  });
});
