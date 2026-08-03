import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { resolveDeckOpenSession } from "./use-command-deck-events";

const source = readFileSync(
  fileURLToPath(new URL("./use-command-deck-events.ts", import.meta.url)),
  "utf8",
);

describe("Command Deck composer sizing", () => {
  it("uses one bounded layout-aware textarea resize effect", () => {
    expect(source.match(/element\.style\.height = "auto"/g)).toHaveLength(1);
    expect(source).toContain("}, [draft, inputRef, layoutMode, open]);");
    expect(source).toContain("Math.min(element.scrollHeight, maxHeight)");
  });
});

describe("resolveDeckOpenSession", () => {
  it("creates a fresh agent-bound session for every agent-card Ask", () => {
    const detail = {
      sessionLabel: "Heimdall",
      newConversation: true,
      targetAgent: "Heimdall",
    } as const;

    const first = resolveDeckOpenSession(detail, "scope", "/agents", "first");
    const second = resolveDeckOpenSession(detail, "scope", "/agents", "second");

    expect(first).toEqual({
      key: "user:scope:agent:Heimdall:conversation:first",
      label: "Heimdall",
      contextAgent: "Heimdall",
      kind: "agent",
      hydrateDurable: false,
    });
    expect(second.key).not.toBe(first.key);
  });

  it("preserves an explicit incident conversation key", () => {
    const resolved = resolveDeckOpenSession({
      sessionKey: "agent:Heimdall:incident:corr-1",
      sessionLabel: "Heimdall / INC-1",
      binding: {
        kind: "incident",
        incidentId: "INC-1",
        correlationId: "corr-1",
        selectedAgent: "Heimdall",
      },
    }, "scope", "/agents", "ignored");

    expect(resolved).toEqual({
      key: "user:scope:agent:Heimdall:incident:corr-1",
      label: "Heimdall / INC-1",
      contextAgent: "Bragi",
      kind: "agent",
      hydrateDurable: true,
    });
  });

  it("rejects an unknown target instead of creating an agent session", () => {
    expect(resolveDeckOpenSession({
      sessionLabel: "Unknown",
      newConversation: true,
      targetAgent: "Unknown",
    }, "scope", "/agents", "ignored")).toEqual({
      key: "screen:scope:/agents",
      label: null,
      contextAgent: null,
      kind: "screen-thread",
      hydrateDurable: false,
    });
  });
});
