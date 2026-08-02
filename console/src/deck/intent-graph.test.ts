import { describe, expect, it } from "vitest";
import { parseIntentGraph, parseIntentGraphEvidence } from "./intent-graph";

function graph() {
  return {
    schema_version: 2,
    goals: [
      {
        goal_id: "health",
        intent: "status",
        capability: "query_subscription_health",
        arguments: { lookback_seconds: 3600 },
        depends_on: [],
        evidence_mode: "operational",
        freshness_required: true,
        confidence: 0.9,
        alternatives: [],
      },
    ],
    clarification: null,
    confidence: 0.9,
    action_posture: "advise_only",
  };
}

describe("parseIntentGraph", () => {
  it("decodes one bounded graph", () => {
    expect(parseIntentGraph(graph())?.goals[0]?.capability)
      .toBe("query_subscription_health");
  });

  it("rejects malformed and oversized graphs", () => {
    expect(parseIntentGraph({ ...graph(), schema_version: 1 })).toBeUndefined();
    expect(parseIntentGraph({ ...graph(), goals: Array(9).fill(graph().goals[0]) }))
      .toBeUndefined();
    expect(parseIntentGraph({ ...graph(), confidence: 2 })).toBeUndefined();
    expect(parseIntentGraph({ ...graph(), unexpected: "field" })).toBeUndefined();
    expect(parseIntentGraph({
      ...graph(),
      goals: [{ ...graph().goals[0], arguments: { nested: [[[[["too deep"]]]]] } }],
    })).toBeUndefined();
  });
});

describe("parseIntentGraphEvidence", () => {
  it("preserves partial evidence mode and goal receipts", () => {
    const parsed = parseIntentGraphEvidence({
      schema_version: 1,
      status: "partial",
      evidence_mode: "partial",
      goals: [{
        goal_id: "health",
        intent: "status",
        capability: "query_subscription_health",
        evidence_mode: "operational",
        status: "completed",
        duration_ms: 12,
        depends_on: [],
        evidence_refs: ["subscription-health:latest"],
      }],
    });

    expect(parsed?.evidence_mode).toBe("partial");
    expect(parsed?.goals).toHaveLength(1);
  });

  it("rejects unknown evidence modes", () => {
    expect(parseIntentGraphEvidence({
      schema_version: 1,
      status: "completed",
      evidence_mode: "invented",
      goals: [],
    })).toBeUndefined();
  });

  it("rejects raw provider evidence and oversized receipt references", () => {
    const receipt = {
      goal_id: "health",
      intent: "status",
      capability: "query_subscription_health",
      evidence_mode: "operational",
      status: "completed",
      duration_ms: 12,
      depends_on: [],
    };
    expect(parseIntentGraphEvidence({
      schema_version: 1,
      status: "completed",
      evidence_mode: "operational_grounded",
      goals: [{ ...receipt, evidence: { secret: "raw" } }],
    })).toBeUndefined();
    expect(parseIntentGraphEvidence({
      schema_version: 1,
      status: "completed",
      evidence_mode: "operational_grounded",
      goals: [{ ...receipt, evidence_refs: ["x".repeat(513)] }],
    })).toBeUndefined();
  });
});
