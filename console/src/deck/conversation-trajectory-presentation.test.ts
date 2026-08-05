import { describe, expect, it } from "vitest";

import type { Turn } from "./command-deck-presenters";
import type { ConversationTrajectory } from "./conversation-trajectory";
import {
  buildTrajectoryPresentation,
  workProgressPresentation,
} from "./conversation-trajectory-presentation";

function trajectory(
  answer: Partial<Turn>,
  overrides: Partial<ConversationTrajectory> = {},
): ConversationTrajectory {
  return {
    question: { id: "question", role: "operator", text: "Check it", at: "10:00:00" },
    answer: { id: "answer", role: "deck", text: "Done", terminal: true, at: "10:00:01", ...answer },
    observedTurns: [],
    activities: [],
    branches: [],
    ...overrides,
    milestones: overrides.milestones ?? [],
  };
}

describe("buildTrajectoryPresentation", () => {
  it("selects the smallest sufficient work-progress presentation", () => {
    expect(workProgressPresentation(trajectory({}))).toBe("none");

    const compact = trajectory({}, { activities: [{
      activityId: "inventory-query",
      branchId: "inventory",
      kind: "read.execution",
      status: "completed",
      label: "Queried inventory",
      completed: 1,
      total: 1,
      execution: {
        tool: "inventory",
        command: '{"query":"status"}',
        inputKind: "query",
        redacted: true,
      },
    }], branches: [{
      branchId: "inventory",
      kind: "tool",
      parentBranchId: null,
      status: "completed",
      summary: "Inventory evidence ready",
      startedAt: "2026-07-31T07:00:00Z",
      completedAt: "2026-07-31T07:00:01Z",
      durationMs: 1000,
      evidenceRefs: ["inventory:snapshot"],
    }] });
    expect(workProgressPresentation(compact)).toBe("compact");

    expect(workProgressPresentation({
      ...compact,
      milestones: [{ messageId: "progress-1", text: "Inventory confirmed" }],
    })).toBe("timeline");
    expect(workProgressPresentation({
      ...compact,
      activities: [...compact.activities, {
        activityId: "verification",
        kind: "tool",
        status: "completed",
        label: "Ran focused checks",
        completed: 1,
        total: 1,
      }],
    })).toBe("timeline");
  });

  it("does not present unavailable evidence or unverified checks as completed", () => {
    const input = trajectory({
      verification: {
        status: "unverified",
        authority: "client_snapshot",
        checks_completed: 0,
        checks_total: 1,
        evidence_refs: [],
        reason_code: "screen_claim_mismatch",
      },
    }, { branches: [
      {
        branchId: "agent",
        kind: "agent",
        parentBranchId: null,
        status: "unavailable",
        summary: "Agent evidence unavailable",
        startedAt: "2026-07-31T07:00:00Z",
        completedAt: "2026-07-31T07:00:00Z",
        durationMs: 0,
        evidenceRefs: [],
      },
      {
        branchId: "web",
        kind: "public_web",
        parentBranchId: null,
        status: "timed_out",
        summary: "Public web evidence timed out",
        startedAt: "2026-07-31T07:00:00Z",
        completedAt: "2026-07-31T07:00:08Z",
        durationMs: 8000,
        evidenceRefs: [],
      },
    ] });

    const result = buildTrajectoryPresentation(input);

    expect(result.phaseStates.evidence).toBe("degraded");
    expect(result.phaseStates.verification).toBe("unverified");
    expect(result.evidenceCompletedCount).toBe(0);
    expect(result.evidenceAttemptCount).toBe(2);
  });

  it("counts a branch-linked activity once", () => {
    const input = trajectory({}, { branches: [{
      branchId: "inventory",
      kind: "operational",
      parentBranchId: null,
      status: "completed",
      summary: "Inventory evidence",
      startedAt: "2026-07-31T07:00:00Z",
      completedAt: "2026-07-31T07:00:01Z",
      durationMs: 1000,
      evidenceRefs: ["inventory:snapshot"],
    }], activities: [{
      activityId: "inventory-query",
      branchId: "inventory",
      kind: "query",
      status: "completed",
      label: "Inventory query",
      completed: 1,
      total: 1,
    }] });

    const result = buildTrajectoryPresentation(input);

    expect(result.phaseStates.evidence).toBe("completed");
    expect(result.evidenceAttemptCount).toBe(1);
    expect(result.evidenceCompletedCount).toBe(1);
    expect(result.evidenceReferenceCount).toBe(1);
  });

  it("reports a model-call lower bound when detailed tracing is disabled", () => {
    const result = buildTrajectoryPresentation(trajectory({
      source: "llm:narrator-mini · 500ms",
    }));

    expect(result.modelCallCount).toBe(1);
    expect(result.modelCallCountIsLowerBound).toBe(true);
  });

  it("includes calls omitted by the trace bound", () => {
    const result = buildTrajectoryPresentation(trajectory({
      source: "llm:narrator-mini · 500ms",
      modelTrace: {
        schema_version: 1,
        redacted: true,
        calls: [],
        omitted_calls: 3,
      },
    }));

    expect(result.modelCallCount).toBe(3);
    expect(result.modelCallCountIsLowerBound).toBe(false);
  });

  it("distinguishes corrected verification and degraded planning", () => {
    const input = trajectory({
      answerPlanning: {
        mode: "shadow",
        status: "degraded",
        primary_agent: null,
        consulted_agents: [],
        contributions: [],
        failures: [],
        elapsed_ms: 10,
        unique_evidence_count: 0,
        duplicate_evidence_count: 0,
        conflicting_evidence_refs: [],
        covered_sections: [],
        estimated_added_tokens: 0,
        budget: {
          max_contributors: 1,
          max_rounds: 1,
          max_wall_ms: 100,
          max_added_tokens: 100,
          nested_rounds: false,
        },
        reason: "no contributor evidence",
      },
      verification: {
        status: "corrected",
        authority: "server_read_model",
        checks_completed: 1,
        checks_total: 1,
        evidence_refs: [],
        reason_code: null,
      },
    });

    const result = buildTrajectoryPresentation(input);

    expect(result.phaseStates.collaboration).toBe("degraded");
    expect(result.phaseStates.verification).toBe("corrected");
  });
});
