import { describe, expect, test } from "vitest";
import type { AuditItem } from "../types";
import { agentOf } from "./agent-activity-semantics";
import {
  buildAgentTrajectories,
  filterAgentTrajectories,
  outcomeTone,
  stepCategory,
  trajectoryPhases,
  trajectoryScale,
  trajectoryTitle,
  uncorrelatedAuditCount,
} from "./agent-activity-trajectory-model";

function item(
  seq: number,
  actor: string,
  actionKind: string,
  recordedAt: string,
  entry: Record<string, unknown> = {},
  correlation: string | null = "corr-change",
): AuditItem {
  return {
    seq,
    event_id: `event-${seq}`,
    correlation_id: correlation,
    actor,
    action_kind: actionKind,
    mode: "shadow",
    entry,
    entry_hash: `hash-${seq}`,
    previous_hash: `hash-${seq - 1}`,
    recorded_at: recordedAt,
  };
}

const CHANGE = [
  item(4, "Var", "hil.requested", "2026-07-15T10:04:00Z", { outcome: "hil_pending", summary: "Approval requested" }),
  item(1, "Huginn", "event.normalized", "2026-07-15T10:00:00.100Z", { summary: "Change normalized", duration_ms: 100 }),
  item(3, "Forseti", "risk_gate.evaluated", "2026-07-15T10:00:02Z", {
    outcome: "hil",
    tier: "t1",
    summary: "Risk class high",
    conversation: [{ from: "Forseti", to: "Var", text: "Approval required." }],
  }),
  item(2, "Heimdall", "inventory.current_state.read", "2026-07-15T10:00:01Z", {
    started_at: "2026-07-15T10:00:00.400Z",
    outputs: { records: "3", stale: "metrics" },
  }),
];

