import { afterEach, describe, expect, test, vi } from "vitest";
import { DetectionHistoryCache, decodeHistoryPage } from "./detection-history";

const filters = { q: "", evidence: "all", delivery: "all", from: "", to: "" };
function response(next: string | null = null) {
  return {
    execution_authority: false,
    lifecycle: { source: "postgresql:state_kv:analyzer-finding-receipt",
      observed_at: null, retained_from: null, receipt_count: 0, receipt_limit: 350,
      target_count: 0, assessment_count: 0,
      evidence_counts: { complete: 0, incomplete: 0, conflicting: 0, missed: 0 }, targets: [] },
    pagination: { snapshot_at: "2026-11-03T00:00:00Z", total_receipts: 0, total_assessments: 0,
      observed_at: null, retained_from: null,
      total_targets: 0, evidence_counts: { complete: 0, incomplete: 0, conflicting: 0, missed: 0 },
      offset: 0, page_size: 50, next_cursor: next },
  };
}
afterEach(() => vi.useRealTimers());

describe("retained history page cache", () => {
  test("reuses visited pages only within the client, filter and size scope", async () => {
    const small = response();
    small.pagination.page_size = 25;
    const panel = vi.fn().mockResolvedValue(response())
      .mockResolvedValueOnce(response()).mockResolvedValueOnce(response()).mockResolvedValueOnce(small);
    const cache = new DetectionHistoryCache({ panel });
    await cache.load(filters, null, 50);
    await cache.load(filters, null, 50);
    expect(panel).toHaveBeenCalledTimes(1);
    await cache.load({ ...filters, q: "older" }, null, 50);
    await cache.load(filters, null, 25);
    expect(panel).toHaveBeenCalledTimes(3);
    cache.clear();
    await cache.load(filters, null, 50);
    expect(panel).toHaveBeenCalledTimes(4);
    await new DetectionHistoryCache({ panel }).load(filters, null, 50);
    expect(panel).toHaveBeenCalledTimes(5);
  });
  test("does not cache failed reads and expires the snapshot explicitly", async () => {
    vi.useFakeTimers();
    const panel = vi.fn().mockRejectedValueOnce(new Error("unavailable")).mockResolvedValue(response());
    const cache = new DetectionHistoryCache({ panel });
    await expect(cache.load(filters, null, 50)).rejects.toThrow("unavailable");
    await cache.load(filters, null, 50);
    vi.advanceTimersByTime(5 * 60_000);
    await expect(cache.load(filters, "cursor", 50)).rejects.toThrow("expired");
    await cache.load(filters, null, 50);
    expect(panel).toHaveBeenCalledTimes(3);
  });
  test("rejects malformed, truncated and authority-bearing pages", () => {
    expect(() => decodeHistoryPage({ ...response(), execution_authority: true })).toThrow("authority");
    expect(() => decodeHistoryPage(response("invalid-next-on-empty"))).toThrow("reconcile");
    const truncated = response();
    truncated.pagination.total_assessments = 600;
    expect(() => decodeHistoryPage(truncated)).toThrow("reconcile");
  });
});
