import { describe, expect, it } from "vitest";
import type { Turn } from "./command-deck-presenters";
import {
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
