import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { analysisKeys, replaceAnalysisResults } from "@/api/analysis";

describe("replaceAnalysisResults", () => {
  it("drops cached results no screen shows, keeps the ones on screen for refetch, and leaves other data alone", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const shown = [...analysisKeys.all, "reconciliation", "SYN-0001"];
    const hidden = [...analysisKeys.all, "finding", "SYN-0001", "FND-REF-endoscopy-report"];
    qc.setQueryData(hidden, { state: "INSUFFICIENT_EVIDENCE" });
    qc.setQueryData(["documents", "list", "SYN-0001"], ["DOC-A"]);
    let fetched = 0;
    const observer = new QueryObserver(qc, { queryKey: shown, queryFn: async () => ++fetched, staleTime: Infinity });
    const unsubscribe = observer.subscribe(() => {});
    await vi.waitFor(() => expect(qc.getQueryData(shown)).toBe(1));

    await replaceAnalysisResults(qc);

    expect(qc.getQueryData(hidden)).toBeUndefined();
    await vi.waitFor(() => expect(fetched).toBe(2)); // the one on screen was refetched, not dropped
    expect(qc.getQueryData(shown)).toBe(2);
    expect(qc.getQueryData(["documents", "list", "SYN-0001"])).toEqual(["DOC-A"]);
    unsubscribe();
  });
});
