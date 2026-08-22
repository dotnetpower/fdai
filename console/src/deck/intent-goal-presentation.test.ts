import { describe, expect, it } from "vitest";

import { intentGoalInstruction } from "./intent-goal-presentation";

describe("intentGoalInstruction", () => {
  it.each([
    ["object_set", "inspectTargets"],
    ["relationship_traversal", "inspectRelationships"],
    ["metric_scope_series", "inspectMetrics"],
    ["metric_comparison", "compareMetrics"],
    ["topology_diff", "compareTopology"],
    ["evidence_join", "combineEvidence"],
    ["function", "verifyCapability"],
  ] as const)("maps %s to %s", (intent, expected) => {
    expect(intentGoalInstruction(intent)).toBe(expected);
  });

  it("keeps an unknown verified intent generic", () => {
    expect(intentGoalInstruction("future_read_kind")).toBe("inspectEvidence");
  });
});
