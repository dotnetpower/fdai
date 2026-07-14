import { describe, expect, test } from "vitest";
import { matchingTurnIndexes, sessionIdFor } from "./command-deck";

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