import { describe, expect, it } from "vitest";

import type { Turn } from "./command-deck-presenters";
import type { ConversationTrajectory } from "./conversation-trajectory";
import {
  buildExecutionTimeline,
  executionTimelineWindow,
} from "./conversation-execution-timeline";

const question: Turn = {
  id: "question",
  role: "operator",
  text: "Check it",
  at: "10:00:00",
  recordedAt: "2026-07-31T07:00:00Z",
};

function trajectory(
  answer: Partial<Turn> = {},
  overrides: Partial<ConversationTrajectory> = {},
): ConversationTrajectory {
  return {
    question,
    answer: {
      id: "answer",
      role: "deck",
      text: "Done",
      at: "10:00:05",
      terminal: true,
      recordedAt: "2026-07-31T07:00:05Z",
      ...answer,
    },
    observedTurns: [],
    activities: [],
    branches: [{
      branchId: "web",
      kind: "public_web",
      parentBranchId: null,
      status: "unavailable",
      summary: "Web evidence unavailable",
      startedAt: "2026-07-31T07:00:01Z",
      completedAt: "2026-07-31T07:00:03Z",
      durationMs: 2000,
      evidenceRefs: [],
    }],
    startedAt: "2026-07-31T07:00:00Z",
    completedAt: "2026-07-31T07:00:05Z",
    durationMs: 5000,
    ...overrides,
    milestones: overrides.milestones ?? [],
  };
}