describe("agent trajectory projection", () => {
  test("groups correlated audit steps in recorded order and keeps uncorrelated rows out", () => {
    const rows = [...CHANGE, item(9, "Saga", "audit.record", "2026-07-15T10:05:00Z", {}, null)];
    const [trajectory, ...rest] = buildAgentTrajectories(rows, agentOf);

    expect(rest).toEqual([]);
    expect(trajectory!.correlationId).toBe("corr-change");
    expect(trajectory!.steps.map((step) => step.seq)).toEqual([1, 2, 3, 4]);
    expect(trajectory!.agents).toEqual(["Huginn", "Heimdall", "Forseti", "Var"]);
    expect(trajectory!.handoffs).toBe(3);
    expect(trajectory!.title).toBe("Change normalized");
    expect(uncorrelatedAuditCount(rows)).toBe(1);
  });

  test("titles a trajectory with prose before a readable machine value", () => {
    const machine = buildAgentTrajectories([
      item(1, "fdai.observer", "observation-campaign.source-transition", "2026-07-15T10:00:00Z", {}, "corr-a"),
      item(2, "fdai.observer", "observer.refresh", "2026-07-15T10:00:01Z", { summary: "current_evidence" }, "corr-b"),
    ], agentOf);
    expect(machine.map((value) => value.title).sort()).toEqual([
      "Current evidence",
      "Observation campaign \u00b7 source transition",
    ]);
    const [prose] = buildAgentTrajectories(CHANGE, agentOf);
    expect(trajectoryTitle(prose!.steps)).toBe("Change normalized");
  });

  test("uses recorded timing without inventing durations", () => {
    const [trajectory] = buildAgentTrajectories(CHANGE, agentOf);
    const [intake, read, risk] = trajectory!.steps;

    expect(intake!.durationMs).toBe(100);
    expect(intake!.endMs - intake!.startMs).toBe(100);
    expect(read!.durationMs).toBe(600);
    expect(read!.outputs).toEqual([["records", "3"], ["stale", "metrics"]]);
    expect(risk!.durationMs).toBeNull();
    expect(risk!.startMs).toBe(risk!.endMs);
    expect(risk!.tier).toBe("T1");
  });

  test("reports the latest recorded outcome without asserting completion", () => {
    const [trajectory] = buildAgentTrajectories(CHANGE, agentOf);

    expect(trajectory!.latestOutcome).toBe("hil_pending");
    expect(trajectory!.tone).toBe("attention");
    expect(trajectory!.flaggedSteps).toBe(2);
    expect(buildAgentTrajectories([item(1, "Huginn", "event.normalized", "2026-07-15T10:00:00Z")], agentOf)[0]!
      .latestOutcome).toBeNull();
  });

  test("leaves phases without records unrecorded instead of skipped", () => {
    const [trajectory] = buildAgentTrajectories(CHANGE, agentOf);

    expect(trajectoryPhases(trajectory!)).toEqual([
      { id: "intake", state: "recorded", steps: 1 },
      { id: "evidence", state: "recorded", steps: 1 },
      { id: "judgment", state: "attention", steps: 1 },
      { id: "authorization", state: "attention", steps: 1 },
      { id: "execution", state: "unrecorded", steps: 0 },
      { id: "outcome", state: "unrecorded", steps: 0 },
    ]);
  });

  test("classifies steps from recorded action fields only", () => {
    expect(stepCategory(item(1, "Huginn", "event.normalized", "2026-07-15T10:00:00Z"))).toBe("intake");
    expect(stepCategory(item(2, "fdai.core", "control_loop.decided", "2026-07-15T10:00:00Z", { stage: "trust_router" })))
      .toBe("decision");
    expect(stepCategory(item(3, "Thor", "action.dispatch", "2026-07-15T10:00:00Z"))).toBe("action");
    expect(stepCategory(item(4, "Vidar", "rollback.completed", "2026-07-15T10:00:00Z"))).toBe("recovery");
    expect(stepCategory(item(5, "Heimdall", "effect.verified", "2026-07-15T10:00:00Z"))).toBe("verification");
    expect(stepCategory(item(6, "Odin", "custom.note", "2026-07-15T10:00:00Z"))).toBe("activity");
  });

  test("maps outcome tone only from recorded outcome text", () => {
    expect(outcomeTone("failed")).toBe("bad");
    expect(outcomeTone("timed_out")).toBe("bad");
    expect(outcomeTone("hil_pending")).toBe("attention");
    expect(outcomeTone("verified")).toBe("good");
    expect(outcomeTone("recorded")).toBe("neutral");
    expect(outcomeTone(null, null)).toBe("neutral");
  });

  test("filters by participating agent, conversation recipient, and recorded text", () => {
    const trajectories = buildAgentTrajectories([
      ...CHANGE,
      item(20, "Njord", "cost.advisory", "2026-07-15T09:00:00Z", { summary: "Advisory" }, "corr-cost"),
    ], agentOf);

    expect(filterAgentTrajectories(trajectories, "Var", "").map((value) => value.correlationId))
      .toEqual(["corr-change"]);
    expect(filterAgentTrajectories(trajectories, null, "advisory").map((value) => value.correlationId))
      .toEqual(["corr-cost"]);
    expect(filterAgentTrajectories(trajectories, null, "approval required").map((value) => value.correlationId))
      .toEqual(["corr-change"]);
    expect(filterAgentTrajectories(trajectories, "Thor", "")).toEqual([]);
  });

  test("compresses long idle gaps while keeping recorded work linear", () => {
    const [trajectory] = buildAgentTrajectories(CHANGE, agentOf);
    const scale = trajectoryScale(trajectory!);

    expect(scale.breaks).toHaveLength(1);
    expect(scale.breaks[0]!.realMs).toBe(238_000);
    expect(scale.x(trajectory!.startMs)).toBe(0);
    expect(scale.x(trajectory!.endMs)).toBe(100);
    expect(scale.x(Date.parse("2026-07-15T10:00:02Z"))).toBeGreaterThan(50);
  });
});
