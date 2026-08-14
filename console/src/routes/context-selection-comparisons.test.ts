import { describe, expect, it } from "vitest";
import { decodeContextSelectionComparisons } from "./context-selection-comparisons";

const comparison = {
  evaluation_id: "eval-1",
  baseline_policy_ref: "deterministic-tiered-v1@1.0.0",
  candidate_policy_ref: "candidate-v1@1.0.0",
  baseline_tokens: 100,
  candidate_tokens: 80,
  evidence_overlap: 0.8,
  omissions: ["turn-1"],
  pinned_preserved: true,
  latency_ms: 4.2,
  failure_reason: null,
  created_at: "2026-07-21T00:00:00+00:00",
};

describe("context selection comparison decoder", () => {
  it("accepts a read-only comparison payload", () => {
    const result = decodeContextSelectionComparisons({
      read_only: true,
      mutation_controls: false,
      count: 1,
      invariant_failures: 0,
      comparisons: [comparison],
    });
    expect(result.comparisons[0]?.candidate_tokens).toBe(80);
  });

  it("rejects mutation controls and contradictory counts", () => {
    expect(() => decodeContextSelectionComparisons({
      read_only: true,
      mutation_controls: true,
      count: 0,
      invariant_failures: 0,
      comparisons: [],
    })).toThrow(/MUST be read-only/);
    expect(() => decodeContextSelectionComparisons({
      read_only: true,
      mutation_controls: false,
      count: 0,
      invariant_failures: 0,
      comparisons: [comparison],
    })).toThrow(/summary counts MUST match/);
  });

  it("rejects invalid overlap and token values", () => {
    const payload = (overrides: Record<string, unknown>) => ({
      read_only: true,
      mutation_controls: false,
      count: 1,
      invariant_failures: 0,
      comparisons: [{ ...comparison, ...overrides }],
    });
    expect(() => decodeContextSelectionComparisons(payload({ evidence_overlap: 1.1 }))).toThrow(/between 0 and 1/);
    expect(() => decodeContextSelectionComparisons(payload({ candidate_tokens: -1 }))).toThrow(/non-negative integer/);
  });

  // Mirrors the authoritative Operator Service GET /context-selection-comparisons payload,
  // including a failed candidate whose candidate-side fields are null.
  it("accepts the authoritative Operator API projection", () => {
    const result = decodeContextSelectionComparisons({
      read_only: true,
      mutation_controls: false,
      count: 2,
      invariant_failures: 1,
      comparisons: [
        comparison,
        {
          evaluation_id: "eval-2",
          baseline_policy_ref: "deterministic-tiered-v1@1.0.0",
          candidate_policy_ref: "candidate-v1@1.0.0",
          baseline_tokens: 10,
          candidate_tokens: null,
          evidence_overlap: null,
          omissions: [],
          pinned_preserved: false,
          latency_ms: 250,
          failure_reason: "timeout>0.250s",
          created_at: "2026-08-14T00:00:00+00:00",
        },
      ],
    });
    expect(result.count).toBe(2);
    expect(result.invariant_failures).toBe(1);
    expect(result.comparisons[1]?.failure_reason).toBe("timeout>0.250s");
    expect(result.comparisons[1]?.evidence_overlap).toBeNull();
  });

  it("accepts the authoritative empty projection", () => {
    const result = decodeContextSelectionComparisons({
      read_only: true,
      mutation_controls: false,
      count: 0,
      invariant_failures: 0,
      comparisons: [],
    });
    expect(result.comparisons).toEqual([]);
  });
});
