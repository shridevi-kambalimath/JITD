import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NAV_ITEMS } from "@/components/sidebar";
import { baseline, envelope, healthy, json, mockApi, noAnalysis, renderApp } from "@/test/utils";

const noDocs = { "GET /api/patients/SYN-0001/documents": () => json(200, []), ...noAnalysis };

describe("Workspace shell", () => {
  it("marks the active screen and lists every spec screen", async () => {
    mockApi({ ...baseline, ...noDocs });
    renderApp("/workspace");
    const nav = (await screen.findAllByRole("navigation", { name: "Workspace" }))[0]!;
    expect(within(nav).getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    for (const item of NAV_ITEMS) expect(within(nav).getByText(item.label)).toBeInTheDocument();
  });

  it("exit criterion: every sidebar item is an enabled link to a built screen", async () => {
    mockApi({ ...baseline, ...noDocs });
    const { router } = renderApp("/workspace/overview");
    const nav = (await screen.findAllByRole("navigation", { name: "Workspace" }))[0]!;
    expect(within(nav).queryAllByText(/^P\d$/)).toHaveLength(0);
    const titles: Record<string, string> = { Summary: "Evidence Summary" };
    for (const item of NAV_ITEMS) {
      const link = within(nav).getByRole("link", { name: item.label });
      expect(link).toHaveAttribute("href", item.to);
      await router.navigate(item.to);
      expect(await screen.findByRole("heading", { level: 1, name: titles[item.label] ?? item.label })).toBeInTheDocument();
      expect(screen.queryByText("Page not found")).toBeNull();
    }
  });

  it("reports backend health: online, database not ready, offline", async () => {
    mockApi({ ...baseline, ...noDocs });
    const a = renderApp("/workspace/overview");
    expect(await screen.findByText("Backend online")).toBeInTheDocument();
    a.unmount();

    mockApi({
      ...noDocs,
      "GET /api/health": healthy["GET /api/health"],
      "GET /api/health/ready": () => json(503, { status: "unavailable", database: { path: "x", reachable: true, schema_version: 1, expected_version: 2, error: "missing tables: claims" } }),
    });
    const b = renderApp("/workspace/overview");
    expect(await screen.findByText("Database not ready")).toBeInTheDocument();
    b.unmount();

    mockApi({
      ...noDocs,
      "GET /api/health": () => { throw new TypeError("Failed to fetch"); },
      "GET /api/health/ready": () => envelope(502, "x", "y"),
    });
    renderApp("/workspace/overview");
    expect(await screen.findByText("Backend offline")).toBeInTheDocument();
  });

  it("identifies an older backend on the API port instead of calling it offline (reported bug)", async () => {
    // exactly what a stage 1/2 backend returns: routes exist without the /api prefix
    mockApi({
      "GET /api/health": () => envelope(404, "not_found", "Not Found"),
      "GET /api/health/ready": () => envelope(404, "not_found", "Not Found"),
      "GET /api/patients/SYN-0001/documents": () => envelope(404, "not_found", "Not Found"),
    });
    renderApp("/workspace/overview");
    expect(await screen.findByText("Incompatible backend")).toBeInTheDocument();
    expect(screen.queryByText("Backend offline")).toBeNull();
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("not this version of MEDUSA-X");
    expect(banner).toHaveTextContent("python -m medusa");
    // the environment row must not show a green tick for an unknown value
    const env = screen.getByText("Environment").closest("div")!;
    expect(env).toHaveTextContent("unknown");
    expect(env.querySelector(".text-supported")).toBeNull();
    expect(screen.getByText("API").closest("div")).toHaveTextContent("wrong server (HTTP 404)");
  });

  it("tells the user how to start a stopped backend", async () => {
    mockApi({
      "GET /api/health": () => { throw new TypeError("Failed to fetch"); },
      "GET /api/health/ready": () => { throw new TypeError("Failed to fetch"); },
      "GET /api/patients/SYN-0001/documents": () => { throw new TypeError("Failed to fetch"); },
    });
    renderApp("/");
    expect(await screen.findByRole("status")).toHaveTextContent("backend is not running");
  });

  it("shows no banner when the backend is healthy", async () => {
    mockApi({ ...baseline, ...noDocs });
    renderApp("/workspace/overview");
    await screen.findByText("Backend online");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("warns when the backend is a different build and shows both versions (stale server)", async () => {
    mockApi({
      ...noDocs,
      "GET /api/health": () => json(200, { status: "ok", app: "MEDUSA-X", version: "0.0.9", environment: "development", max_upload_bytes: 5_000_000 }),
      "GET /api/health/ready": healthy["GET /api/health/ready"],
    });
    renderApp("/workspace/overview");
    expect(await screen.findByText("Version mismatch")).toBeInTheDocument();
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent(`This screen is v${__APP_VERSION__}, the backend is v0.0.9`);
    expect(screen.getAllByTestId("build-versions")[0]).toHaveTextContent(`UI v${__APP_VERSION__} · API v0.0.9`);
  });

  it("shows no banner and matching versions when both halves are the same build", async () => {
    mockApi({ ...baseline, ...noDocs });
    renderApp("/workspace/overview");
    await screen.findByText("Backend online");
    expect(screen.getAllByTestId("build-versions")[0]).toHaveTextContent(`UI v${__APP_VERSION__} · API v${__APP_VERSION__}`);
  });

  it("shows a not-found page for unknown workspace routes", async () => {
    mockApi({ ...baseline });
    renderApp("/workspace/nope");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });
});
