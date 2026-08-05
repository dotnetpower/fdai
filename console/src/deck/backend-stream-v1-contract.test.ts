import { afterEach, expect, test, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("rejects v1 frames with mismatched request ids or missing sequences", async () => {
  for (const variant of ["mismatch", "missing-sequence"] as const) {
    vi.resetModules();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input, init) => {
        const request = JSON.parse(String(init?.body)) as { request_id: string };
        const payload = {
          v: 1,
          request_id: variant === "mismatch" ? "another-request" : request.request_id,
          ...(variant === "mismatch" ? { seq: 1 } : {}),
          answer: "must not be accepted",
          model: "gpt-test",
        };
        const validToken = {
          v: 1,
          request_id: request.request_id,
          seq: 1,
          revision: 0,
          delta: "must be discarded",
        };
        return new Response(
          `event: token\ndata: ${JSON.stringify(validToken)}\n\n` +
            `event: done\ndata: ${JSON.stringify(payload)}\n\n`,
        );
      }),
    );
    const backend = await import("./backend");
    backend.fallbackTypewriter.intervalMs = 0;
    const tokens: string[] = [];

    const reply = await backend.askBackendStream("q", null, [], {
      onToken: (token) => tokens.push(token),
    });

    expect(reply.source).toBe("partial (sequence gap)");
    expect(reply.text).toBe("");
    expect(tokens).toEqual([]);
    expect(reply.verification).toBeUndefined();
  }
});
