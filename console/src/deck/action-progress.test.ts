import { describe, expect, test } from "vitest";
import type { LiveStageEvent, LiveStageName } from "../hooks/use-live-stream";
import { formatActionProgress } from "./action-progress";

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
});
