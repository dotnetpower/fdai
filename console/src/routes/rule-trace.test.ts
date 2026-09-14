import { describe, expect, it } from "vitest";
import { OperatorApiError } from "../api";

import {
  buildTraceViewSnapshot,
  decodeTraceResponse,
  traceActionLifecycles,
  traceLoadFailure,
  traceOperationalSummary,
} from "./rule-trace";
import { traceOffset } from "./rule-trace-supporting-evidence";

const step = (seq: number) => ({
  seq,
  event_id: `event-${seq}`,
  source_correlation_id: "corr-1",
  recorded_at: `2026-07-17T09:00:0${seq}Z`,
  actor: "Forseti",
  stage: "risk-gate",
  decision: "hil",
  reason: "approval required",
  action_kind: "change",
  mode: "shadow",
  action_id: null,
  attempt: null,
  execution_path: null,
  outcome: null,
  entry_hash: `hash-${seq}`,
  previous_hash: `hash-${seq - 1}`,
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

  it("rejects a response for a different requested correlation", () => {
    expect(() => decodeTraceResponse({
      correlation_id: "corr-other",
      step_count: 1,
      steps: [step(1)],
      terminal_stage: "risk-gate",
    }, "corr-requested")).toThrow(/MUST match the requested correlation/);
  });

  it("accepts consistent server summary metadata and rejects a contradictory latest row", () => {
    const root = {
      correlation_id: "corr-1",
      step_count: 1,
      steps: [step(1)],
      terminal_stage: "risk-gate",
      trace_kind: "decision",
      source_authority: "operator-audit-log",
      complete: true,
      first_recorded_at: step(1).recorded_at,
      last_recorded_at: step(1).recorded_at,
      latest_sequence: 1,
      latest_activity_stage: "risk-gate",
      latest_action_kind: "change",
      latest_actor: "Forseti",
      latest_decision: "hil",
      latest_outcome: null,
      latest_mode: "shadow",
      target_resource_ref: null,
      target_count: 0,
      action_attempt_count: 0,
      effect_observation_count: 0,
      incident_evidence_recorded: false,
      rca_evidence_recorded: false,
    };

    expect(decodeTraceResponse(root)).toEqual(expect.objectContaining({
      metadata_source: "server",
      trace_kind: "decision",
      complete: true,
    }));
    expect(() => decodeTraceResponse({ ...root, latest_sequence: 2 }))
      .toThrow(/latest metadata MUST match ordered steps/);
  });

  it("renders expected source absence as unavailable without hiding server failures", () => {
    expect(traceLoadFailure(new OperatorApiError(404, "no audit items"))).toEqual({
      status: "unavailable",
      message: "No audit steps for this correlation id.",
    });
    expect(traceLoadFailure(
      new OperatorApiError(503, "audit source unavailable", "projection-unavailable"),
    )).toEqual({
      status: "unavailable",
      message: "Trace could not be loaded: audit source unavailable",
    });
    expect(traceLoadFailure(new OperatorApiError(500, "database failed"))).toEqual({
      status: "error",
      message: "Trace could not be loaded: database failed",
    });
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

  it("rejects an oversized response instead of presenting a truncated trace as complete", () => {
    const steps = Array.from({ length: 501 }, (_, index) => ({
      ...step(1),
      seq: index + 1,
    }));

    expect(() => decodeTraceResponse({
      correlation_id: "corr-oversized",
      step_count: steps.length,
      steps,
      terminal_stage: "risk-gate",
    })).toThrow(/at most 500 records/);
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
    expect(() => decodeTraceResponse({ ...root, steps: [{ ...step(1), decision: " " }] }))
      .toThrow(/decision MUST be null or non-empty/);
    expect(() => decodeTraceResponse({ ...root, steps: [{ ...step(1), reason: " " }] }))
      .toThrow(/reason MUST be null or non-empty/);
    expect(() => decodeTraceResponse({ ...root, terminal_stage: " " }))
      .toThrow(/terminal_stage MUST be null or non-empty/);
    expect(() => decodeTraceResponse({ ...root, steps: [{ ...step(1), seq: 0 }] }))
      .toThrow(/seq MUST be positive/);
  });

  it("shows recorded clock drift instead of flattening it to zero", () => {
    expect(traceOffset(step(2), step(1))).toBe("-1.0 s");
    expect(traceOffset(step(1), step(1))).toBe("+0 ms");
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
      event_id: "event-1",
      source_correlation_id: "corr-1",
      actor: "Forseti",
      stage: null,
      reason: "no delivery channel is available",
      entry_hash: "hash-activity",
      previous_hash: "hash-0",
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

  describe("trace action lifecycle", () => {
    it("keeps dispatch pending until independent observation is recorded", () => {
      const action = {
        action_id: "action-1",
        attempt: 1,
        execution_path: "direct_api",
        outcome: null,
      };
      const data = decodeTraceResponse({
        correlation_id: "corr-lifecycle",
        step_count: 4,
        steps: [
          { ...step(1), ...action, stage: "plan", decision: null, action_kind: "action.proposal.recorded" },
          { ...step(2), ...action, stage: "risk-gate", decision: "hil", action_kind: "risk_gate.unified" },
          { ...step(3), ...action, stage: null, decision: null, action_kind: "hil.approved.claimed" },
          {
            ...step(4),
            ...action,
            stage: "execute",
            decision: null,
            action_kind: "hil.approved.execution_pending",
            outcome: "awaiting_effect_evidence",
          },
        ],
        terminal_stage: "execute",
      });

      const lifecycles = traceActionLifecycles(data);

      expect(lifecycles).toHaveLength(1);
      expect(lifecycles[0]?.stages).toEqual([
        expect.objectContaining({ id: "proposal", state: "recorded" }),
        expect.objectContaining({ id: "decision", state: "recorded" }),
        expect.objectContaining({ id: "approval", state: "recorded" }),
        expect.objectContaining({ id: "dispatch", state: "pending" }),
        expect.objectContaining({ id: "observation", state: "not_recorded" }),
        expect.objectContaining({ id: "recovery", state: "not_recorded" }),
      ]);
    });

    it("shows observation and recovery only from their own audit evidence", () => {
      const action = {
        action_id: "action-2",
        attempt: 1,
        execution_path: "direct_api",
        outcome: null,
      };
      const data = decodeTraceResponse({
        correlation_id: "corr-closure",
        step_count: 3,
        steps: [
          {
            ...step(1),
            ...action,
            stage: "execute",
            decision: null,
            action_kind: "executor.direct_api.dispatched",
            outcome: "dispatched",
          },
          {
            ...step(2),
            ...action,
            stage: "verify",
            decision: "done",
            action_kind: "effect_observation.recorded",
          },
          {
            ...step(3),
            ...action,
            stage: "audit",
            decision: "done",
            action_kind: "t2.proposer.route.rolled_back",
          },
        ],
        terminal_stage: "audit",
      });

      const lifecycle = traceActionLifecycles(data)[0]!.stages;

      expect(lifecycle.find((item) => item.id === "dispatch")?.state).toBe("recorded");
      expect(lifecycle.find((item) => item.id === "observation")?.state).toBe("recorded");
      expect(lifecycle.find((item) => item.id === "recovery")?.state).toBe("recorded");
      expect(lifecycle.find((item) => item.id === "decision")?.state).toBe("not_recorded");
      expect(lifecycle.find((item) => item.id === "approval")?.state).toBe("not_recorded");
    });

    it("renders proven no-publication as not attempted instead of completed", () => {
      const data = decodeTraceResponse({
        correlation_id: "corr-no-dispatch",
        step_count: 1,
        steps: [{
          ...step(1),
          stage: "execute",
          decision: null,
          action_kind: "executor.remote.dispatch_not_attempted",
          action_id: "action-3",
          attempt: 1,
          execution_path: "direct_api",
          outcome: "dispatch_not_attempted",
        }],
        terminal_stage: "execute",
      });

      const lifecycle = traceActionLifecycles(data)[0]!.stages;

      expect(lifecycle.find((item) => item.id === "dispatch")?.state).toBe("not_attempted");
    });

    it("does not treat notification or compensation failures as action dispatch", () => {
      const action = {
        action_id: "action-4",
        attempt: 1,
        execution_path: null,
        outcome: null,
      };
      const data = decodeTraceResponse({
        correlation_id: "corr-unrelated-failures",
        step_count: 2,
        steps: [
          {
            ...step(1),
            ...action,
            stage: null,
            decision: null,
            action_kind: "hil.request.dispatch_failed",
          },
          {
            ...step(2),
            ...action,
            stage: "audit",
            decision: null,
            action_kind: "workflow.compensation.failed",
          },
        ],
        terminal_stage: "audit",
      });

      expect(traceActionLifecycles(data)[0]!.stages.find((item) => item.id === "dispatch")?.state)
        .toBe("not_recorded");
      expect(traceActionLifecycles(data)[0]!.stages.find((item) => item.id === "approval")?.state)
        .toBe("not_recorded");
    });

    it("marks explicit approval rejection as failed without treating other HIL traffic as approval", () => {
      const data = decodeTraceResponse({
        correlation_id: "corr-approval-rejected",
        step_count: 2,
        steps: [
          {
            ...step(1),
            action_id: "action-approval",
            attempt: 1,
            action_kind: "hil.delivery.observed",
            decision: null,
          },
          {
            ...step(2),
            action_id: "action-approval",
            attempt: 1,
            action_kind: "hil.rejected",
            decision: "deny",
          },
        ],
        terminal_stage: "risk-gate",
      });

      const approval = traceActionLifecycles(data)[0]!.stages.find(
        (item) => item.id === "approval",
      );

      expect(approval).toEqual(expect.objectContaining({
        state: "failed",
        evidence: expect.objectContaining({ action_kind: "hil.rejected" }),
      }));
    });

    it("never combines two action attempts in one lifecycle", () => {
      const data = decodeTraceResponse({
        correlation_id: "corr-two-actions",
        step_count: 2,
        steps: [
          {
            ...step(1),
            action_id: "action-a",
            attempt: 1,
            execution_path: "direct_api",
            outcome: "dispatched",
            action_kind: "executor.direct_api.dispatched",
          },
          {
            ...step(2),
            action_id: "action-b",
            attempt: 2,
            execution_path: "direct_api",
            outcome: "execution_unknown",
            action_kind: "executor.remote.execution_unknown",
          },
        ],
        terminal_stage: "risk-gate",
      });

      const lifecycles = traceActionLifecycles(data);

      expect(lifecycles).toHaveLength(2);
      expect(lifecycles[0]).toEqual(expect.objectContaining({ actionId: "action-a", attempt: 1 }));
      expect(lifecycles[1]).toEqual(expect.objectContaining({ actionId: "action-b", attempt: 2 }));
      expect(lifecycles[0]?.stages.find((item) => item.id === "dispatch")?.state)
        .toBe("recorded");
      expect(lifecycles[1]?.stages.find((item) => item.id === "dispatch")?.state)
        .toBe("pending");
    });

    it("merges missing-attempt evidence only when one explicit attempt exists", () => {
      const data = decodeTraceResponse({
        correlation_id: "corr-one-attempt",
        step_count: 2,
        steps: [
          {
            ...step(1),
            action_id: "action-one",
            attempt: null,
            execution_path: null,
            outcome: null,
            action_kind: "risk_gate.unified",
          },
          {
            ...step(2),
            action_id: "action-one",
            attempt: 3,
            execution_path: "direct_api",
            outcome: "dispatched",
            action_kind: "executor.correlated.dispatched",
          },
        ],
        terminal_stage: "risk-gate",
      });

      const lifecycles = traceActionLifecycles(data);

      expect(lifecycles).toHaveLength(1);
      expect(lifecycles[0]).toEqual(expect.objectContaining({ actionId: "action-one", attempt: 3 }));
      expect(lifecycles[0]?.stages.find((item) => item.id === "decision")?.state)
        .toBe("recorded");
      expect(lifecycles[0]?.stages.find((item) => item.id === "dispatch")?.state)
        .toBe("recorded");
    });

    it("classifies PR-native and denied direct API producer shapes from outcome fields", () => {
      const data = decodeTraceResponse({
        correlation_id: "corr-producer-shapes",
        step_count: 2,
        steps: [
          {
            ...step(1),
            action_id: "action-pr",
            attempt: 1,
            execution_path: "pr_native",
            outcome: "published",
            action_kind: "ops.publish-change-summary",
          },
          {
            ...step(2),
            action_id: "action-direct",
            attempt: 1,
            execution_path: "direct_api",
            outcome: "permission_denied",
            action_kind: "executor.direct_api.permission_denied",
          },
        ],
        terminal_stage: "risk-gate",
      });

      const lifecycles = traceActionLifecycles(data);

      expect(lifecycles[0]?.stages.find((item) => item.id === "dispatch")?.state)
        .toBe("recorded");
      expect(lifecycles[1]?.stages.find((item) => item.id === "dispatch")?.state)
        .toBe("not_attempted");
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
