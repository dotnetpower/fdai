/**
 * Fallback-typewriter test for :func:`askBackendStream`.
 *
 * When the SSE endpoint fails (offline, 501, error frame, ...) the deck
 * used to dump the whole deterministic reply through ``onToken`` in ONE
 * call, which paints the answer atomically and looks non-streaming to
 * the operator. The current implementation types the fallback in through
 * :func:`chunksForTypewriter` so the deck always LOOKS live even when
 * the upstream LLM is down. This test locks that in.
 *
 * Read-only, hermetic: mocked fetch, patched typewriter cadence to 0ms.
 */
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { ViewSnapshot } from "./context";

function snap(): ViewSnapshot {
  return {
    routeId: "live",
    routeLabel: "Live cockpit",
    headline: "60 tiles",
    capturedAt: "2026-07-12T00:00:00+00:00",
    facts: [],
    records: {},
  };
}

describe("askBackendStream fallback typewriter", () => {
  beforeEach(() => {
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("offline fallback types in progressively (many onToken calls)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network offline");
      }),
    );
    const mod = await import("./backend");
    // Patch to 0ms so the test finishes instantly but the chunking loop
    // still runs and fires onToken per chunk.
    mod.fallbackTypewriter.intervalMs = 0;

    const deltas: string[] = [];
    const reply = await mod.askBackendStream("what is FDAI", snap(), [], {
      onToken: (d) => deltas.push(d),
    });

    expect(reply.text.length).toBeGreaterThan(0);
    // If the fallback dumped the whole answer at once we'd see length === 1;
    // the typewriter must produce many chunks.
    expect(deltas.length).toBeGreaterThan(2);
    // And the accumulated deltas MUST reconstruct the final reply text exactly.
    expect(deltas.join("")).toBe(reply.text);
    expect(reply.source.startsWith("deterministic (")).toBe(true);
  });

  test("501 fallback (LLM not configured) also types in progressively", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ error: "off" }), {
            status: 501,
            headers: { "content-type": "application/json" },
          }),
      ),
    );
    const mod = await import("./backend");
    mod.fallbackTypewriter.intervalMs = 0;

    const deltas: string[] = [];
    const reply = await mod.askBackendStream("hi", snap(), [], {
      onToken: (d) => deltas.push(d),
    });

    expect(deltas.length).toBeGreaterThan(2);
    expect(deltas.join("")).toBe(reply.text);
    expect(reply.source).toContain("LLM not configured");
  });

  test("abort during fallback stops emitting further chunks", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network offline");
      }),
    );
    const mod = await import("./backend");
    // Use a real (non-zero) cadence so we can abort mid-stream.
    mod.fallbackTypewriter.intervalMs = 10;

    const controller = new AbortController();
    const deltas: string[] = [];
    const p = mod.askBackendStream("what is FDAI", snap(), [], {
      onToken: (d) => {
        deltas.push(d);
        // Abort right after the first chunk lands.
        if (deltas.length === 1) controller.abort();
      },
      signal: controller.signal,
    });
    await p;

    // Aborting after 1 chunk means the typewriter loop bails out and NO
    // further chunks arrive - the deck keeps whatever streamed so far.
    expect(deltas.length).toBe(1);
  });

  test("SSE burst arrival is paced by the client-side typewriter", async () => {
    // Reasoning-family models spend N seconds thinking then flush the whole
    // answer as one TCP write. The client pacer MUST fan those tokens out
    // over time so the deck looks streaming even when all deltas land in
    // the same event-loop tick.
    const bigAnswer = "hello world foo bar baz qux quux corge grault garply";
    const sseBody = [
      `event: token\ndata: {"delta": "${bigAnswer}"}\n\n`,
      `event: done\ndata: {"answer": "${bigAnswer}", "model": "gpt-test", "latency_ms": 1500}\n\n`,
    ].join("");
    // ReadableStream feeds the whole body in ONE chunk to simulate a burst.
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(sseBody));
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(stream, {
            status: 200,
            headers: { "content-type": "text/event-stream" },
          }),
      ),
    );
    const mod = await import("./backend");
    mod.fallbackTypewriter.intervalMs = 5;

    const stamps: number[] = [];
    const t0 = Date.now();
    const reply = await mod.askBackendStream("q", snap(), [], {
      onToken: () => stamps.push(Date.now() - t0),
    });

    expect(reply.text).toBe(bigAnswer);
    // The pacer must have produced multiple paints, not one atomic drop.
    expect(stamps.length).toBeGreaterThan(2);
    // Total pacing span > 0 (paints spread over time, not all at t=0).
    const span = stamps[stamps.length - 1] - stamps[0];
    expect(span).toBeGreaterThan(0);
  });
});
