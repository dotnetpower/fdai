import { afterEach, describe, expect, it, vi } from "vitest";

import {
  askChat,
  DEFAULT_CHAT_TIMEOUT_MS,
  fetchSnapshot,
  fetchAuditItems,
} from "../src/data/operator-api.js";

describe("askChat", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts the shared chat wire contract and returns its grounded answer", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ answer: "9 events.", model: "shared-narrator" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const reply = await askChat("http://127.0.0.1:8010/", "status", {
      viewContext: { routeId: "cli", facts: { event_count: 9 } },
      history: [{ role: "assistant", content: "Ready." }],
      sessionId: "cli-session",
      authorization: "Bearer opaque-session",
    });

    expect(reply.answer).toBe("9 events.");
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://127.0.0.1:8010/chat");
    expect((init as RequestInit).signal).toBeInstanceOf(AbortSignal);
    expect((init as RequestInit).redirect).toBe("error");
    expect((init as RequestInit).headers).toMatchObject({
      accept: "application/json",
      authorization: "Bearer opaque-session",
      "content-type": "application/json",
    });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      prompt: "status",
      view_context: { routeId: "cli", facts: { event_count: 9 } },
      history: [{ role: "assistant", content: "Ready." }],
      session_id: "cli-session",
    });
  });

  it("rejects malformed backend responses instead of inventing an answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ model: "shared-narrator" }), { status: 200 })),
    );

    await expect(askChat("http://127.0.0.1:8010", "status")).rejects.toThrow(
      /invalid chat response/,
    );
  });

  it("rejects malformed optional chat metadata", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ answer: "ok", model: "shared-narrator", latency_ms: "1" }),
          { status: 200 },
        ),
      ),
    );

    await expect(askChat("http://127.0.0.1:8010", "status")).rejects.toThrow(
      /invalid chat response/,
    );
  });

  it("rejects chat output that becomes empty after control normalization", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ answer: "\u001b\u0007", model: "model" }), {
          status: 200,
        }),
      ),
    );

    await expect(askChat("http://127.0.0.1:8010", "status")).rejects.toThrow(
      /invalid chat response/,
    );
  });

  it("removes terminal controls from chat and error text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ answer: "safe\u001b[2J answer", model: "model\u0007name" }),
          { status: 200 },
        ),
      ),
    );

    await expect(askChat("http://127.0.0.1:8010", "status")).resolves.toMatchObject({
      answer: "safe[2J answer",
      model: "modelname",
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "bad\u001b[2J detail" }), { status: 503 }),
      ),
    );
    await expect(askChat("http://127.0.0.1:8010", "status")).rejects.toThrow(
      /bad\[2J detail/,
    );
  });

  it("surfaces bounded backend error detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "chat backend not configured" }), {
          status: 501,
          statusText: "Not Implemented",
        }),
      ),
    );

    await expect(askChat("http://127.0.0.1:8010", "status")).rejects.toThrow(
      /501 Not Implemented: chat backend not configured/,
    );
  });

  it("falls back to HTTP status when an error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("upstream unavailable", { status: 503 })),
    );

    await expect(askChat("http://127.0.0.1:8010", "status")).rejects.toThrow(/-> 503$/);
  });

  it.each([
    new TypeError("connect ECONNREFUSED"),
    new DOMException("The operation was aborted", "AbortError"),
  ])("propagates transport failure without a local fallback: %s", async (failure) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw failure;
      }),
    );

    await expect(askChat("http://127.0.0.1:8010", "status")).rejects.toBe(failure);
  });

  it("applies a bounded default timeout and accepts a shorter caller timeout", async () => {
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ answer: "ok", model: "shared-narrator" }), {
          status: 200,
        }),
      ),
    );

    await askChat("http://127.0.0.1:8010", "status");
    await askChat("http://127.0.0.1:8010", "status", { timeoutMs: 250 });

    expect(timeoutSpy).toHaveBeenNthCalledWith(1, DEFAULT_CHAT_TIMEOUT_MS);
    expect(timeoutSpy).toHaveBeenNthCalledWith(2, 250);
    timeoutSpy.mockRestore();
  });

  it("combines caller cancellation with the request timeout", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(init?.signal).toBeInstanceOf(AbortSignal);
      controller.abort();
      expect(init?.signal?.aborted).toBe(true);
      throw new DOMException("The operation was aborted", "AbortError");
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      askChat("http://127.0.0.1:8010", "status", { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("fetchSnapshot", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps explicitly unavailable projections distinct from empty results", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input);
        if (url.endsWith("/audit?limit=8")) {
          return new Response(JSON.stringify({ items: [] }), { status: 200 });
        }
        return new Response(JSON.stringify({ detail: "projection unavailable" }), {
          status: 503,
        });
      }),
    );

    await expect(fetchSnapshot("http://127.0.0.1:8010")).resolves.toEqual({
      kpi: null,
      hil: null,
      audit: [],
    });
  });

  it("rejects malformed successful projections instead of trusting TypeScript casts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input);
        if (url.endsWith("/kpi")) {
          return new Response(
            JSON.stringify({
              event_count: "500",
              shadow_share: 1,
              enforce_share: 0,
              hil_pending: 1,
              by_action_kind: {},
              by_outcome: {},
              by_tier: {},
              last_recorded_at: null,
            }),
            { status: 200 },
          );
        }
        return new Response(JSON.stringify({ detail: "not configured" }), { status: 501 });
      }),
    );

    await expect(fetchSnapshot("http://127.0.0.1:8010")).rejects.toThrow(
      /invalid KPI event_count/,
    );
  });

  it("rejects inconsistent count-only approval details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const url = String(input);
        if (url.endsWith("/hil-queue")) {
          return new Response(
            JSON.stringify({
              items: [{ event_id: "event" }],
              total: 1,
              detail_level: "count_only",
            }),
            { status: 200 },
          );
        }
        return new Response(JSON.stringify({ detail: "not configured" }), { status: 501 });
      }),
    );

    await expect(fetchSnapshot("http://127.0.0.1:8010")).rejects.toThrow(
      /inconsistent approval queue response/,
    );
  });

  it("rejects an invalid audit page limit before issuing a request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAuditItems("http://127.0.0.1:8010", 0)).rejects.toThrow(
      /audit limit/,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
