import { describe, expect, test } from "vitest";
import { decodeProvisionEvent } from "./use-provision-stream";

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
