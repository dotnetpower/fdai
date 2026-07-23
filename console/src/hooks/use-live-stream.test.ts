import { describe, expect, test } from "vitest";
import {
  consumeLiveSse,
  decodeLiveStageEvent,
  isPermanentLiveStreamFailure,
  liveReconnectDelay,
  liveStreamHeaders,
  shouldPauseLiveStream,
  shouldStopLiveStream,
  type LiveStageEvent,
} from "./use-live-stream";

describe("live stream boundary", () => {
  test("adds the bearer header", () => {
    const headers = liveStreamHeaders("Bearer token");
    expect(headers.get("authorization")).toBe("Bearer token");
    expect(headers.get("accept")).toBe("text/event-stream");
  });

  test("decodes a valid stage frame and rejects malformed frames", () => {
    const event = decodeLiveStageEvent(JSON.stringify({
      event_id: "event-1",
      correlation_id: "incident-1",
      stage: "ingest",
      phase: "done",
      ts: "2026-07-16T06:00:00Z",
      detail: { tier: "t0" },
    }));
    expect(event?.stage).toBe("ingest");
    expect(event?.source).toBe("unknown");
    expect(decodeLiveStageEvent(JSON.stringify({
      event_id: "event-2",
      correlation_id: "incident-2",
      stage: "audit",
      phase: "done",
      source: "replay",
      ts: "2026-07-16T06:00:00Z",
    }))?.source).toBe("replay");
    expect(decodeLiveStageEvent("not json")).toBeNull();
    expect(decodeLiveStageEvent(JSON.stringify({ stage: "unknown" }))).toBeNull();
  });

  test("decodes named stage data while ignoring hello and keepalive", async () => {
    const payload = JSON.stringify({
      event_id: "event-1",
      correlation_id: "incident-1",
      stage: "route",
      phase: "done",
      ts: "2026-07-16T06:00:00Z",
    });
    const response = new Response(
      `event: hello\ndata: {"status":"ok"}\n\n: keepalive\n\nevent: stage\ndata: ${payload}\n\n`,
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
    const events: LiveStageEvent[] = [];
    await consumeLiveSse(response, (event) => events.push(event));
    expect(events).toHaveLength(1);
    expect(events[0]?.stage).toBe("route");
  });

  test("classifies auth failures and caps reconnect backoff", () => {
    expect(isPermanentLiveStreamFailure(401)).toBe(true);
    expect(isPermanentLiveStreamFailure(403)).toBe(true);
    expect(isPermanentLiveStreamFailure(503)).toBe(false);
    expect(liveReconnectDelay(0)).toBe(1000);
    expect(liveReconnectDelay(20)).toBe(30000);
  });

  test("keeps an opted-in background notification stream connected", () => {
    expect(shouldPauseLiveStream(true, true)).toBe(true);
    expect(shouldPauseLiveStream(true, false)).toBe(false);
    expect(shouldPauseLiveStream(false, true)).toBe(false);
  });

  test("lets an opt-in stream retry after authentication expiry", () => {
    expect(shouldStopLiveStream(401, false)).toBe(true);
    expect(shouldStopLiveStream(403, false)).toBe(true);
    expect(shouldStopLiveStream(401, true)).toBe(false);
    expect(shouldStopLiveStream(503, false)).toBe(false);
  });
});
