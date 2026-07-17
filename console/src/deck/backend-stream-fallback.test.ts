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

  test("background-tab fallback completes without timer throttling", async () => {
    vi.stubGlobal("document", { visibilityState: "hidden" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network offline");
      }),
    );
    const mod = await import("./backend");
    mod.fallbackTypewriter.intervalMs = 10_000;

    const deltas: string[] = [];
    const reply = await mod.askBackendStream("what is FDAI", snap(), [], {
      onToken: (delta) => deltas.push(delta),
    });

    expect(deltas.join("")).toBe(reply.text);
    expect(reply.source).toBe("deterministic (offline)");
  });

  test("unfocused-window fallback also skips cosmetic pacing", async () => {
    vi.stubGlobal("document", { visibilityState: "visible", hasFocus: () => false });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network offline");
      }),
    );
    const mod = await import("./backend");
    mod.fallbackTypewriter.intervalMs = 10_000;

    const deltas: string[] = [];
    const reply = await mod.askBackendStream("what is FDAI", snap(), [], {
      onToken: (delta) => deltas.push(delta),
    });

    expect(deltas.join("")).toBe(reply.text);
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
    const reply = await p;

    // Aborting after 1 chunk means the typewriter loop bails out and NO
    // further chunks arrive - the deck keeps whatever streamed so far.
    expect(deltas.length).toBe(1);
    expect(reply.text).toBe(deltas.join(""));
    expect(reply.source).toBe("stopped");
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
    mod.streamBurstPacer.intervalMs = 5;

    const stamps: number[] = [];
    const t0 = Date.now();
    const reply = await mod.askBackendStream("q", snap(), [], {
      onToken: () => stamps.push(Date.now() - t0),
    });

    expect(reply.text).toBe(bigAnswer);
    // The pacer must have produced multiple paints, not one atomic drop.
    expect(stamps.length).toBeGreaterThan(2);
    expect(stamps.length).toBeGreaterThanOrEqual(5);
    // Total pacing span > 0 (paints spread over time, not all at t=0).
    const span = stamps[stamps.length - 1]! - stamps[0]!;
    expect(span).toBeGreaterThan(0);
  });

  test("small incremental SSE delta bypasses cosmetic pacing", async () => {
    const answer = "ready";
    const body =
      `event: token\ndata: ${JSON.stringify({ delta: answer })}\n\n` +
      `event: done\ndata: ${JSON.stringify({ answer, model: "gpt-test" })}\n\n`;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    const timer = vi.spyOn(globalThis, "setTimeout");
    const mod = await import("./backend");
    mod.streamBurstPacer.intervalMs = 10_000;

    const deltas: string[] = [];
    const reply = await mod.askBackendStream("q", snap(), [], {
      onToken: (delta) => deltas.push(delta),
    });

    expect(deltas).toEqual([answer]);
    expect(reply.text).toBe(answer);
    expect(timer).not.toHaveBeenCalled();
  });

  test("accepts CRLF-framed SSE from an intermediary", async () => {
    const answer = "CRLF stream completed";
    const body =
      `event: token\r\ndata: {"delta":"${answer}"}\r\n\r\n` +
      `event: done\r\ndata: {"answer":"${answer}","model":"gpt-test"}\r\n\r\n`;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    const mod = await import("./backend");
    mod.fallbackTypewriter.intervalMs = 0;

    const deltas: string[] = [];
    const reply = await mod.askBackendStream("q", snap(), [], {
      onToken: (delta) => deltas.push(delta),
    });

    expect(deltas.join("")).toBe(answer);
    expect(reply.text).toBe(answer);
    expect(reply.source).toBe("llm:gpt-test");
  });

  test("flushes a UTF-8 code point split across network chunks", async () => {
    const prefix = new TextEncoder().encode('event: token\ndata: {"delta":"');
    const suffix = new TextEncoder().encode('"}\n\nevent: done\ndata: {"answer":"ok","model":"gpt-test"}\n\n');
    const glyph = new TextEncoder().encode("\uD55C");
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array([...prefix, ...glyph.slice(0, 2)]));
        controller.enqueue(new Uint8Array([...glyph.slice(2), ...suffix]));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(stream, { status: 200 })));
    const mod = await import("./backend");
    mod.fallbackTypewriter.intervalMs = 0;

    const deltas: string[] = [];
    await mod.askBackendStream("q", snap(), [], { onToken: (delta) => deltas.push(delta) });

    expect(deltas.join("")).toBe("\uD55C");
  });

  test("labels tokens followed by an error frame as a partial answer", async () => {
    const body =
      'event: token\ndata: {"delta":"Partial answer"}\n\n' +
      'event: error\ndata: {"detail":"upstream reset"}\n\n';
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    const mod = await import("./backend");
    mod.fallbackTypewriter.intervalMs = 0;

    const reply = await mod.askBackendStream("q", snap(), [], { onToken: () => undefined });

    expect(reply.text).toBe("Partial answer");
    expect(reply.source).toBe("partial (stream error)");
  });

  test("applies one monotonic verified revision to the provisional answer", async () => {
    const frames = [
      ["status", { seq: 1, revision: 0, phase: "evidence_resolving", label: "Checking evidence" }],
      ["status", {
        seq: 2,
        revision: 0,
        phase: "generating",
        label: "Drafting answer",
        sources: [{
          kind: "operational",
          label: "Operational evidence",
          detail: "Memory pressure",
          side_effect_class: "read",
        }],
      }],
      ["token", { seq: 3, revision: 0, delta: "Unsupported draft" }],
      // Same sequence is a replay and MUST be ignored.
      ["token", { seq: 3, revision: 0, delta: " duplicate" }],
      ["provisional", { seq: 4, revision: 0, answer: "Unsupported draft" }],
      ["verification", {
        seq: 5,
        revision: 0,
        phase: "verifying",
        label: "Verifying answer",
        completed: 0,
        total: 1,
      }],
      ["verification", {
        seq: 6,
        revision: 0,
        phase: "corrected",
        label: "Verification corrected",
        completed: 1,
        total: 1,
      }],
      ["revision", {
        seq: 7,
        revision: 1,
        answer: "Verified canonical answer",
        status: "corrected",
      }],
      // A later frame carrying the same revision is stale and MUST be ignored.
      ["revision", {
        seq: 8,
        revision: 1,
        answer: "Stale replacement",
        status: "corrected",
      }],
      ["done", {
        seq: 9,
        revision: 1,
        answer: "Verified canonical answer",
        model: "gpt-test",
        latency_ms: 42,
        verification: {
          status: "corrected",
          authority: "server_read_model",
          checks_completed: 1,
          checks_total: 1,
          evidence_refs: ["incident:corr-1"],
          reason_code: "grounded_rca",
          claims: [{
            claim_id: "c001",
            kind: "id",
            text: "corr-1",
            span: { start: 0, end: 6 },
            raw_value: "corr-1",
            normalized_value: "corr-1",
            unit: null,
            anchors: ["correlation"],
            status: "supported",
            evidence_refs: ["incident:corr-1"],
            reason_code: null,
          }],
          failed_claim_ids: [],
          evidence_manifest: {
            schema_version: 1,
            manifest_id: "sha256:abc",
            authority: "server_read_model",
            route_id: "incidents",
            captured_at: "2026-07-15T00:00:00Z",
            complete: true,
            source_entry_count: 1,
            entries: [{
              ref: "incident:corr-1",
              path: "/incident/correlation_id",
              field: "correlation_id",
              kind: "id",
              raw_value: "corr-1",
              normalized_value: "corr-1",
              anchors: ["correlation"],
            }],
          },
        },
      }],
    ] as const;
    const body = frames
      .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
      .join("");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    const mod = await import("./backend");
    mod.fallbackTypewriter.intervalMs = 0;

    const deltas: string[] = [];
    const progress: string[] = [];
    let generatingSources: readonly { readonly kind: string; readonly label: string }[] = [];
    const revisions: Array<{ answer: string; revision: number; status: string }> = [];
    const callbackOrder: string[] = [];
    const reply = await mod.askBackendStream("q", snap(), [], {
      onToken: (delta) => {
        deltas.push(delta);
        callbackOrder.push("token");
      },
      onProgress: (item) => {
        progress.push(item.phase);
        if (item.phase === "generating") generatingSources = item.sources ?? [];
      },
      onRevision: (answer, revision, status) => {
        revisions.push({ answer, revision, status });
        callbackOrder.push("revision");
      },
    });

    expect(deltas.join("")).toBe("Unsupported draft");
    expect(progress).toEqual([
      "evidence_resolving",
      "generating",
      "verifying",
      "corrected",
    ]);
    expect(generatingSources).toEqual([
      expect.objectContaining({
        kind: "operational",
        label: "Operational evidence",
      }),
    ]);
    expect(revisions).toEqual([
      { answer: "Verified canonical answer", revision: 1, status: "corrected" },
    ]);
    expect(callbackOrder.at(-1)).toBe("revision");
    expect(callbackOrder.slice(0, -1).every((item) => item === "token")).toBe(true);
    expect(reply.text).toBe("Verified canonical answer");
    expect(reply.verification).toEqual({
      status: "corrected",
      authority: "server_read_model",
      checks_completed: 1,
      checks_total: 1,
      evidence_refs: ["incident:corr-1"],
      reason_code: "grounded_rca",
      claims: [{
        claim_id: "c001",
        kind: "id",
        text: "corr-1",
        span: { start: 0, end: 6 },
        raw_value: "corr-1",
        normalized_value: "corr-1",
        unit: null,
        anchors: ["correlation"],
        status: "supported",
        evidence_refs: ["incident:corr-1"],
        reason_code: null,
      }],
      failed_claim_ids: [],
      evidence_manifest: {
        schema_version: 1,
        manifest_id: "sha256:abc",
        authority: "server_read_model",
        route_id: "incidents",
        captured_at: "2026-07-15T00:00:00Z",
        complete: true,
        source_entry_count: 1,
        entries: [{
          ref: "incident:corr-1",
          path: "/incident/correlation_id",
          field: "correlation_id",
          kind: "id",
          raw_value: "corr-1",
          normalized_value: "corr-1",
          anchors: ["correlation"],
        }],
      },
    });
  });

  test("downgrades malformed claim artifacts to unverified", async () => {
    const body = [
      'event: token\ndata: {"seq":1,"delta":"Draft 12"}\n\n',
      'event: done\ndata: {"seq":2,"answer":"Draft 12","model":"gpt-test",' +
        '"verification":{"status":"consistent","authority":"client_snapshot",' +
        '"checks_completed":1,"checks_total":1,"evidence_refs":[],' +
        '"reason_code":"screen_claims_supported","claims":"not-an-array",' +
        '"failed_claim_ids":[]}}\n\n',
    ].join("");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    const mod = await import("./backend");
    mod.fallbackTypewriter.intervalMs = 0;

    const reply = await mod.askBackendStream("q", snap(), [], { onToken: () => undefined });

    expect(reply.verification?.status).toBe("unverified");
    expect(reply.verification?.reason_code).toBe("malformed_verification_artifact");
  });

});
