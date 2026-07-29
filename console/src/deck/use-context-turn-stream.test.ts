import { describe, expect, it } from "vitest";
import { contextChunks, contextStreamPacer } from "./use-context-turn-stream";

describe("context turn pacing", () => {
  it("streams short word bursts faster than the source-streaming mock", () => {
    const text = "Heimdall is monitoring discovery freshness and processing object.event now.";
    const chunks = contextChunks(text);

    expect(chunks.join("")).toBe(text);
    expect(chunks).toHaveLength(5);
    expect(chunks.length * contextStreamPacer.intervalMs).toBeLessThan(100);
  });
});
