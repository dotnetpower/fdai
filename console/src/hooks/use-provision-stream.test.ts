import { afterEach, describe, expect, test, vi } from "vitest";
import {
  consumeProvisionSse,
  decodeProvisionEvent,
  isPermanentProvisionFailure,
  provisionReconnectDelay,
  provisionStreamHeaders,
  type ProvisionEvent,
} from "./use-provision-stream";

/**
 * `decodeProvisionEvent` is the trust boundary between the SSE wire and the
 * console state: the producer is not fully trusted, so malformed or hostile
 * payloads must be rejected or sanitised rather than corrupting the view.
 */

afterEach(() => {
  vi.useRealTimers();
});

describe("decodeProvisionEvent", () => {
  test("decodes a well-formed progress event", () => {
    const ev = decodeProvisionEvent(
      JSON.stringify({ type: "provision.progress", fraction: 0.5, node: "a" }),
    );
    expect(ev?.phase).toBe("progress");
    expect(ev?.fraction).toBe(0.5);
    expect(ev?.node).toBe("a");
  });

  test("rejects non-JSON and non-object payloads", () => {
    expect(decodeProvisionEvent("not json")).toBeNull();
    expect(decodeProvisionEvent("42")).toBeNull();
    expect(decodeProvisionEvent("null")).toBeNull();
  });

  test("rejects a non-provision or unknown-phase type", () => {
    expect(decodeProvisionEvent(JSON.stringify({ type: "audit.entry" }))).toBeNull();
    expect(decodeProvisionEvent(JSON.stringify({ type: "provision.bogus" }))).toBeNull();
    expect(decodeProvisionEvent(JSON.stringify({ type: "provision.ready" }))).toBeNull();
  });

  test("ignores out-of-range / non-finite fraction", () => {
    for (const bad of [1.5, -0.1, Number.NaN, Number.POSITIVE_INFINITY]) {
      const ev = decodeProvisionEvent(
        JSON.stringify({ type: "provision.progress", fraction: bad }),
      );
      expect(ev).not.toBeNull();
      expect(ev?.fraction).toBeUndefined();
    }
  });

  test("accepts boundary fractions 0 and 1", () => {
    expect(decodeProvisionEvent(JSON.stringify({ type: "provision.done", fraction: 1 }))?.fraction).toBe(1);
    expect(
      decodeProvisionEvent(JSON.stringify({ type: "provision.progress", fraction: 0 }))?.fraction,
    ).toBe(0);
  });

  test("decodes a bounded durable status snapshot", () => {
    const event = decodeProvisionEvent(JSON.stringify({
      type: "provision.snapshot",
      run_id: "run.test",
      sequence: 9,
      attempt: 1,
      state: "applying",
      current_stage: "initial-inventory",
      stages_completed: 4,
      stages_total: 5,
      last_progress_at: "2026-08-31T00:00:00+00:00",
      reason_code: null,
      ready: false,
      readiness: {
        database: true,
        semantic: true,
        models: true,
        runtime: true,
        inventory: false,
        system: false,
      },
      stages: [
        { id: "database", status: "completed" },
        { id: "semantic-defaults", status: "completed" },
        { id: "model-deployments", status: "completed" },
        { id: "console", status: "completed" },
        { id: "initial-inventory", status: "active" },
      ],
      inventory: {
        resources_observed: 12,
        resources_expected: 20,
        pages_completed: 2,
        pages_expected: 4,
      },
    }));

    expect(event?.phase).toBe("snapshot");
    expect(event?.ready).toBe(false);
    expect(event?.inventory?.resources_expected).toBe(20);
  });

  test("rejects inconsistent snapshot totals", () => {
    expect(decodeProvisionEvent(JSON.stringify({
      type: "provision.snapshot",
      run_id: "run.test",
      sequence: 1,
      attempt: 1,
      state: "applying",
      current_stage: "database",
      stages_completed: 2,
      stages_total: 1,
      last_progress_at: "2026-08-31T00:00:00+00:00",
      ready: false,
      readiness: {
        database: false,
        semantic: false,
        models: false,
        runtime: false,
        inventory: false,
        system: false,
      },
      stages: [{ id: "database", status: "active" }],
    }))).toBeNull();
  });

  test("rejects readiness that is not backed by every gate and stage", () => {
    expect(decodeProvisionEvent(JSON.stringify({
      type: "provision.snapshot",
      run_id: "run.test",
      sequence: 2,
      attempt: 1,
      state: "ready",
      current_stage: "system-readiness",
      stages_completed: 1,
      stages_total: 1,
      last_progress_at: "2026-08-31T00:00:00+00:00",
      ready: true,
      readiness: {
        database: true,
        semantic: true,
        models: true,
        runtime: true,
        inventory: true,
        system: false,
      },
      stages: [{ id: "system-readiness", status: "completed" }],
    }))).toBeNull();
  });

  test("rejects component readiness without its completed stage", () => {
    expect(decodeProvisionEvent(JSON.stringify({
      type: "provision.snapshot",
      run_id: "run.test",
      sequence: 2,
      attempt: 1,
      state: "applying",
      current_stage: "database",
      stages_completed: 0,
      stages_total: 1,
      last_progress_at: "2026-08-31T00:00:00+00:00",
      ready: false,
      readiness: {
        database: true,
        semantic: false,
        models: false,
        runtime: false,
        inventory: false,
        system: false,
      },
      stages: [{ id: "database", status: "active" }],
    }))).toBeNull();
  });

  test("rejects a failed run whose current stage still claims completion", () => {
    expect(decodeProvisionEvent(JSON.stringify({
      type: "provision.snapshot",
      run_id: "run.test",
      sequence: 2,
      attempt: 1,
      state: "failed",
      current_stage: "database",
      stages_completed: 1,
      stages_total: 1,
      last_progress_at: "2026-08-31T00:00:00+00:00",
      reason_code: "migration-failed",
      ready: false,
      readiness: {
        database: true,
        semantic: false,
        models: false,
        runtime: false,
        inventory: false,
        system: false,
      },
      stages: [{ id: "database", status: "completed" }],
    }))).toBeNull();
  });
});

