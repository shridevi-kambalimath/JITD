import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { baseline, envelope, json, mockApi, renderApp } from "@/test/utils";

describe("Landing page", () => {
  it("explains the workflow and enters the workspace", async () => {
    mockApi({ ...baseline, "GET /api/patients/SYN-0001/documents": () => json(200, []) });
    const { router } = renderApp("/");
    expect(screen.getByRole("heading", { name: /reconstruct what the records actually say/i })).toBeInTheDocument();
    const workflow = screen.getByRole("region", { name: /evidence-driven workflow/i });
    expect(within(workflow).getAllByRole("listitem")).toHaveLength(7);
    await userEvent.click(screen.getByRole("link", { name: /enter workspace/i }));
    expect(router.state.location.pathname).toBe("/workspace/overview");
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
  });

  it("loads the synthetic demo through the backend, then opens the overview", async () => {
    let docs: unknown[] = [];
    const calls = mockApi({
      ...baseline,
      "POST /api/patients/SYN-0001/demo/load": () => {
        docs = [{ document_id: "DOC-0000000000000001", patient_id: "SYN-0001", filename: "01_admission_note.txt", file_format: "txt",
          size_bytes: 10, sha256: "x", status: "processed", document_type: "Admission Note", document_date: "2026-03-10",
          source_document_id: null, extraction_method: "utf8_text", page_count: null, char_count: 10, warnings: [],
          error_code: null, error_message: null, uploaded_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }];
        return json(200, { patient_id: "SYN-0001", loaded: docs, skipped_existing: [], rejected: [] });
      },
      "GET /api/patients/SYN-0001/documents": () => json(200, docs),
    });
    const { router } = renderApp("/");
    await userEvent.click(screen.getByRole("button", { name: /open synthetic demo workspace/i }));
    expect(await screen.findByText("Admission Note")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/workspace/overview");
    expect(calls).toContain("POST /api/patients/SYN-0001/demo/load");
  });

  it("shows the backend error with its code and request id when the demo cannot load", async () => {
    mockApi({ ...baseline, "POST /api/patients/SYN-0001/demo/load": () => envelope(404, "not_found", "No synthetic demo bundle", "rid-9") });
    const { router } = renderApp("/");
    await userEvent.click(screen.getByRole("button", { name: /open synthetic demo workspace/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No synthetic demo bundle");
    expect(alert).toHaveTextContent("rid-9");
    expect(router.state.location.pathname).toBe("/");
  });
});
