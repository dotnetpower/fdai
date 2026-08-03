import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  drainStreamPaint,
  flushStreamPaint,
  shouldFlushStreamPaintSynchronously,
  streamPaintBatchSize,
  terminalRevealChunks,
} from "./stream-paint";

const submitSource = readFileSync(
  fileURLToPath(new URL("./use-command-deck-submit.ts", import.meta.url)),
  "utf8",
);

describe("stream paint batching", () => {
  it("uses a bounded adaptive batch per display frame", () => {
    expect(streamPaintBatchSize(1)).toBe(1);
    expect(streamPaintBatchSize(9)).toBe(2);
    expect(streamPaintBatchSize(25)).toBe(3);
    expect(streamPaintBatchSize(1_000)).toBe(3);
  });

  it("never dumps a large preparing backlog in one paint", () => {
    const queue = Array.from({ length: 60 }, (_, index) => `${index},`);
    const first = drainStreamPaint(queue);
    expect(first).toBe("0,1,2,");
    expect(queue).toHaveLength(57);
  });

  it("reconstructs every delta in order", () => {
    const source = Array.from({ length: 60 }, (_, index) => `[${index}]`);
    const queue = [...source];
    const frames: string[] = [];
    while (queue.length > 0) frames.push(drainStreamPaint(queue));
    expect(frames.join("")).toBe(source.join(""));
    expect(frames.length).toBeGreaterThan(20);
  });

  it.each([
    ["visible", true, false],
    ["visible", false, true],
    ["hidden", true, true],
    ["hidden", false, true],
  ])("selects synchronous terminal drain for %s focus=%s", (state, focused, expected) => {
    expect(shouldFlushStreamPaintSynchronously(state, focused)).toBe(expected);
  });

  it("flushes a background backlog byte-for-byte and empties the queue", () => {
    const queue = ["first", " ", "second", "."];

    expect(flushStreamPaint(queue)).toBe("first second.");
    expect(queue).toEqual([]);
  });

  it("chunks terminal-only tables without changing their canonical text", () => {
    const text = "| Name | State |\n| --- | --- |\n| api | Running |";
    const chunks = terminalRevealChunks(text);

    expect(chunks.length).toBeGreaterThan(4);
    expect(chunks.join("")).toBe(text);
  });

  it("bounds a long terminal-only reveal to roughly 300 ms of display frames", () => {
    const text = Array.from({ length: 300 }, (_, index) => `word-${index} `).join("");
    const chunks = terminalRevealChunks(text);
    const queue = [...chunks];
    let frames = 0;
    while (queue.length > 0) {
      drainStreamPaint(queue);
      frames += 1;
    }

    expect(chunks).toHaveLength(30);
    expect(frames).toBeLessThanOrEqual(18);
    expect(chunks.join("")).toBe(text);
  });

  it("records terminal receipt before visual replay completes", () => {
    const receiptIndex = submitSource.indexOf("const terminalRecordedAt =");
    const revealIndex = submitSource.indexOf("const terminalQueue = terminalRevealChunks");

    expect(receiptIndex).toBeGreaterThan(0);
    expect(revealIndex).toBeGreaterThan(receiptIndex);
    expect(submitSource).toContain("recordedAt: terminalRecordedAt");
  });
});
