import { describe, expect, it } from "vitest";

import {
  buildTraceViewSnapshot,
  decodeTraceResponse,
  traceOperationalSummary,
} from "./rule-trace";

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
    expect(() => decodeTraceResponse({ ...root, terminal_stage: "execute" })).toThrow(/last named stage/);
  });

  it("accepts correlated activity without a pipeline stage", () => {
    const decoded = decodeTraceResponse({
      correlation_id: "corr-activity",
      step_count: 2,
      steps: [step(1), { ...step(2), stage: null, action_kind: "notification.escalation" }],
      terminal_stage: "risk-gate",
    });

    expect(decoded.steps[1]?.stage).toBeNull();
    expect(decoded.terminal_stage).toBe("risk-gate");
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
    expect(() => decodeTraceResponse({ ...root, steps: [{ ...step(1), stage: " " }] }))
      .toThrow(/MUST be null or non-empty/);
  });
});

describe("trace view context", () => {
  it("preserves correlation and the actionable load error", () => {
    const snapshot = buildTraceViewSnapshot("corr-error", {
      status: "error",
      message: "Trace evidence is inconsistent.",
    });

    expect(snapshot?.facts).toContainEqual(expect.objectContaining({ key: "correlation_id", value: "corr-error" }));
    expect(snapshot?.facts).toContainEqual(expect.objectContaining({ key: "load_error", value: "Trace evidence is inconsistent." }));
  });

  it("publishes stage-less causal activity and its audit hash", () => {
    const data = decodeTraceResponse({
      correlation_id: "corr-activity",
      step_count: 1,
      steps: [{ ...step(1), stage: null, reason: "no delivery channel is available", entry_hash: "hash-activity" }],
      terminal_stage: null,
    });

    const snapshot = buildTraceViewSnapshot("corr-activity", { status: "ready", data });

    expect(snapshot?.records?.["steps"]?.[0]).toEqual(expect.objectContaining({
      stage: null,
      reason: "no delivery channel is available",
      entry_hash: "hash-activity",
    }));
  });
});

describe("trace operational summary", () => {
  it("distinguishes delivery escalation from decisions, RCA, and named stages", () => {
    const data = decodeTraceResponse({
      correlation_id: "corr-activity",
      step_count: 2,
      steps: [
        { ...step(1), stage: null, decision: null },
        {
          ...step(2),
          stage: null,
          action_kind: "notification.escalation",
          decision: null,
        },
      ],
      terminal_stage: null,
    });

    expect(traceOperationalSummary(data)).toEqual({
      notificationEscalation: true,
      decisionRecorded: false,
      rcaRecorded: false,
      namedStageCount: 0,
    });
  });

  it("counts recorded decisions, RCA evidence, and named stages", () => {
    const data = decodeTraceResponse({
      correlation_id: "corr-rca",
      step_count: 2,
      steps: [
        { ...step(1), action_kind: "policy.evaluation" },
        { ...step(2), action_kind: "rca.hypothesis" },
      ],
      terminal_stage: "risk-gate",
    });

    expect(traceOperationalSummary(data)).toEqual({
      notificationEscalation: false,
      decisionRecorded: true,
      rcaRecorded: true,
      namedStageCount: 2,
    });
  });
});
