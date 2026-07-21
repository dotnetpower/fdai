import { afterEach, describe, expect, test, vi } from "vitest";
import type { LiveStageEvent, LiveStageName } from "../hooks/use-live-stream";
import { formatActionProgress, watchActionProgress } from "./action-progress";

afterEach(() => {
  vi.useRealTimers();
});

function stage(
  name: LiveStageName,
  phase: LiveStageEvent["phase"],
  detail?: Record<string, unknown>,
): LiveStageEvent {
  return {
    event_id: "event-1",
    correlation_id: "incident-1",
    stage: name,
    phase,
    ts: "2026-07-20T00:00:00Z",
    ...(detail ? { detail } : {}),
  };
}

describe("action progress", () => {
  test("renders ordered agent stages for one correlation", () => {
    const events = new Map<LiveStageName, LiveStageEvent>([
      ["gate", stage("gate", "done", { gate_decision: "auto" })],
      ["ingest", stage("ingest", "done")],
      ["route", stage("route", "done", { routed_to: "t0" })],
    ]);

    const result = formatActionProgress("incident-1", events);

    expect(result.terminal).toBe(false);
    expect(result.text.split("\n").slice(1)).toEqual([
      "- Huginn · ingest: complete",
      "- Forseti · route: complete · routed_to=t0",
      "- Forseti · gate: complete · gate_decision=auto",
    ]);
  });

  test("marks the timeline terminal only after audit", () => {
    const events = new Map<LiveStageName, LiveStageEvent>([
      ["execute", stage("execute", "done", { mode: "enforce" })],
      ["audit", stage("audit", "done", { outcome: "executed" })],
    ]);

    const result = formatActionProgress("incident-1", events);

    expect(result.terminal).toBe(true);
    expect(result.text).toContain("Thor · execute: complete · mode=enforce");
    expect(result.text).toContain("Saga · audit: complete · outcome=executed");
  });

  test("reports timeout separately from a terminal abort", async () => {
    vi.useFakeTimers();
    const request = watchActionProgress(
      "incident-1",
      () => undefined,
      1_000,
      {
        baseUrl: "http://127.0.0.1:8010",
        requestHeaders: async () => ({}),
        fetcher: async (_input, init) => new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
          );
        }),
      },
    );
    const rejection = expect(request).rejects.toThrow("action progress exceeded the timeout");

    await vi.advanceTimersByTimeAsync(1_000);

    await rejection;
  });

  test("completes normally when the audit frame aborts the stream", async () => {
    const payload = JSON.stringify(stage("audit", "done", { outcome: "executed" }));
    const snapshots: string[] = [];

    await expect(watchActionProgress(
      "incident-1",
      (snapshot) => snapshots.push(snapshot.text),
      1_000,
      {
        baseUrl: "http://127.0.0.1:8010",
        requestHeaders: async () => ({}),
        fetcher: async () => new Response(`event: stage\ndata: ${payload}\n\n`, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        }),
      },
    )).resolves.toBeUndefined();
    expect(snapshots.at(-1)).toContain("Saga · audit: complete");
  });
});
