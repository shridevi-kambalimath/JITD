import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { analysedOverview, baseline, envelope, json, mockApi, renderApp } from "@/test/utils";

/** Phase 10 drills on the frontend: the backend disappears mid-session, or its database is not ready. */
describe("Recovery", () => {
  it("backend stopped mid-session: explains it, then reconnects and refreshes every panel by itself", async () => {
    let up = false;
    const down = () => Promise.reject(new TypeError("Failed to fetch"));
    mockApi({
      ...baseline,
      "GET /api/health": () => (up ? baseline["GET /api/health"]() : down()),
      "GET /api/health/ready": () => (up ? baseline["GET /api/health/ready"]() : down()),
      "GET /api/patients/SYN-0001/documents": () => (up ? json(200, []) : down()),
      "GET /api/patients/SYN-0001/overview": () => (up ? json(200, analysedOverview()) : down()),
    });
    renderApp("/workspace/overview");
    expect(await screen.findByText("The MEDUSA-X backend is not running")).toBeInTheDocument();
    expect(screen.getByText(/This page reconnects automatically/)).toBeInTheDocument();
    up = true; // the developer restarts the backend
    await waitFor(() => expect(screen.queryByText("The MEDUSA-X backend is not running")).toBeNull(), { timeout: 6000 });
    // panels that failed while it was away refetched without a reload
    await waitFor(() => expect(screen.getByTestId("stage-Claims & events")).toHaveTextContent("48"), { timeout: 6000 });
    expect(screen.getByText("Backend online")).toBeInTheDocument();
  }, 15_000);

  it("database not ready: says so and what the next action does", async () => {
    mockApi({ ...baseline,
      "GET /api/health/ready": () => json(503, { status: "unavailable", database: { path: "x.db", reachable: false, schema_version: -1, expected_version: 5, error: "database file does not exist" } }),
      "GET /api/patients/SYN-0001/documents": () => json(200, []),
      "GET /api/patients/SYN-0001/overview": () => envelope(503, "database_recreated", "The database file was missing or replaced, so an empty one was created.", "rid-db") });
    renderApp("/workspace/overview");
    expect(await screen.findByText("The database is not ready: database file does not exist")).toBeInTheDocument();
    expect(screen.getByText(/your next action creates an empty one; then load the demo bundle again/)).toBeInTheDocument();
    const alert = (await screen.findAllByRole("alert")).find((a) => a.textContent?.includes("database_recreated"))!;
    expect(within(alert).getByText(/an empty one was created/)).toBeInTheDocument();
  });
});
