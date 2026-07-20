import { describe, expect, test } from "vitest";
import { decodeAutomationBlueprints } from "./automation-blueprints";

function payload() {
  return {
    source: "automation-blueprint-store",
    mutation_controls: false,
    count: 1,
    candidates: [{
      candidate_id: "blueprint-example",
      state: "draft",
      normalized_task_intent: "check inventory drift",
      schedule_expression: "0 3 * * *",
      resource_scope: "scope://subscription/example/resource-group/app",
      delivery_intent: "audit-only",
      required_tools: ["query_inventory"],
      isolation_profile: {
        profile_id: "scheduled.default-deny",
        max_session_seconds: 300,
        max_context_chars: 16000,
        max_tool_calls: 0,
        allowed_tool_ids: [],
      },
      estimated_cost_microusd: 100,
      evidence_fingerprints: ["a".repeat(64), "b".repeat(64), "c".repeat(64)],
      confidence: 0.75,
      expires_at: "2026-08-20T00:00:00+00:00",
      enabled: false,
      shadow_only: true,
      mutation_tool_ids: [],
    }],
    metrics: {
      proposed: 1,
      accepted: 0,
      rejected: 0,
      expired: 0,
      materialized: 0,
      realized_usage: 0,
      candidate_precision: 0,
      acceptance_rate: 0,
      rejection_reasons: {},
    },
  };
}

describe("automation blueprint cards", () => {
  test("decodes inert evidence, scope, tools, isolation, cost, and quality", () => {
    const decoded = decodeAutomationBlueprints(payload());
    expect(decoded.mutation_controls).toBe(false);
    expect(decoded.candidates[0]?.evidence_fingerprints).toHaveLength(3);
    expect(decoded.candidates[0]?.required_tools).toEqual(["query_inventory"]);
    expect(decoded.candidates[0]?.isolation_profile.max_tool_calls).toBe(0);
    expect(decoded.metrics.candidate_precision).toBe(0);
  });

  test("rejects contradictory counts and invalid confidence", () => {
    expect(() => decodeAutomationBlueprints({ ...payload(), count: 2 })).toThrow(/count MUST match/);
    const invalid = payload();
    invalid.candidates[0]!.confidence = 2;
    expect(() => decodeAutomationBlueprints(invalid)).toThrow(/MUST be <= 1/);
  });
});
