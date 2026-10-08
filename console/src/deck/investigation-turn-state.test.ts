import { describe, expect, it } from "vitest";
import type { InvestigationActivity } from "./backend";
import type { Turn } from "./command-deck-presenters";
import {
  investigationFlowHasTerminalAnswer,
  investigationFlowPosition,
  investigationTurnsAreSettled,
  isInvestigationLead,
  plannedReadsObserved,
  settleInvestigationTurn,
  settleInvestigationTurns,
} from "./investigation-turn-state";

function activityTurn(id: string): Turn {
  return {
    id,
    role: "deck",
    kind: "activity",
    text: id,
    streaming: true,
    terminal: false,
    at: "01:00:00",
  };
}

describe("investigation turn state", () => {
  it("keeps one agent flow from observed work through the terminal answer", () => {
    const operator: Turn = {
      id: "question",
      role: "operator",
      text: "Check inventory",
      at: "01:00:00",
    };
    const progress: Turn = {
      id: "progress",
      role: "deck",
      kind: "message",
      source: "investigation",
      text: "Starting inventory query",
      at: "01:00:01",
    };
    const answer: Turn = {
      id: "answer",
      role: "deck",
      source: "evidence:verified",
      text: "Nine resources matched.",
      terminal: true,
      at: "01:00:03",
    };
    const nextOperator: Turn = {
      id: "next-question",
      role: "operator",
      text: "What is unhealthy?",
      at: "01:00:04",
    };
    const turns = [operator, progress, activityTurn("query"), answer, nextOperator];

    expect(investigationFlowPosition(turns, 1)).toEqual({
      inFlow: true,
      continuation: false,
      start: true,
      end: false,
    });
    expect(investigationFlowPosition(turns, 2)).toEqual({
      inFlow: true,
      continuation: false,
      start: false,
      end: false,
    });
    expect(investigationFlowPosition(turns, 3)).toEqual({
      inFlow: true,
      continuation: true,
      start: false,
      end: true,
    });
    expect(investigationFlowPosition(turns, 4).inFlow).toBe(false);
  });

  it("compacts every activity group once the shared flow has a terminal answer", () => {
    const first = { ...activityTurn("phase-1"), streaming: false, terminal: true };
    const second = { ...activityTurn("phase-2"), streaming: false, terminal: true };
    const answer: Turn = {
      id: "answer",
      role: "deck",
      text: "Verified evidence is unavailable.",
      terminal: true,
      at: "01:00:03",
    };
    const turns = [first, second, answer];

    expect(investigationFlowHasTerminalAnswer(turns, 0)).toBe(true);
    expect(investigationFlowHasTerminalAnswer(turns, 1)).toBe(true);
    expect(investigationFlowHasTerminalAnswer(turns, 2)).toBe(false);
    expect(investigationFlowHasTerminalAnswer([first, second], 0)).toBe(false);
  });

  it("settles only the activity group that precedes a milestone", () => {
    const turns = [activityTurn("phase-1"), activityTurn("phase-2")];

    const settled = settleInvestigationTurn(turns, "phase-1");

    expect(settled[0]).toMatchObject({ streaming: false, terminal: true });
    expect(settled[1]).toBe(turns[1]);
  });

  it("settles every observed activity group at terminal completion", () => {
    const message: Turn = {
      id: "milestone",
      role: "deck",
      text: "Continuing with verification.",
      at: "01:00:01",
    };
    const turns = [activityTurn("phase-1"), message, activityTurn("phase-2")];

    const settled = settleInvestigationTurns(turns, new Set(["phase-1", "phase-2"]));

    expect(settled[0]).toMatchObject({ streaming: false, terminal: true });
    expect(settled[1]).toBe(message);
    expect(settled[2]).toMatchObject({ streaming: false, terminal: true });
  });

  it("holds answer reveal until every observed activity and branch is terminal", () => {
    const runningActivity: InvestigationActivity = {
      activityId: "inventory",
      kind: "inventory.query",
      status: "running",
      label: "Query inventory",
      completed: 0,
      total: 1,
    };
    const running: Turn = {
      ...activityTurn("phase-1"),
      activities: [runningActivity],
    };
    const settled: Turn = {
      ...running,
      activities: [{ ...runningActivity, status: "completed", completed: 1 }],
    };

    expect(investigationTurnsAreSettled([running], new Set([running.id]))).toBe(false);
    expect(investigationTurnsAreSettled([settled], new Set([settled.id]))).toBe(true);
    expect(investigationTurnsAreSettled([], new Set([running.id]))).toBe(false);
    expect(investigationTurnsAreSettled([], new Set())).toBe(true);
  });

  it("gives the turn-wide roles to the first activity turn of each flow", () => {
    const question: Turn = { id: "q", role: "operator", text: "Check drift", at: "01:00:00" };
    const milestone: Turn = {
      id: "milestone-1",
      role: "deck",
      kind: "message",
      source: "investigation",
      text: "The first wave finished.",
      at: "01:00:02",
    };
    const turns = [question, activityTurn("wave-1"), milestone, activityTurn("wave-2")];

    expect(turns.map((_, index) => isInvestigationLead(turns, index))).toEqual([
      false,
      true,
      false,
      false,
    ]);
    // A flow that opens with a milestone still gives the roles to its first activity turn.
    const late = [question, milestone, activityTurn("wave-1")];
    expect(isInvestigationLead(late, 2)).toBe(true);
  });

  it("treats a pause between waves as unfinished until the pinned reads are observed", () => {
    const read = (id: string): InvestigationActivity => ({
      activityId: id,
      kind: "ontology_query",
      status: "completed",
      label: id,
      completed: 1,
      total: 1,
      execution: { tool: "Ontology query", command: "query.function", inputKind: "query", redacted: true },
    });
    const lifecycle: InvestigationActivity = {
      activityId: "semantic:evidence",
      kind: "semantic_turn",
      status: "completed",
      label: "Evidence checked",
      completed: 1,
      total: 1,
    };
    const shape = { schema_version: 1, density: "procedural", waves: 2, planned_reads: 3 } as const;
    const wave1: Turn = { ...activityTurn("wave-1"), activities: [read("a"), read("b"), lifecycle] };
    const wave2: Turn = { ...activityTurn("wave-2"), activities: [read("c")] };
    const ids = new Set([wave1.id, wave2.id]);

    expect(plannedReadsObserved([wave1], ids, undefined)).toBe(true);
    // A lifecycle step is not a read, so two reads of three keep the work open.
    expect(plannedReadsObserved([wave1], ids, shape)).toBe(false);
    expect(plannedReadsObserved([wave1, wave2], ids, shape)).toBe(true);
    // A read replayed under the same identity is counted once.
    expect(plannedReadsObserved([wave1, { ...wave2, activities: [read("a")] }], ids, shape)).toBe(false);
  });

  it("keeps planning open while only model calls have been observed", () => {
    const modelCall = (id: string): InvestigationActivity => ({
      activityId: id,
      kind: "model_call",
      status: "completed",
      label: id,
      completed: null,
      total: null,
    });
    const planning: Turn = {
      ...activityTurn("planning"),
      activities: [modelCall("semantic:model:1"), modelCall("semantic:model:2")],
    };
    const ids = new Set([planning.id]);

    // Every call has ended, but the plan has not been pinned or read yet.
    expect(investigationTurnsAreSettled([planning], ids)).toBe(true);
    expect(plannedReadsObserved([planning], ids, undefined)).toBe(false);

    const lifecycle: InvestigationActivity = {
      activityId: "semantic:evidence",
      kind: "semantic_turn",
      status: "completed",
      label: "Evidence checked",
      completed: 1,
      total: 1,
    };
    const withWork = { ...planning, activities: [...planning.activities ?? [], lifecycle] };
    expect(plannedReadsObserved([withWork], ids, undefined)).toBe(true);
    expect(plannedReadsObserved([{ ...activityTurn("empty"), activities: [] }], new Set(["empty"]), undefined))
      .toBe(true);
  });
});
