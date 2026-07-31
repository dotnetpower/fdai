import { describe, expect, it } from "vitest";

import type { Turn } from "./command-deck-presenters";
import type { ConversationTrajectory } from "./conversation-trajectory";
import { buildExecutionTimeline } from "./conversation-execution-timeline";

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
    expect(items.find((item) => item.kind === "model")?.widthPct).toBeCloseTo(38.1, 1);
    expect(items.at(-1)?.leftPct).toBeLessThan(100);

    const hidden = buildExecutionTimeline(input, { includeModelCalls: false });
    expect(hidden.every((item) => item.kind !== "model")).toBe(true);
  });

  it("does not invent lanes when no observed timestamps exist", () => {
    const input = trajectory({}, { branches: [] });
    delete (input as { startedAt?: string }).startedAt;
    delete (input as { completedAt?: string }).completedAt;

    expect(buildExecutionTimeline(input)).toEqual([]);
  });
});