describe("fetch SSE boundary", () => {
  test("adds the bearer header without putting it in the URL", () => {
    const headers = provisionStreamHeaders("Bearer token");
    expect(headers.get("authorization")).toBe("Bearer token");
    expect(headers.get("accept")).toBe("text/event-stream");
    expect(headers.get("last-event-id")).toBeNull();
    expect(provisionStreamHeaders(null, 42).get("last-event-id")).toBe("42");
  });

  test("decodes provision data frames and ignores hello/keepalive frames", async () => {
    const response = new Response(
      "event: hello\ndata: {\"status\":\"ok\"}\n\n: keepalive\n\ndata: {\"type\":\"provision.progress\",\"fraction\":0.5}\n\n",
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
    const events: ProvisionEvent[] = [];
    await consumeProvisionSse(response, (event) => events.push(event));
    expect(events).toHaveLength(1);
    expect(events[0]?.fraction).toBe(0.5);
  });

  test("preserves the durable SSE replay cursor", async () => {
    const response = new Response(
      'id: 42\ndata: {"type":"provision.progress","fraction":0.5}\n\n',
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
    const events: ProvisionEvent[] = [];

    await consumeProvisionSse(response, (event) => events.push(event));

    expect(events[0]?.stream_id).toBe(42);
  });

  test("advances the replay cursor across invalid semantic frames", async () => {
    const response = new Response(
      'id: 42\nevent: invalid\ndata: {"error":"frame_too_large"}\n\n',
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
    const events: ProvisionEvent[] = [];
    const cursors: number[] = [];

    await consumeProvisionSse(
      response,
      (event) => events.push(event),
      1_000,
      (cursor) => cursors.push(cursor),
    );

    expect(events).toEqual([]);
    expect(cursors).toEqual([42]);
  });

  test("rejects an unauthorized stream response", async () => {
    await expect(consumeProvisionSse(new Response("unauthorized", { status: 401 }), () => {}))
      .rejects.toThrow(/HTTP 401/);
  });

  test("parses a CRLF event boundary split across stream chunks", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"provision.done","fraction":1}\r'));
        controller.enqueue(encoder.encode("\n\r\n"));
        controller.close();
      },
    });
    const events: ProvisionEvent[] = [];
    await consumeProvisionSse(
      new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
      (event) => events.push(event),
    );
    expect(events[0]?.phase).toBe("done");
  });

  test("classifies permanent auth failures and caps reconnect backoff", () => {
    expect(isPermanentProvisionFailure(401)).toBe(true);
    expect(isPermanentProvisionFailure(403)).toBe(true);
    expect(isPermanentProvisionFailure(503)).toBe(false);
    expect(provisionReconnectDelay(0)).toBe(1000);
    expect(provisionReconnectDelay(20)).toBe(30000);
  });

  test("rejects a successful non-SSE response", async () => {
    await expect(consumeProvisionSse(
      new Response("<html></html>", { status: 200, headers: { "content-type": "text/html" } }),
      () => {},
    )).rejects.toThrow(/content type/);
  });

  test("cancels a provisioning stream after byte inactivity", async () => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    const response = new Response(
      new ReadableStream<Uint8Array>({ cancel }),
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
    const result = consumeProvisionSse(response, () => undefined, 1_000);
    const rejection = expect(result).rejects.toThrow(/inactivity timeout/);

    await vi.advanceTimersByTimeAsync(1_000);

    await rejection;
    expect(cancel).toHaveBeenCalledOnce();
  });

  test("cancels a provisioning stream when the event callback fails", async () => {
    const cancel = vi.fn();
    const encoder = new TextEncoder();
    const response = new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode('data: {"type":"provision.progress"}\n\n'));
        },
        cancel,
      }),
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );

    await expect(consumeProvisionSse(response, () => {
      throw new Error("callback failed");
    })).rejects.toThrow("callback failed");
    expect(cancel).toHaveBeenCalledOnce();
  });
});
