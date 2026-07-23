import { describe, expect, test } from "vitest";
import {
  clearScheduledTimeouts,
  matchingTurnIndexes,
  clampDockWidth,
  parseDeckLayoutMode,
  replyAgent,
  restoredTurn,
  sessionIdFor,
} from "./command-deck";

describe("Deck scheduled work", () => {
  test("cancels every tracked context timeout", () => {
    const timers = new Set([11, 12, 13]);
    const cleared: number[] = [];

    clearScheduledTimeouts(timers, (timer) => cleared.push(timer));

    expect(cleared).toEqual([11, 12, 13]);
    expect(timers.size).toBe(0);
  });
});

describe("Deck layout mode", () => {
  test("restores supported modes and defaults malformed values to the right dock", () => {
    expect(parseDeckLayoutMode("floating")).toBe("floating");
    expect(parseDeckLayoutMode("dock")).toBe("dock");
    expect(parseDeckLayoutMode("workspace")).toBe("workspace");
    expect(parseDeckLayoutMode("unknown")).toBe("dock");
    expect(parseDeckLayoutMode(null)).toBe("dock");
  });

  test("clamps right-sidebar width to a usable viewport range", () => {
    expect(clampDockWidth(100, 1440)).toBe(340);
    expect(clampDockWidth(500, 1440)).toBe(500);
    expect(clampDockWidth(900, 1440)).toBe(720);
    expect(clampDockWidth(600, 800)).toBe(480);
  });
});

describe("Deck backend session IDs", () => {
  test("isolates transcripts and restores an existing session ID", () => {
    const sessions = new Map<string, string>();
    let next = 0;
    const create = () => `session-${++next}`;

    const general = sessionIdFor(sessions, "screen", create);
    const forseti = sessionIdFor(sessions, "agent:Forseti", create);

    expect(general).not.toBe(forseti);
    expect(sessionIdFor(sessions, "screen", create)).toBe(general);
    expect(next).toBe(2);
  });
});

describe("Deck transcript search", () => {
  test("matches case-insensitively and ignores a blank query", () => {
    const turns = [
      { text: "Explain the current HIL decision" },
      { text: "No matching content" },
      { text: "HIL is waiting for Var" },
    ];

    expect(matchingTurnIndexes(turns, " hil ")).toEqual([0, 2]);
    expect(matchingTurnIndexes(turns, "   ")).toEqual([]);
  });
});

describe("terminal reply attribution", () => {
  test("uses Bragi when verification replaces delegated prose", () => {
    const delegation = { primary_agent: "Saga", contributors: [] };
    const verification = {
      authority: "client_snapshot",
      checks_completed: 0,
      checks_total: 1,
      evidence_refs: [],
      reason_code: "screen_claim_mismatch",
    } as const;

    expect(replyAgent({ delegation, verification: { ...verification, status: "unverified" } }))
      .toBe("Bragi");
    expect(replyAgent({ delegation, verification: { ...verification, status: "corrected" } }))
      .toBe("Bragi");
    expect(replyAgent({ delegation, verification: { ...verification, status: "consistent" } }))
      .toBe("Saga");
  });
});

describe("durable transcript restoration", () => {
  test("maps principal-scoped operator and assistant records into deck turns", () => {
    const operator = restoredTurn({
      turn_id: "turn-1",
      conversation_id: "conversation-1",
      turn_index: 0,
      role: "operator",
      content: "Show major issues.",
      recorded_at: "2026-07-16T07:00:00Z",
      metadata: {},
    });
    const assistant = restoredTurn({
      turn_id: "turn-2",
      conversation_id: "conversation-1",
      turn_index: 1,
      role: "assistant",
      content: "No high issues.",
      recorded_at: "2026-07-16T07:00:01Z",
      metadata: { source: "llm:test", agent: "Bragi" },
    });

    expect(operator).toMatchObject({ id: "turn-1", role: "operator", text: "Show major issues." });
    expect(assistant).toMatchObject({
      id: "turn-2",
      role: "deck",
      text: "No high issues.",
      source: "llm:test",
      agent: "Bragi",
      terminal: true,
    });
  });
});
