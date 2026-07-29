import { describe, expect, it } from "vitest";
import type { Turn } from "./command-deck-presenters";
import { backendHistoryForTurns } from "./turn-history";

describe("backendHistoryForTurns", () => {
  it("sends hidden grounding while retaining the concise rendered briefing", () => {
    const turns: Turn[] = [{
      id: "context-1",
      role: "deck",
      text: "Heimdall is analyzing discovery signals.",
      groundingText: "Context for a conversation about the FDAI agent Heimdall.",
      source: "context",
      agent: "Heimdall",
      at: "13:00:00",
    }];

    expect(backendHistoryForTurns(turns)).toEqual([{
      role: "assistant",
      content: "Context for a conversation about the FDAI agent Heimdall.",
    }]);
    expect(turns[0]?.text).toBe("Heimdall is analyzing discovery signals.");
  });
});
