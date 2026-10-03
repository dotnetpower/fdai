import { afterEach, expect, test, vi } from "vitest";
import type { WorkProgressShape } from "./backend-types";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SHAPE: WorkProgressShape = {
  schema_version: 1,
  density: "procedural",
  waves: 2,
  planned_reads: 3,
};

function read(activityId: string): Record<string, unknown> {
  return {
    activity_id: activityId,
    kind: "ontology_query",
    status: "running",
    label: activityId,
    completed: 0,
    total: 1,
    execution: { tool: "Ontology query", command: "query.function", input_kind: "query", redacted: true },
  };
}

// Streams the frames, then a terminal frame, and returns every plan pin the deck accepted.
async function acceptedPins(
  frames: readonly (readonly [string, Record<string, unknown>])[],
): Promise<readonly WorkProgressShape[]> {
  vi.resetModules();
  const body = [...frames, ["done", { answer: "Done." }] as const]
    .map(([event, data], index) =>
      `event: ${event}\ndata: ${JSON.stringify({ seq: index + 1, revision: 0, ...data })}\n\n`)
    .join("");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body)));
  const backend = await import("./backend");
  backend.fallbackTypewriter.intervalMs = 0;
  const pins: WorkProgressShape[] = [];
  await backend.askBackendStream("q", null, [], {
    onToken: () => undefined,
    onWorkProgress: (shape) => pins.push(shape),
  });
  return pins;
}

test("accepts one plan pin before the first read", async () => {
  expect(await acceptedPins([
    ["work_progress", { work_progress_shape: SHAPE }],
    ["work_progress", { work_progress_shape: { ...SHAPE, planned_reads: 5 } }],
    ["activity", read("semantic:goal:a")],
  ])).toEqual([SHAPE]);
});

test("ignores a pin that arrives after the first read, so density never flips", async () => {
  expect(await acceptedPins([
    ["activity", read("semantic:goal:a")],
    ["work_progress", { work_progress_shape: SHAPE }],
  ])).toEqual([]);
});

test("drops a malformed pin without closing the pin window", async () => {
  expect(await acceptedPins([
    ["work_progress", { work_progress_shape: { ...SHAPE, waves: 9 } }],
    ["work_progress", { work_progress_shape: SHAPE }],
  ])).toEqual([SHAPE]);
});
