import { afterEach, describe, expect, test, vi } from "vitest";
import { setChatAuth } from "./auth";
import {
  BusyClientError,
  cancelBusyCurrent,
  decodeBusyState,
  inspectBusy,
  setBusyMode,
  submitBusy,
} from "./busy-input-client";

vi.mock("../config", () => ({
  loadConfig: () => ({ operatorApiBaseUrl: "http://example.invalid" }),
}));

const sessionId = "user:example:screen";
const state = {
  session_id: sessionId,
  mode: "queue",
  active: true,
  revision: 2,
  pending: [{
    input: { input_id: "input-one", expires_at: "2026-09-26T12:00:00Z" },
    sequence: 0,
    disposition: "queued",
    status: "pending",
  }],
};

afterEach(() => {
  vi.unstubAllGlobals();
  setChatAuth(null);
});

describe("authenticated busy input client", () => {
  test("reads only exact-session, bounded authoritative state through the chat auth seam", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(state), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    setChatAuth({
      getAuthorizationHeader: async () => "Bearer synthetic",
    } as Parameters<typeof setChatAuth>[0]);
    expect(await inspectBusy(sessionId)).toEqual({
      sessionId,
      mode: "queue",
      active: true,
      revision: 2,
      pending: [{
        inputId: "input-one",
        sequence: 0,
        disposition: "queued",
        expiresAt: "2026-09-26T12:00:00Z",
      }],
    });
    expect(fetcher).toHaveBeenCalledWith(
      `http://example.invalid/chat/busy-input?session_id=${encodeURIComponent(sessionId)}`,
      expect.objectContaining({
        headers: { authorization: "Bearer synthetic" },
        cache: "no-store",
      }),
    );
    expect(fetcher.mock.calls[0]?.[1]).not.toHaveProperty("principal_id");
  });

  test.each([
    { ...state, session_id: "other" },
    { ...state, mode: "unknown" },
    { ...state, revision: -1 },
    { ...state, pending: [{ ...state.pending[0], input: { input_id: "input-one" } }] },
    { ...state, pending: [{ ...state.pending[0], status: "consumed" }] },
    { ...state, pending: [...state.pending, state.pending[0]] },
    { ...state, pending: Array(33).fill(state.pending[0]) },
    { ...state, active: "true" },
  ])("rejects mismatched or malformed GET without a usable state", async (payload) => {
    expect(decodeBusyState(payload, sessionId)).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
    await expect(inspectBusy(sessionId)).rejects.toMatchObject({ reason: "unavailable" });
  });

  test.each([404, 503, 202, 409])("fails closed on GET HTTP %i", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status })));
    await expect(inspectBusy(sessionId)).rejects.toMatchObject({
      reason: status === 409 ? "conflict" : status === 202 ? "pending" : "unavailable",
    });
  });

  test("rejects oversized or invalid UTF-8 projections before decoding state", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(" ".repeat(64_001), { status: 200 }))
      .mockResolvedValueOnce(new Response(new Uint8Array([0xff]), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(inspectBusy(sessionId)).rejects.toMatchObject({ reason: "unavailable" });
    await expect(inspectBusy(sessionId)).rejects.toMatchObject({ reason: "unavailable" });
  });

  test("submits prose without a principal, never interprets HTTP 202 as a disposition", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 202 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(submitBusy(sessionId, "input-one", "Follow up")).resolves.toBeUndefined();
    const [url, options] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://example.invalid/chat/busy-input");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body as string)).toEqual({
      session_id: sessionId,
      input_id: "input-one",
      idempotency_key: "input-one",
      content: "Follow up",
      kind: "prose",
    });
    expect(options.headers).toEqual({ "content-type": "application/json" });
  });

  test("rejects oversized input and conflicts without retry", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 409 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(submitBusy(sessionId, "input", "a".repeat(4001)))
      .rejects.toBeInstanceOf(BusyClientError);
    expect(fetcher).not.toHaveBeenCalled();
    await expect(submitBusy(sessionId, "input", "text"))
      .rejects.toMatchObject({ reason: "conflict" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  test("uses only revision-bound mode and conversational cancel routes", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 202 }));
    vi.stubGlobal("fetch", fetcher);
    const observed = decodeBusyState(state, sessionId)!;
    await setBusyMode(observed, "steer");
    await cancelBusyCurrent(observed);
    expect(fetcher.mock.calls.map((call: unknown[]) => {
      const [url, options] = call as [string, RequestInit];
      return [url, options.method, JSON.parse(options.body as string)];
    })).toEqual([
      ["http://example.invalid/chat/busy-input/mode", "PUT",
        { session_id: sessionId, mode: "steer", revision: 2 }],
      ["http://example.invalid/chat/busy-input/cancel-current", "POST",
        { session_id: sessionId, revision: 2 }],
    ]);
  });
});
