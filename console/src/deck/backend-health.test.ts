import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createBackendHealthProbe, BACKEND_HEALTH_REFRESH_MS } from "./backend-health";
import { parseRouter } from "./backend-normalizers";

function response(model: string) {
  return new Response(JSON.stringify({
    available: true,
    mode: "semantic-core",
    model,
    endpoint: null,
    router: {
      chose: model,
      reason: "unmeasured",
      updated_at: "2026-09-06T10:00:00Z",
      expires_at: "2026-09-06T10:05:00Z",
      interval_seconds: 300,
      candidates: [{
        deployment: model, p50_ms: null, p95_ms: null, samples: 0, history_ms: [], status: "unmeasured",
      }],
    },
  }), { status: 200, headers: { "content-type": "application/json" } });
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("coalesced backend health refresh", () => {
  it("shares requests and cached results, then reads the new selection after 30 seconds", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response("example-mini-a"))
      .mockResolvedValueOnce(response("example-mini-b"));
    vi.stubGlobal("fetch", fetchMock);
    const probe = createBackendHealthProbe(() => "/chat/health", async () => ({}), parseRouter);
    const [first, second] = await Promise.all([probe(), probe()]);
    expect(first).toEqual(second);
    expect(first.router).toMatchObject({
      updated_at: "2026-09-06T10:00:00Z",
      expires_at: "2026-09-06T10:05:00Z",
      interval_seconds: 300,
      candidates: [{ status: "unmeasured" }],
    });
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS - 1);
    expect((await probe()).model).toBe("example-mini-a");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    const [updated, concurrent] = await Promise.all([probe(), probe()]);
    expect(updated.model).toBe("example-mini-b");
    expect(updated).toEqual(concurrent);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenLastCalledWith("/chat/health", expect.objectContaining({
      method: "GET", cache: "no-store", credentials: "omit",
    }));
  });

  it("keeps the old health-only shape usable without a router", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      available: true, mode: "legacy", model: "example-mini", endpoint: null,
    }))));
    const probe = createBackendHealthProbe(() => "/chat/health", async () => ({}), parseRouter);
    expect(await probe()).toEqual({
      available: true, mode: "legacy", model: "example-mini", endpoint: null,
    });
  });

  it.each([
    ["[REDACTED]", null],
    [" [REDACTED] ", null],
    [null, null],
    ["https://chat.example.com", "https://chat.example.com"],
  ] as const)("normalizes only explicitly redacted health endpoints: %j", async (endpoint, expected) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      available: true, mode: "semantic-core", model: "example-mini", endpoint,
    }))));
    const probe = createBackendHealthProbe(() => "/chat/health", async () => ({}), parseRouter);
    expect(await probe()).toEqual({
      available: true, mode: "semantic-core", model: "example-mini", endpoint: expected,
    });
  });

  it("replaces previously ready health with unavailable state after a failed refresh", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(response("example-mini"))
      .mockRejectedValueOnce(new Error("network unavailable")));
    const probe = createBackendHealthProbe(() => "/chat/health", async () => ({}), parseRouter);
    expect((await probe()).available).toBe(true);
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS);
    expect(await probe()).toEqual({
      available: false, mode: "offline", model: null, endpoint: null,
    });
  });
});
