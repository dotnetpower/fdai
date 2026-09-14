import { describe, expect, test, vi } from "vitest";

import {
  authenticatedSseHeaders,
  consumeSseFrames,
  isTransientSseStatus,
  shouldAdvanceSseCursor,
  shouldResetRejectedSseCursor,
  sseReconnectDelay,
} from "./sse-client";

describe("central SSE client", () => {
  test("parses bounded canonical fields and multiline data", async () => {
    const frames: object[] = [];
    await consumeSseFrames(
      new Response(
        [
          ": keepalive",
          "id: epoch-1:7",
          "event: live.activity",
          "retry: 2500",
          "dropped: 3",
          'data: {"part":',
          'data: "two"}',
          "",
          "",
        ].join("\n"),
        { headers: { "content-type": "text/event-stream" } },
      ),
      (frame) => {
        frames.push(frame);
      },
    );

    expect(frames).toEqual([{
      event: "live.activity",
      data: '{"part":\n"two"}',
      id: "epoch-1:7",
      retryMs: 2500,
      droppedBefore: 3,
    }]);
  });

  test("rejects malformed cursors and oversized pending frames", async () => {
    await expect(consumeSseFrames(
      new Response("id: bad cursor\ndata: {}\n\n", {
        headers: { "content-type": "text/event-stream" },
      }),
      () => undefined,
    )).rejects.toThrow("event id");
    await expect(consumeSseFrames(
      new Response("data: 123456", {
        headers: { "content-type": "text/event-stream" },
      }),
      () => undefined,
      { maxBufferChars: 5 },
    )).rejects.toThrow("buffer");
  });

  test("uses opaque cursors, accepted-frame advancement, and one reset", () => {
    const headers = authenticatedSseHeaders("******", "epoch-1:7");
    expect(headers.get("authorization")).toBe("******");
    expect(headers.get("last-event-id")).toBe("epoch-1:7");
    expect(shouldResetRejectedSseCursor(400, true, false)).toBe(true);
    expect(shouldResetRejectedSseCursor(400, true, true)).toBe(false);
    expect(shouldResetRejectedSseCursor(401, true, false)).toBe(false);
    expect(shouldResetRejectedSseCursor(429, true, false)).toBe(false);
    const frame = {
      event: "stage",
      data: "{}",
      id: "epoch-1:7",
      retryMs: null,
      droppedBefore: 0,
    };
    expect(shouldAdvanceSseCursor(frame, false)).toBe(false);
    expect(shouldAdvanceSseCursor(frame, true)).toBe(true);
  });

  test("honors server retry and classifies bounded transient status", () => {
    expect(sseReconnectDelay(0)).toBe(1000);
    expect(sseReconnectDelay(20)).toBe(30_000);
    expect(sseReconnectDelay(20, 2500)).toBe(2500);
    expect(isTransientSseStatus(429)).toBe(true);
    expect(isTransientSseStatus(503)).toBe(true);
    expect(isTransientSseStatus(404)).toBe(false);
  });

  test("normalizes CR and a CRLF split across network chunks", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode("event: first\rdata: one\r\r"));
        controller.enqueue(encoder.encode("event: second\r"));
        controller.enqueue(encoder.encode("\ndata: two\r\n\r\n"));
        controller.close();
      },
    });
    const frames: object[] = [];

    await consumeSseFrames(
      new Response(stream, {
        headers: { "content-type": "text/event-stream" },
      }),
      (frame) => {
        frames.push(frame);
      },
    );

    expect(frames).toMatchObject([
      { event: "first", data: "one" },
      { event: "second", data: "two" },
    ]);
  });

  test("accepts many bounded frames in one large network chunk", async () => {
    const payload = Array.from(
      { length: 40 },
      (_, index) => `event: item\ndata: ${index}\n\n`,
    ).join("");
    const frames: object[] = [];

    await consumeSseFrames(
      new Response(payload, {
        headers: { "content-type": "text/event-stream" },
      }),
      (frame) => {
        frames.push(frame);
      },
      { maxBufferChars: 32 },
    );

    expect(frames).toHaveLength(40);
  });

  test("can ignore a legacy non-cursor id without dropping its frame", async () => {
    const frames: object[] = [];

    await consumeSseFrames(
      new Response("id: Agent:2026-09-14T00:00:00+00:00\ndata: {}\n\n", {
        headers: { "content-type": "text/event-stream" },
      }),
      (frame) => {
        frames.push(frame);
      },
      { strictEventId: false },
    );

    expect(frames).toMatchObject([{ data: "{}", id: null }]);
  });

  test("cancels a stalled reader at the inactivity deadline", async () => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    const response = new Response(new ReadableStream<Uint8Array>({
      pull() {
        return new Promise(() => undefined);
      },
      cancel,
    }), {
      headers: { "content-type": "text/event-stream" },
    });
    const pending = consumeSseFrames(
      response,
      () => undefined,
      { inactivityTimeoutMs: 1000 },
    );
    const rejected = expect(pending).rejects.toThrow("inactivity");
    await vi.advanceTimersByTimeAsync(1000);
    await rejected;
    expect(cancel).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
