import { describe, expect, it, vi } from "vitest";

import {
  consumeOntologyInvalidationSse,
  decodeOntologyInvalidationEvent,
  ontologyInvalidationHeaders,
  ontologyInvalidationReconnectDelay,
  ontologyInvalidationCursor,
  recoverOntologyInvalidationCursor,
} from "./use-ontology-invalidation-stream";

const EVENT = {
  schema_version: "1.0.0",
  watermark: 42,
  observation_count: 3,
  observed_at: "2026-09-05T04:00:00Z",
  recorded_at: "2026-09-05T04:00:01Z",
  complete: false,
  execution_authority: false,
  mutation_authority: false,
};

describe("ontology invalidation SSE", () => {
  const epochEvent = { ...EVENT, schema_version: "2.0.0" as const, epoch: "a".repeat(32), reset_required: true, complete: false as const, execution_authority: false as const, mutation_authority: false as const };
  it.each([null, 42, "broken", "a".repeat(33)])("rejects malformed epoch %s", (epoch) => {
    expect(decodeOntologyInvalidationEvent(JSON.stringify({ ...epochEvent, epoch }))).toBeNull();
  });
  it("accepts epoch events only with a matching compound id", async () => {
    const events: unknown[] = [];
    const cursor = ontologyInvalidationCursor(epochEvent);
    const response = new Response(`id: ${cursor}\nevent: inventory.invalidated\ndata: ${JSON.stringify(epochEvent)}\n\n`, { headers: { "content-type": "text/event-stream" } });
    await consumeOntologyInvalidationSse(response, (event) => events.push(event));
    expect(events).toEqual([epochEvent]);
  });
  it("does not acknowledge the reset until snapshot reread completes", async () => {
    let resolve: () => void = () => undefined;
    const load = new Promise<void>((finish) => { resolve = finish; });
    let acknowledged = false;
    const result = recoverOntologyInvalidationCursor(epochEvent, () => load).then((cursor) => { acknowledged = true; return cursor; });
    await Promise.resolve();
    expect(acknowledged).toBe(false);
    resolve();
    expect(await result).toBe(`${epochEvent.epoch}:42`);
  });
  it("does not acknowledge a failed snapshot read", async () => {
    await expect(recoverOntologyInvalidationCursor(epochEvent, async () => { throw new Error("unavailable"); })).rejects.toThrow("unavailable");
  });
  it("invalidates delayed rendering when the principal or route changed", async () => {
    let current = true;
    let permitted: () => boolean = () => true;
    await expect(recoverOntologyInvalidationCursor(epochEvent, async (isCurrent) => {
      permitted = isCurrent;
      expect(permitted()).toBe(true);
      current = false;
    }, () => current)).rejects.toThrow("cancelled");
    expect(permitted()).toBe(false);
  });
  it("bounds a stalled snapshot reread", async () => {
    vi.useFakeTimers();
    try {
      const result = recoverOntologyInvalidationCursor(epochEvent, () => new Promise(() => undefined));
      const rejected = expect(result).rejects.toThrow("timed out");
      await vi.advanceTimersByTimeAsync(10_000);
      await rejected;
    } finally { vi.useRealTimers(); }
  });
  it("accepts only bounded no-authority invalidations", () => {
    expect(decodeOntologyInvalidationEvent(JSON.stringify(EVENT))).toEqual(EVENT);
    expect(decodeOntologyInvalidationEvent(JSON.stringify({
      ...EVENT,
      resource_id: "/subscriptions/example",
    }))).toBeNull();
    expect(decodeOntologyInvalidationEvent(JSON.stringify({
      ...EVENT,
      execution_authority: true,
    }))).toBeNull();
    expect(decodeOntologyInvalidationEvent(JSON.stringify({
      ...EVENT,
      observation_count: 501,
    }))).toBeNull();
    expect(decodeOntologyInvalidationEvent(JSON.stringify({
      ...EVENT,
      observed_at: "September 5",
    }))).toBeNull();
    expect(decodeOntologyInvalidationEvent("{")).toBeNull();
  });

  it("builds authenticated replay headers without storing credentials", () => {
    const headers = ontologyInvalidationHeaders("Bearer opaque", "42");

    expect(headers.get("accept")).toBe("text/event-stream");
    expect(headers.get("authorization")).toBe("Bearer opaque");
    expect(headers.get("last-event-id")).toBe("42");
  });

  it("bounds reconnect backoff", () => {
    expect(ontologyInvalidationReconnectDelay(0)).toBe(1_000);
    expect(ontologyInvalidationReconnectDelay(3)).toBe(8_000);
    expect(ontologyInvalidationReconnectDelay(20)).toBe(30_000);
  });

  it("decodes invalidations and ignores heartbeat or unrelated events", async () => {
    const body = [
      ": heartbeat\n\n",
      "event: watermark\ndata: {\"sequence\":41}\n\n",
      `id: 42\nevent: inventory.invalidated\ndata: ${JSON.stringify(EVENT)}\n\n`,
    ].join("");
    const response = new Response(body, {
      status: 200,
      headers: { "content-type": "text/event-stream; charset=utf-8" },
    });
    const events: unknown[] = [];

    await consumeOntologyInvalidationSse(response, (event) => events.push(event));

    expect(events).toEqual([EVENT]);
  });

  it("rejects an SSE id that does not match the payload watermark", async () => {
    const response = new Response(
      `id: 41\nevent: inventory.invalidated\ndata: ${JSON.stringify(EVENT)}\n\n`,
      { headers: { "content-type": "text/event-stream" } },
    );
    const events: unknown[] = [];

    await consumeOntologyInvalidationSse(response, (event) => events.push(event));

    expect(events).toEqual([]);
  });

  it("rejects an invalid stream response", async () => {
    await expect(consumeOntologyInvalidationSse(
      new Response("{}", { headers: { "content-type": "application/json" } }),
      () => undefined,
    )).rejects.toThrow("invalid content type");
  });
});
