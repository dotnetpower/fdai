import { describe, expect, it } from "vitest";

import { decodeTraceResponse } from "./rule-trace";

const step = (seq: number) => ({
  seq,
  recorded_at: `2026-07-17T09:00:0${seq}Z`,
  stage: "risk-gate",
  decision: "hil",
  reason: "approval required",
  action_kind: "change",
  mode: "shadow",
  entry_hash: `hash-${seq}`,
});

describe("trace response contract", () => {
  it("accepts an ordered trace whose summary matches its steps", () => {
    expect(decodeTraceResponse({
      correlation_id: "corr-1",
      step_count: 2,
      steps: [step(1), step(2)],
      terminal_stage: "risk-gate",
    }).steps).toHaveLength(2);
  });

  it("rejects contradictory, duplicate, or unordered trace evidence", () => {
    const root = {
      correlation_id: "corr-1",
      step_count: 2,
      steps: [step(1), step(2)],
      terminal_stage: null,
    };
    expect(() => decodeTraceResponse({ ...root, step_count: 3 })).toThrow(/step_count MUST match/);
    expect(() => decodeTraceResponse({ ...root, steps: [step(1), step(1)] })).toThrow(/unique ascending/);
    expect(() => decodeTraceResponse({ ...root, steps: [step(2), step(1)] })).toThrow(/unique ascending/);
  });

  it("rejects incomplete identifiers and malformed evidence times", () => {
    const root = {
      correlation_id: "corr-1",
      step_count: 1,
      steps: [step(1)],
      terminal_stage: null,
    };
    expect(() => decodeTraceResponse({ ...root, correlation_id: " " })).toThrow(/MUST NOT be empty/);
    expect(() => decodeTraceResponse({ ...root, steps: [{ ...step(1), recorded_at: "2026-07-17" }] }))
      .toThrow(/MUST be RFC 3339/);
  });
});
