import { describe, expect, test } from "vitest";
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
});

describe("fetch SSE boundary", () => {
  test("adds the bearer header without putting it in the URL", () => {
    const headers = provisionStreamHeaders("Bearer token");
    expect(headers.get("authorization")).toBe("Bearer token");
    expect(headers.get("accept")).toBe("text/event-stream");
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
});
