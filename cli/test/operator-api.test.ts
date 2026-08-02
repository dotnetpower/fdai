import { afterEach, describe, expect, it, vi } from "vitest";

import { askChat, DEFAULT_CHAT_TIMEOUT_MS } from "../src/data/operator-api.js";

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
    });

    expect(reply.answer).toBe("9 events.");
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://127.0.0.1:8010/chat");
    expect((init as RequestInit).signal).toBeInstanceOf(AbortSignal);
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
});
