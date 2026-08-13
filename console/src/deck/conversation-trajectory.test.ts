import { describe, expect, it } from "vitest";

import type { Turn } from "./command-deck-presenters";
import { conversationTrajectoriesByAnswer } from "./conversation-trajectory";

function turn(input: Partial<Turn> & Pick<Turn, "id" | "role" | "text">): Turn {
  return { at: "10:00:00", ...input };
}

describe("conversationTrajectoriesByAnswer", () => {
  it("retains the exact semantic receipt on the terminal answer", () => {
    const question = turn({ id: "question-1", role: "operator", text: "Query ontology" });
    const semanticReceipt = {
      schema_version: "1.0.0" as const,
      projection_id: `00000000-0000-4000-8000-${"0".repeat(12)}`,
      request_id: `00000000-0000-4000-8000-${"0".repeat(11)}1`,
      disposition: "answered" as const,
      reason_code: "query_completed",
      ontology_release_digest: `sha256:${"a".repeat(64)}`,
      principal_manifest_digest: `sha256:${"b".repeat(64)}`,
      plan_digest: `sha256:${"c".repeat(64)}`,
      execution_receipt_digest: `sha256:${"d".repeat(64)}`,
      execution_authority: false as const,
    };
    const answer = turn({
      id: "answer-1",
      role: "deck",
      text: "Grounded answer",
      terminal: true,
      semanticReceipt,
    });

    expect(conversationTrajectoriesByAnswer([question, answer]).get(answer.id)?.answer)
      .toMatchObject({ semanticReceipt });
  });

  it("groups observed work between one question and its terminal answer", () => {
    const question = turn({
      id: "question-1",
      role: "operator",
      text: "What is unhealthy?",
      recordedAt: "2026-07-31T01:00:00Z",
    });
    const activity = turn({
      id: "activity-1",
      role: "deck",
      kind: "activity",
      source: "investigation",
      terminal: true,
      text: "Queried inventory",
      activities: [{
        activityId: "inventory",
        kind: "query",
        status: "completed",
        label: "Queried inventory",
        completed: 1,
        total: 1,
      }],
      branches: [{
        branchId: "branch-1",
        kind: "operational",
        parentBranchId: null,
        status: "completed",
        summary: "Inventory evidence",
        startedAt: "2026-07-31T01:00:00.500Z",
        completedAt: "2026-07-31T01:00:01.500Z",
        durationMs: 1000,
        evidenceRefs: ["inventory:snapshot"],
      }],
    });
    const milestone = turn({
      id: "milestone-1",
      role: "deck",
      kind: "message",
      source: "investigation",
      terminal: true,
      text: "Inventory complete",
    });
    const answer = turn({
      id: "answer-1",
      role: "deck",
      text: "One service is unavailable.",
      source: "llm:test",
      terminal: true,
      recordedAt: "2026-07-31T01:00:03Z",
    });

    const trajectory = conversationTrajectoriesByAnswer([
      question,
      activity,
      milestone,
      answer,
    ]).get(answer.id);

    expect(trajectory).toMatchObject({
      question,
      answer,
      observedTurns: [activity, milestone],
      durationMs: 3000,
    });
    expect(trajectory?.activities.map((item) => item.activityId)).toEqual(["inventory"]);
    expect(trajectory?.branches.map((item) => item.branchId)).toEqual(["branch-1"]);
  });

  it("keeps first-seen order while retaining the latest observation per id", () => {
    const question = turn({ id: "question-1", role: "operator", text: "Check it" });
    const running = turn({
      id: "activity-running",
      role: "deck",
      kind: "activity",
      source: "investigation",
      text: "Running",
      activities: [{
        activityId: "same",
        kind: "query",
        status: "running",
        label: "Running",
        completed: 0,
        total: 1,
      }],
    });
    const completed = turn({
      id: "activity-completed",
      role: "deck",
      kind: "activity",
      source: "investigation",
      text: "Completed",
      activities: [{
        activityId: "same",
        kind: "query",
        status: "completed",
        label: "Completed",
        completed: 1,
        total: 1,
      }],
    });
    const answer = turn({
      id: "answer-1",
      role: "deck",
      text: "Done",
      terminal: true,
    });

    const trajectory = conversationTrajectoriesByAnswer([
      question,
      running,
      completed,
      answer,
    ]).get(answer.id);

    expect(trajectory?.activities).toHaveLength(1);
    expect(trajectory?.activities[0]?.status).toBe("completed");
  });

  it("does not treat investigation milestones or partial replies as terminal answers", () => {
    const question = turn({ id: "question-1", role: "operator", text: "Check it" });
    const milestone = turn({
      id: "milestone-1",
      role: "deck",
      kind: "message",
      source: "investigation",
      terminal: true,
      text: "Evidence ready",
    });
    const partial = turn({
      id: "partial-1",
      role: "deck",
      terminal: false,
      text: "Partial",
    });

    expect(conversationTrajectoriesByAnswer([question, milestone, partial]).size).toBe(0);
  });

  it("does not invent a duration for reversed recorded timestamps", () => {
    const question = turn({
      id: "question-1",
      role: "operator",
      text: "Check it",
      recordedAt: "2026-07-31T01:00:03Z",
    });
    const answer = turn({
      id: "answer-1",
      role: "deck",
      text: "Done",
      terminal: true,
      recordedAt: "2026-07-31T01:00:00Z",
    });

    expect(conversationTrajectoriesByAnswer([question, answer]).get(answer.id)?.durationMs)
      .toBeUndefined();
  });

  it("reconstructs durable detail without intermediate live turns", () => {
    const question = turn({
      id: "question-1",
      role: "operator",
      text: "Check inventory",
      recordedAt: "2026-07-31T01:00:00Z",
    });
    const answer = turn({
      id: "answer-1",
      role: "deck",
      text: "Two resources found.",
      terminal: true,
      recordedAt: "2026-07-31T01:00:02Z",
      trajectoryDetail: {
        schema_version: 1,
        activities: [{
          activityId: "query-1",
          kind: "query",
          status: "completed",
          label: "Query inventory",
          completed: 1,
          total: 1,
          execution: {
            tool: "inventory",
            command: '{"query":"status"}',
            inputKind: "query",
            redacted: true,
            output: '{"count":2}',
          },
        }],
        branches: [{
          branchId: "branch-1",
          kind: "operational",
          parentBranchId: null,
          status: "completed",
          summary: "Evidence ready",
          startedAt: "2026-07-31T01:00:00Z",
          completedAt: "2026-07-31T01:00:01Z",
          durationMs: 1000,
          evidenceRefs: ["evidence:1"],
        }],
        milestones: [{
          messageId: "milestone-1",
          text: "Inventory complete",
          recordedAt: "2026-07-31T01:00:01Z",
        }],
        omitted: { activities: 0, branches: 0, milestones: 0 },
        truncated_outputs: 0,
      },
    });

    const trajectory = conversationTrajectoriesByAnswer([question, answer]).get(answer.id);

    expect(trajectory?.activities[0]?.execution?.output).toBe('{"count":2}');
    expect(trajectory?.branches[0]?.evidenceRefs).toEqual(["evidence:1"]);
    expect(trajectory?.milestones[0]?.text).toBe("Inventory complete");
  });

  it("deduplicates live and terminal milestone detail by message id", () => {
    const question = turn({ id: "question-1", role: "operator", text: "Check it" });
    const liveMilestone = turn({
      id: "milestone-milestone-1",
      role: "deck",
      kind: "message",
      source: "investigation",
      text: "Inventory complete",
      recordedAt: "2026-07-31T01:00:01Z",
    });
    const answer = turn({
      id: "answer-1",
      role: "deck",
      text: "Done",
      terminal: true,
      trajectoryDetail: {
        schema_version: 1,
        activities: [],
        branches: [],
        milestones: [{
          messageId: "milestone-1",
          text: "Inventory complete",
          recordedAt: "2026-07-31T01:00:01Z",
        }],
        omitted: { activities: 0, branches: 0, milestones: 0 },
        truncated_outputs: 0,
      },
    });

    const trajectory = conversationTrajectoriesByAnswer([
      question,
      liveMilestone,
      answer,
    ]).get(answer.id);

    expect(trajectory?.milestones).toHaveLength(1);
  });

  it("prefers richer live execution output over the bounded replay copy", () => {
    const question = turn({ id: "question-1", role: "operator", text: "Check it" });
    const liveActivity = turn({
      id: "activity-1",
      role: "deck",
      kind: "activity",
      source: "investigation",
      text: "Query inventory",
      activities: [{
        activityId: "query-1",
        kind: "query",
        status: "completed",
        label: "Query inventory",
        completed: 1,
        total: 1,
        execution: {
          tool: "inventory",
          command: '{"query":"status"}',
          inputKind: "query",
          redacted: true,
          output: "complete live output",
        },
      }],
    });
    const answer = turn({
      id: "answer-1",
      role: "deck",
      text: "Done",
      terminal: true,
      trajectoryDetail: {
        schema_version: 1,
        activities: [{
          ...liveActivity.activities![0]!,
          execution: {
            ...liveActivity.activities![0]!.execution!,
            output: "truncated durable output",
            outputTruncated: true,
          },
        }],
        branches: [],
        milestones: [],
        omitted: { activities: 0, branches: 0, milestones: 0 },
        truncated_outputs: 1,
      },
    });

    const trajectory = conversationTrajectoriesByAnswer([
      question,
      liveActivity,
      answer,
    ]).get(answer.id);

    expect(trajectory?.activities[0]?.execution?.output).toBe("complete live output");
  });
});
