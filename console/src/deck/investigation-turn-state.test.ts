import { describe, expect, it } from "vitest";
import type { Turn } from "./command-deck-presenters";
import {
  investigationFlowPosition,
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
});