describe("buildExecutionTimeline", () => {
  it("sorts observed work on one shared question-to-answer scale", () => {
    const input = trajectory({
      turnTiming: {
        schema_version: 1,
        started_at: "2026-07-31T07:00:00Z",
        completed_at: "2026-07-31T07:00:05Z",
        duration_ms: 5000,
        phases: [{
          phase: "verification",
          status: "unverified",
          started_at: "2026-07-31T07:00:04Z",
          completed_at: "2026-07-31T07:00:04.500Z",
          duration_ms: 500,
        }],
      },
      modelTrace: {
        schema_version: 1,
        redacted: true,
        omitted_calls: 0,
        calls: [{
          call_id: "call-1",
          kind: "answer-stream",
          model: "test-model",
          status: "completed",
          started_at: "2026-07-31T07:00:02Z",
          completed_at: "2026-07-31T07:00:04Z",
          duration_ms: 2000,
          request: { messages: [], sha256: "a".repeat(64) },
          response: { role: "assistant", content: "Done", sha256: "b".repeat(64) },
          usage: null,
          redactions: [],
        }],
      },
    });
    const items = buildExecutionTimeline(input);

    expect(items.map((item) => `${item.kind}:${item.label}`)).toEqual([
      "turn:input",
      "evidence:public_web",
      "model:answer-stream",
      "phase:verification",
      "turn:answer",
    ]);
    expect(items.find((item) => item.kind === "evidence")?.state).toBe("degraded");
    expect(items.find((item) => item.kind === "phase")?.state).toBe("unverified");
    expect(items.find((item) => item.kind === "model")?.widthPct).toBeCloseTo(40, 1);
    expect(items.find((item) => item.kind === "evidence")?.details).toEqual({
      summary: "Web evidence unavailable",
      facts: [],
      evidenceRefs: [],
    });
    expect(items.find((item) => item.kind === "model")?.details).toEqual({
      facts: [
        { key: "model", value: "test-model" },
        { key: "requestMessages", value: "0" },
        { key: "response", value: "recorded" },
        { key: "redactions", value: "0" },
      ],
      evidenceRefs: [],
      records: [
        { key: "request", value: "[]" },
        {
          key: "response",
          value: JSON.stringify(input.answer.modelTrace?.calls[0]?.response, null, 2),
        },
      ],
    });
    expect(items.at(-1)?.leftPct).toBeLessThan(100);
    expect(executionTimelineWindow(items)).toEqual({
      startedAt: "2026-07-31T07:00:00Z",
      completedAt: "2026-07-31T07:00:05Z",
      durationMs: 5000,
    });

    const hidden = buildExecutionTimeline(input, { includeModelCalls: false });
    expect(hidden.every((item) => item.kind !== "model")).toBe(true);
  });

  it("does not invent lanes when no observed timestamps exist", () => {
    const input = trajectory({}, { branches: [] });
    delete (input as { startedAt?: string }).startedAt;
    delete (input as { completedAt?: string }).completedAt;

    expect(buildExecutionTimeline(input)).toEqual([]);
  });

  it("places answer delivery after the final recorded timing phase", () => {
    const input = trajectory({
      recordedAt: "2026-07-31T07:00:04Z",
      turnTiming: {
        schema_version: 1,
        started_at: "2026-07-31T07:00:00Z",
        completed_at: "2026-07-31T07:00:05Z",
        duration_ms: 5000,
        phases: [{
          phase: "verification",
          status: "completed",
          started_at: "2026-07-31T07:00:04.500Z",
          completed_at: "2026-07-31T07:00:05Z",
          duration_ms: 500,
        }],
      },
    }, {
      completedAt: "2026-07-31T07:00:04Z",
    });

    const items = buildExecutionTimeline(input);

    expect(items.map((item) => item.label).slice(-2)).toEqual(["verification", "answer"]);
    expect(items.at(-1)).toMatchObject({
      kind: "turn",
      label: "answer",
      startedAt: "2026-07-31T07:00:05Z",
      gapWidthPct: 0,
    });
  });

  it("keeps input first when the server timing clock precedes the browser record", () => {
    const input = trajectory({
      turnTiming: {
        schema_version: 1,
        started_at: "2026-07-31T06:59:59.500Z",
        completed_at: "2026-07-31T07:00:05Z",
        duration_ms: 5500,
        phases: [{
          phase: "evidence",
          status: "completed",
          started_at: "2026-07-31T06:59:59.500Z",
          completed_at: "2026-07-31T07:00:03Z",
          duration_ms: 3500,
        }],
      },
    });

    const items = buildExecutionTimeline(input);

    expect(items.slice(0, 2).map((item) => item.label)).toEqual(["input", "evidence"]);
    expect(items[0]?.startedAt).toBe("2026-07-31T06:59:59.500Z");
  });

  it("connects recorded timing gaps and prefers the observed activity over its branch", () => {
    const input = trajectory({}, {
      activities: [{
        activityId: "inventory",
        branchId: "web",
        kind: "inventory.query",
        status: "completed",
        label: "Queried inventory",
        detail: "9 matching resources",
        completed: 1,
        total: 1,
        authority: "server_inventory_graph",
        execution: {
          tool: "query_inventory",
          command: "{}",
          inputKind: "query",
          redacted: true,
          startedAt: "2026-07-31T07:00:01Z",
          completedAt: "2026-07-31T07:00:03Z",
          durationMs: 2000,
        },
      }],
    });

    const items = buildExecutionTimeline(input);
    const evidence = items.find((item) => item.kind === "evidence");

    expect(items.filter((item) => item.kind === "evidence")).toHaveLength(1);
    expect(evidence).toMatchObject({
      id: "activity-inventory",
      displayLabel: "Queried inventory",
      gapLeftPct: 0,
      gapWidthPct: 20,
      details: {
        summary: "9 matching resources",
        facts: [
          { key: "tool", value: "query_inventory" },
          { key: "authority", value: "server_inventory_graph" },
        ],
        records: [
          { key: "query", value: "{}" },
        ],
      },
    });
  });

  it("does not infer zero model calls when trace capture is absent", () => {
    const input = trajectory({
      turnTiming: {
        schema_version: 1,
        started_at: "2026-07-31T07:00:00Z",
        completed_at: "2026-07-31T07:00:05Z",
        duration_ms: 5000,
        phases: [{
          phase: "generation",
          status: "completed",
          started_at: "2026-07-31T07:00:03Z",
          completed_at: "2026-07-31T07:00:04Z",
          duration_ms: 1000,
        }],
      },
    });

    expect(buildExecutionTimeline(input).find((item) => item.label === "generation")?.details)
      .toEqual({
        facts: [
          { key: "source", value: "recorded" },
          { key: "modelCalls", value: "notRecorded" },
        ],
        evidenceRefs: [],
      });
  });

  it("hides a recorded model-call count when trace presentation is disabled", () => {
    const input = trajectory({
      modelTrace: {
        schema_version: 1,
        redacted: true,
        omitted_calls: 0,
        calls: [],
      },
      turnTiming: {
        schema_version: 1,
        started_at: "2026-07-31T07:00:00Z",
        completed_at: "2026-07-31T07:00:05Z",
        duration_ms: 5000,
        phases: [{
          phase: "generation",
          status: "completed",
          started_at: "2026-07-31T07:00:03Z",
          completed_at: "2026-07-31T07:00:04Z",
          duration_ms: 1000,
        }],
      },
    });

    const visible = buildExecutionTimeline(input).find((item) => item.label === "generation");
    const hidden = buildExecutionTimeline(input, { includeModelCalls: false })
      .find((item) => item.label === "generation");

    expect(visible?.details.facts.at(-1)?.value).toBe("0");
    expect(hidden?.details.facts.at(-1)?.value).toBe("notRecorded");
  });
});
