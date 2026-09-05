import { describe, expect, it } from "vitest";

import {
  consumeOntologyInvalidationSse,
  decodeOntologyInvalidationEvent,
  ontologyInvalidationHeaders,
  ontologyInvalidationReconnectDelay,
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
