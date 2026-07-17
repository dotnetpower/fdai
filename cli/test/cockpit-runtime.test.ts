import { afterEach, describe, expect, it, vi } from "vitest";

import { createInputController } from "../src/cockpit-input.js";
import { CockpitRenderer } from "../src/cockpit-renderer.js";
import { consumeSse } from "../src/cockpit-sse.js";
import { createCockpitState, reduceStageFrame } from "../src/cockpit-state.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("consumeSse", () => {
  it("reassembles split stage frames and ignores malformed data", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: stage\ndata: {"event_id":"event-1",'));
        controller.enqueue(
          encoder.encode(
            '"correlation_id":"corr-1","stage":"route","phase":"done","ts":"now"}\n\n' +
              "event: stage\ndata: not-json\n\n",
          ),
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(body, { status: 200 })),
    );
    const frames: string[] = [];
    const statuses: string[] = [];

    await consumeSse(
      "https://example.com/live/stream",
      (frame) => frames.push(frame.event_id),
      (status) => statuses.push(status),
      new AbortController().signal,
    );

    expect(frames).toEqual(["event-1"]);
    expect(statuses).toEqual(["live"]);
  });

  it("reports an HTTP stream status without reading a missing body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
    const statuses: string[] = [];

    await consumeSse(
      "https://example.com/live/stream",
      vi.fn(),
      (status) => statuses.push(status),
      new AbortController().signal,
    );

    expect(statuses).toEqual(["stream 503"]);
  });
});

describe("reduceStageFrame", () => {
  it("carries route and verify state into the terminal audit activity", () => {
    const state = createCockpitState();
    reduceStageFrame(
      state,
      {
        event_id: "event-1",
        correlation_id: "corr-1",
        stage: "route",
        phase: "done",
        ts: "now",
        detail: { routed_to: "t2", resource_type: "compute.vm" },
      },
      "en",
    );
    reduceStageFrame(
      state,
      {
        event_id: "event-1",
        correlation_id: "corr-1",
        stage: "verify",
        phase: "done",
        ts: "now",
        detail: { tier: "t1" },
      },
      "en",
    );

    const activity = reduceStageFrame(
      state,
      {
        event_id: "event-1",
        correlation_id: "corr-1",
        stage: "audit",
        phase: "done",
        ts: "now",
        detail: { decision: "auto", outcome: "executed" },
      },
      "en",
    );

    expect(activity).toMatchObject({ resource: "compute.vm", tier: "t1" });
    expect(state.handled).toBe(1);
    expect(state.autoApplied).toBe(1);
    expect(state.byTier).toEqual({ t2: 1 });
    expect(state.resourceCounts).toEqual({ "compute.vm": 1 });
    expect(state.perEvent.size).toBe(0);
  });

  it("counts failed phases without inventing an activity", () => {
    const state = createCockpitState();
    const activity = reduceStageFrame(
      state,
      {
        event_id: "event-1",
        correlation_id: "corr-1",
        stage: "verify",
        phase: "failed",
        ts: "now",
      },
      "en",
    );

    expect(activity).toBeNull();
    expect(state.errors).toBe(1);
  });
});

describe("cockpit input and rendering", () => {
  const makeRenderer = () => {
    const writes: string[] = [];
    const output = {
      rows: 24,
      columns: 80,
      write: (text: string) => {
        writes.push(text);
        return true;
      },
    } as unknown as NodeJS.WriteStream;
    const state = createCockpitState();
    return { state, renderer: new CockpitRenderer(state, "en", output), writes };
  };

  it("inserts composed Korean text as Unicode code points before submit", () => {
    const { state, renderer } = makeRenderer();
    const submitted: string[] = [];
    const onData = createInputController(
      state,
      renderer,
      () => submitted.push(state.input.join("")),
      vi.fn(),
    );

    onData("한글\n");

    expect(state.input).toEqual(["한", "글"]);
    expect(state.cursor).toBe(2);
    expect(submitted).toEqual(["한글"]);
  });

  it("keeps the terminal caret after a wide character", () => {
    const { state, renderer, writes } = makeRenderer();
    state.input = ["한", "a"];
    state.cursor = 1;

    renderer.placeCaret();

    expect(writes.at(-1)).toBe("\x1b[24;6H");
  });

  it("preserves history navigation and word deletion keys", () => {
    const { state, renderer } = makeRenderer();
    state.history.push("focus network");
    const onData = createInputController(state, renderer, vi.fn(), vi.fn());

    onData("\x1b[A");
    expect(state.input.join("")).toBe("focus network");
    onData("\x17");
    expect(state.input.join("")).toBe("focus ");
    onData("\x1b[B");
    expect(state.input).toEqual([]);
    expect(state.historyIndex).toBeNull();
  });
});
