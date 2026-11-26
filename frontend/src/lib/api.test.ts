import { describe, expect, it, vi } from "vitest";
import { ApiError, apiRequest } from "@/lib/api";
import { envelope, json } from "@/test/utils";

function respond(r: Response | Error) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
    if (r instanceof Error) throw r;
    return r;
  });
}

describe("apiRequest", () => {
  it("prefixes /api and returns parsed JSON", async () => {
    respond(json(200, { ok: 1 }));
    await expect(apiRequest("/x")).resolves.toEqual({ ok: 1 });
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe("/api/x");
  });

  it("turns the backend error envelope into an ApiError with code and request id", async () => {
    respond(envelope(409, "conflict", "Already uploaded", "rid-42"));
    const err = await apiRequest("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: "conflict", message: "Already uploaded", requestId: "rid-42" });
  });

  it("reports a network failure as status 0", async () => {
    respond(new TypeError("Failed to fetch"));
    const err = (await apiRequest("/x").catch((e) => e)) as ApiError;
    expect(err.isNetworkError).toBe(true);
    expect(err.code).toBe("network_error");
  });

  it("treats a dev-proxy 502 as backend unreachable", async () => {
    respond(new Response("Bad Gateway", { status: 502 }));
    expect(((await apiRequest("/x").catch((e) => e)) as ApiError).isNetworkError).toBe(true);
  });

  it("returns undefined for 204 and the body for allowed error statuses", async () => {
    respond(new Response(null, { status: 204 }));
    await expect(apiRequest("/x", { method: "DELETE" })).resolves.toBeUndefined();
    respond(json(503, { status: "unavailable" }));
    await expect(apiRequest("/x", { allowStatus: [503] })).resolves.toEqual({ status: "unavailable" });
  });

  it("rejects a non-JSON success body instead of returning garbage", async () => {
    respond(new Response("<html>", { status: 200 }));
    await expect(apiRequest("/x")).rejects.toMatchObject({ code: "invalid_response" });
  });

  it("sends JSON bodies with a content type", async () => {
    respond(json(200, {}));
    await apiRequest("/x", { method: "PUT", body: { status: "reviewed" } });
    const init = vi.mocked(fetch).mock.calls[0]?.[1];
    expect(init?.body).toBe('{"status":"reviewed"}');
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });
});
