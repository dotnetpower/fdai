import { describe, expect, it } from "vitest";

import type { Turn } from "./command-deck-presenters";
import { settleCancelledTurns } from "./use-command-deck-lifecycle";

const baseTurn = {
  id: "turn-1",
  role: "deck",
  at: "12:00:00",
  streaming: true,
  terminal: false,
} satisfies Partial<Turn>;

describe("settleCancelledTurns", () => {
  it("records the stop and keeps each read's last observed status", () => {
    const activity: Turn = {
      ...baseTurn,
      role: "deck",
      kind: "activity",
      text: "Checked the bounded resource scope.",
      activities: [{
        activityId: "activity-1",
        kind: "query",
        status: "running",
        label: "Resource scope",
        completed: 0,
        total: 1,
      }],
      branches: [{
        branchId: "branch-1",
        kind: "operational",
        parentBranchId: null,
        status: "running",
        summary: "Reading scoped evidence",
        startedAt: "2026-09-08T12:00:00Z",
        evidenceRefs: ["evidence-1"],
      }],
    };

    // The read never reported an end, so it is shown as stopped rather than as unavailable.
    expect(settleCancelledTurns([activity])).toEqual([
      {
        ...activity,
        streaming: false,
        terminal: true,
        stopped: true,
        branches: [{ ...activity.branches![0], status: "cancelled" }],
      },
    ]);
  });

  it("retracts only provisional answer text and confirmation", () => {
    const answer: Turn = {
      ...baseTurn,
      role: "deck",
      text: "Unverified draft",
      confirmed: {
        segmentIndex: 0,
        revision: 1,
        text: "Unverified draft",
        status: "consistent",
        evidenceRefs: ["evidence-1"],
      },
    };

    const [stopped] = settleCancelledTurns([answer]);

    expect(stopped?.text).toBe("");
    expect(stopped?.streaming).toBe(false);
    expect(stopped?.terminal).toBe(false);
    expect(stopped?.confirmed).toBeUndefined();
  });
});
