import { describe, expect, it } from "vitest";

import { parseContextReceipts, parseTurnBudget, parseWorkProgressShape } from "./work-progress-contract";

const DIGEST = "a".repeat(64);

function budget(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    model_calls: { used: 3, reserved: 1, maximum: 5 },
    tokens: { used: 21000, reserved: 0, maximum: 48000 },
    elapsed_ms: { used: 18000, reserved: 0, maximum: 60000 },
    as_of: "2026-09-28T10:41:04Z",
    complete: true,
    ...overrides,
  };
}

describe("parseWorkProgressShape", () => {
  it("accepts compact and procedural shapes", () => {
    expect(parseWorkProgressShape({ schema_version: 1, density: "compact", waves: 1, planned_reads: 1 }))
      .toEqual({ schema_version: 1, density: "compact", waves: 1, planned_reads: 1 });
    expect(parseWorkProgressShape({ schema_version: 1, density: "procedural", waves: 2, planned_reads: 7 })?.waves)
      .toBe(2);
  });

  it.each([
    undefined,
    { schema_version: 2, density: "procedural", waves: 2, planned_reads: 7 },
    { schema_version: 1, density: "stream", waves: 1, planned_reads: 1 },
    { schema_version: 1, density: "procedural", waves: 0, planned_reads: 1 },
    { schema_version: 1, density: "procedural", waves: 9, planned_reads: 1 },
    { schema_version: 1, density: "procedural", waves: 2, planned_reads: 65 },
    { schema_version: 1, density: "compact", waves: 2, planned_reads: 1 },
    { schema_version: 1, density: "compact", waves: 1, planned_reads: 2 },
  ])("rejects an out-of-contract shape", (raw) => {
    expect(parseWorkProgressShape(raw)).toBeUndefined();
  });
});

describe("parseTurnBudget", () => {
  it("accepts measured telemetry and keeps an exhaustion reason", () => {
    expect(parseTurnBudget(budget())?.model_calls).toEqual({ used: 3, reserved: 1, maximum: 5 });
    expect(parseTurnBudget(budget({ exhaustion_reason: "rate_limited" }))?.exhaustion_reason).toBe("rate_limited");
  });

  it("lets elapsed time pass its maximum only when the deadline ended the turn", () => {
    const over = { elapsed_ms: { used: 60250, reserved: 0, maximum: 60000 } };
    expect(parseTurnBudget(budget(over))).toBeUndefined();
    expect(parseTurnBudget(budget({ ...over, exhaustion_reason: "deadline" }))?.elapsed_ms.used).toBe(60250);
  });

  it("lets tokens pass their maximum only when token exhaustion ended the turn", () => {
    // Observed usage replaces the reservation before the budget check, so the ending turn can overshoot.
    const over = { tokens: { used: 48400, reserved: 0, maximum: 48000 } };
    expect(parseTurnBudget(budget(over))).toBeUndefined();
    expect(parseTurnBudget(budget({ ...over, exhaustion_reason: "deadline" }))).toBeUndefined();
    expect(parseTurnBudget(budget({ ...over, exhaustion_reason: "tokens" }))?.tokens.used).toBe(48400);
    expect(parseTurnBudget(budget({ model_calls: { used: 6, reserved: 0, maximum: 5 }, exhaustion_reason: "model_calls" })))
      .toBeUndefined();
  });

  it.each([
    { model_calls: { used: 5, reserved: 1, maximum: 5 } },
    { tokens: { used: -1, reserved: 0, maximum: 48000 } },
    { elapsed_ms: { used: 1000, reserved: 10, maximum: 60000 } },
    { model_calls: { used: 1, reserved: 0, maximum: 0 } },
    { as_of: "yesterday" },
    { complete: "yes" },
    { exhaustion_reason: "retry" },
    { schema_version: 2 },
  ])("rejects malformed telemetry", (override) => {
    expect(parseTurnBudget(budget(override))).toBeUndefined();
  });
});

describe("parseContextReceipts", () => {
  const receipt = {
    receipt_id: "ctx-1",
    kind: "operator_preference",
    digest: DIGEST,
    observed_at: "2026-09-28T10:40:58Z",
    freshness: "fresh",
    label: "Separate verified facts from limitations",
  };

  it("accepts bounded operator preference receipts", () => {
    expect(parseContextReceipts([receipt, { ...receipt, receipt_id: "ctx-2", freshness: "superseded" }]))
      .toHaveLength(2);
  });

  it.each([
    [[{ ...receipt, kind: "memory_file" }]],
    [[{ ...receipt, digest: "not-a-digest" }]],
    [[{ ...receipt, freshness: "unknown" }]],
    [[{ ...receipt, label: " " }]],
    [[receipt, receipt]],
    [Array.from({ length: 5 }, (_, index) => ({ ...receipt, receipt_id: `ctx-${index}` }))],
    [receipt],
  ])("rejects receipts outside the contract", (raw) => {
    expect(parseContextReceipts(raw)).toBeUndefined();
  });
});
