import { describe, expect, it } from "vitest";
import { parseRouter } from "./backend-normalizers";

const candidate = {
  deployment: "example-mini",
  p50_ms: 100,
  p95_ms: 200,
  samples: 2,
  history_ms: [100, 200],
};
const router = { chose: "example-mini", reason: "latency", candidates: [candidate] };

describe("router health metadata normalization", () => {
  it("accepts the legacy shape without fabricating freshness", () => {
    expect(parseRouter(router)).toEqual(router);
  });

  it("retains optional RFC3339 timestamps, candidate status and the configured interval", () => {
    const current = {
      ...router,
      updated_at: "2026-09-06T19:00:00+09:00",
      expires_at: "2026-09-06T10:05:00.000Z",
      interval_seconds: 300,
      candidates: [{ ...candidate, status: "measured", measured_at: "2026-09-06T10:00:00Z" }],
    };
    expect(parseRouter(current)).toEqual(current);
  });

  it.each(["measured", "unmeasured", "failed", "stale"])("retains status %s", (status) => {
    expect(parseRouter({ ...router, candidates: [{ ...candidate, status }] })?.candidates[0]?.status).toBe(status);
  });

  it("does not upgrade unknown candidate statuses or malformed measured timestamps", () => {
    for (const metadata of [
      { status: "future-state" },
      { status: "measured", measured_at: "yesterday" },
      { status: "measured", measured_at: "2026-09-06T10:00:00" },
    ]) {
      const result = parseRouter({ ...router, candidates: [{ ...candidate, ...metadata }] });
      expect(result?.candidates[0]?.status).toBe("unmeasured");
      expect(result?.candidates[0]?.measured_at).toBeUndefined();
    }
  });

  it("preserves a failed probe with no measurement timestamp", () => {
    const result = parseRouter({
      ...router, candidates: [{ ...candidate, status: "failed", measured_at: null }],
    });
    expect(result?.candidates[0]?.status).toBe("failed");
  });

  it.each([null, "not-a-date", "2026-09-06T10:00:00", 123])("drops invalid snapshot timestamps %j", (timestamp) => {
    const result = parseRouter({ ...router, updated_at: timestamp, expires_at: timestamp });
    expect(result?.updated_at).toBeUndefined();
    expect(result?.expires_at).toBeUndefined();
    expect(result?.chose).toBe("example-mini");
  });

  it.each([0, -1, NaN, Infinity, "300"])("drops invalid interval %j", (interval) => {
    expect(parseRouter({ ...router, interval_seconds: interval })?.interval_seconds).toBeUndefined();
  });

  it("rejects negative measurements and invalid sample counts instead of reporting speed", () => {
    const result = parseRouter({
      ...router,
      candidates: [{ ...candidate, p50_ms: -1, p95_ms: -2, samples: 1.5, history_ms: [-1, 100, Infinity] }],
    });
    expect(result?.candidates[0]).toEqual({
      deployment: "example-mini", p50_ms: null, p95_ms: null, samples: 0, history_ms: [100],
    });
  });
});
