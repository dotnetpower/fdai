import { afterEach, describe, expect, it, vi } from "vitest";

import { inputViewport, wrap } from "../src/cockpit-format.js";
import {
  createInputController,
  MAX_CLI_INPUT_CODE_POINTS,
} from "../src/cockpit-input.js";
import { CockpitRenderer } from "../src/cockpit-renderer.js";
import { consumeSse, MAX_COCKPIT_SSE_FRAME_CHARS } from "../src/cockpit-sse.js";
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
      vi.fn().mockResolvedValue(
        new Response(body, {
          status: 200,
          headers: { "content-type": "text/event-stream; charset=utf-8" },
        }),
      ),
    );
    const frames: string[] = [];
    const statuses: string[] = [];

    await consumeSse(
      "https://example.com/live/stream",
      (frame) => frames.push(frame.event_id),
      (status) => statuses.push(status),
      new AbortController().signal,
      "Bearer opaque-session",
    );

    expect(frames).toEqual(["event-1"]);
    expect(statuses).toEqual(["live", "stream closed"]);
    expect(vi.mocked(fetch).mock.calls[0]?.[1]).toMatchObject({
      headers: { accept: "text/event-stream", authorization: "Bearer opaque-session" },
      redirect: "error",
    });
  });

  it("rejects a successful non-SSE response before parsing", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(body, {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    const statuses: string[] = [];

    await consumeSse(
      "https://example.com/live/stream",
      vi.fn(),
      (status) => statuses.push(status),
      new AbortController().signal,
    );

    expect(statuses).toEqual(["stream invalid content type"]);
    expect(cancel).toHaveBeenCalledOnce();
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

  it("rejects and cancels an oversized SSE frame", async () => {
    const cancel = vi.fn();
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(`event: stage\ndata: ${"x".repeat(MAX_COCKPIT_SSE_FRAME_CHARS)}\n\n`));
      },
      cancel,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(body, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        }),
      ),
    );
    const frames = vi.fn();
    const statuses: string[] = [];

    await consumeSse(
      "https://example.com/live/stream",
      frames,
      (status) => statuses.push(status),
      new AbortController().signal,
    );

    expect(frames).not.toHaveBeenCalled();
    expect(cancel).toHaveBeenCalledOnce();
    expect(statuses).toEqual(["live", "stream error: SSE frame exceeds the size limit"]);
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

  it("suppresses a duplicate terminal audit frame", () => {
    const state = createCockpitState();
    const frame = {
      event_id: "event-1",
      correlation_id: "corr-1",
      stage: "audit",
      phase: "done",
      ts: "now",
      detail: { outcome: "observed" },
    };

    expect(reduceStageFrame(state, frame, "en")).not.toBeNull();
    expect(reduceStageFrame(state, frame, "en")).toBeNull();
    expect(state.handled).toBe(1);
    expect(state.activity).toHaveLength(1);
  });

  it("contains unknown routing tiers in one bounded bucket", () => {
    const state = createCockpitState();
    reduceStageFrame(
      state,
      {
        event_id: "event-1",
        correlation_id: "corr-1",
        stage: "route",
        phase: "done",
        ts: "now",
        detail: { routed_to: "unexpected-tier", resource_type: "compute.vm" },
      },
      "en",
    );

    expect(state.byTier).toEqual({ unrouted: 1 });
    expect(state.perEvent.get("event-1")?.tier).toBe("unrouted");
  });

  it("removes terminal controls from streamed activity fields", () => {
    const state = createCockpitState();
    reduceStageFrame(
      state,
      {
        event_id: "event-1",
        correlation_id: "corr-1",
        stage: "route",
        phase: "done",
        ts: "now",
        detail: { routed_to: "t0\u001b[2J", resource_type: "compute\u0007.vm" },
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
        detail: { outcome: "observed\u001b[2J" },
      },
      "en",
    );

    expect(activity).toMatchObject({
      resource: "compute.vm",
      text: "observed[2J",
      tier: "unrouted",
    });
    expect(JSON.stringify(activity)).not.toContain("\u001b");
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

  it("bounds a pasted question without splitting Unicode code points", () => {
    const { state, renderer } = makeRenderer();
    const onData = createInputController(state, renderer, vi.fn(), vi.fn());

    onData("한".repeat(MAX_CLI_INPUT_CODE_POINTS + 10));

    expect(state.input).toHaveLength(MAX_CLI_INPUT_CODE_POINTS);
    expect(state.input.at(-1)).toBe("한");
  });

  it("keeps the terminal caret after a wide character", () => {
    const { state, renderer, writes } = makeRenderer();
    state.input = ["한", "a"];
    state.cursor = 1;

    renderer.placeCaret();

    expect(writes.at(-1)).toBe("\x1b[24;6H");
  });

  it("counts combining marks as zero-width at the hardware caret", () => {
    const { state, renderer, writes } = makeRenderer();
    state.input = ["e", "\u0301"];
    state.cursor = 2;

    renderer.placeCaret();

    expect(writes.at(-1)).toBe("\x1b[24;5H");
  });

  it("keeps a wide-character caret inside a narrow input viewport", () => {
    expect(inputViewport(["a", "한", "b", "글"], 4, 4)).toEqual({
      text: "<b글",
      caretWidth: 4,
    });
  });

  it("wraps long opaque values without exceeding the content width", () => {
    const lines = wrap("abcdefghijklmnopqrstuvwxyz", 8, 4);
    expect(lines).toEqual(["abcdefgh", "ijklmnop", "qrstuvwx", "yz"]);
  });

  it("keeps hierarchy labels while removing color in no-color mode", () => {
    const { state, writes } = makeRenderer();
    state.authMode = "local-azure-cli";
    const output = {
      rows: 24,
      columns: 80,
      write: (text: string) => {
        writes.push(text);
        return true;
      },
    } as unknown as NodeJS.WriteStream;
    const renderer = new CockpitRenderer(state, "en", output, false);

    renderer.renderAll();

    const rendered = writes.join("");
    expect(rendered).toContain("FDAI Console");
    expect(rendered).toContain("Azure CLI session");
    expect(rendered).not.toContain("\x1b[38;");
  });

  it("replaces the cockpit with a resize instruction below minimum geometry", () => {
    const writes: string[] = [];
    const output = {
      rows: 12,
      columns: 60,
      write: (text: string) => {
        writes.push(text);
        return true;
      },
    } as unknown as NodeJS.WriteStream;
    const renderer = new CockpitRenderer(createCockpitState(), "en", output);

    renderer.renderAll();

    expect(writes.join("")).toContain("Terminal too small");
    expect(writes.join("")).not.toContain("Routing mix");
  });

  it("cancels delayed header redraws when disposed", () => {
    vi.useFakeTimers();
    const { renderer, writes } = makeRenderer();
    renderer.scheduleHeader();
    renderer.dispose();
    vi.advanceTimersByTime(400);
    expect(writes).toEqual([]);
    vi.useRealTimers();
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
