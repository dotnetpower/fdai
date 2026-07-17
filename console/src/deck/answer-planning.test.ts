import { describe, expect, test } from "vitest";
import { parseAnswerPlanning } from "./backend";

const validPlanning = {
  mode: "shadow",
  status: "completed",
  primary_agent: "Forseti",
  consulted_agents: ["Freyr", "Njord"],
  contributions: [
    {
      agent: "Freyr",
      evidence_refs: ["agent-owned:freyr:1"],
      confidence: 0.8,
      suggested_sections: ["trade_offs"],
    },
  ],
  failures: [],
  elapsed_ms: 12,
  unique_evidence_count: 1,
  duplicate_evidence_count: 0,
  conflicting_evidence_refs: [],
  covered_sections: ["trade_offs"],
  estimated_added_tokens: 24,
  budget: {
    max_contributors: 2,
    max_rounds: 1,
    max_wall_ms: 1200,
    max_added_tokens: 800,
    nested_rounds: false,
  },
  reason: null,
};

describe("Answer Planning metadata boundary", () => {
  test("keeps bounded shadow utility metadata", () => {
    expect(parseAnswerPlanning(validPlanning)).toEqual(validPlanning);
  });

  test.each([
    { ...validPlanning, mode: "selective" },
    { ...validPlanning, consulted_agents: ["Freyr", "Njord", "Loki"] },
    { ...validPlanning, elapsed_ms: 10_000 },
    { ...validPlanning, estimated_added_tokens: 801 },
    { ...validPlanning, conflicting_evidence_refs: Array(33).fill("evidence:ref") },
    { ...validPlanning, budget: { ...validPlanning.budget, max_contributors: 3 } },
    { ...validPlanning, budget: { ...validPlanning.budget, nested_rounds: true } },
    { ...validPlanning, prompt: "hidden prompt", contributions: [{ ...validPlanning.contributions[0], confidence: 2 }] },
  ])("rejects malformed or widened metadata %#", (value) => {
    expect(parseAnswerPlanning(value)).toBeUndefined();
  });
});
