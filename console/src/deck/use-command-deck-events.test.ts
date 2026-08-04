import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { resolveDeckOpenSession, shouldDeferDeckOpen } from "./use-command-deck-events";
import { resolveConversationSummary } from "./use-command-deck-submit";
import type { ConversationSummary } from "./conversation-sessions";

const source = readFileSync(
  fileURLToPath(new URL("./use-command-deck-events.ts", import.meta.url)),
  "utf8",
);
const submitSource = readFileSync(
  fileURLToPath(new URL("./use-command-deck-submit.ts", import.meta.url)),
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

  it("creates a fresh user-scoped session for an incident candidate click", () => {
    const detail = {
      sessionKey: "incident:corr-1",
      sessionLabel: "Pod restart",
      newConversation: true,
      binding: {
        kind: "incident",
        incidentId: "INC-1",
        correlationId: "corr-1",
      },
    } as const;

    const first = resolveDeckOpenSession(detail, "scope", "/overview", "first");
    const second = resolveDeckOpenSession(detail, "scope", "/overview", "second");

    expect(first).toEqual({
      key: "user:scope:conversation:first",
      label: "Pod restart",
      contextAgent: "Bragi",
      kind: "screen-thread",
      hydrateDurable: false,
    });
    expect(second.key).not.toBe(first.key);
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

describe("resolveConversationSummary", () => {
  it("prefers synchronously switched bound metadata over stale index state", () => {
    const stale: ConversationSummary = {
      key: "user:scope:conversation:first",
      label: "General",
      kind: "screen-thread",
      originPath: "/overview",
      originLabel: "Dashboard",
      createdAt: "2026-08-04T00:00:00Z",
      updatedAt: "2026-08-04T00:00:00Z",
    };
    const bound: ConversationSummary = {
      ...stale,
      label: "Pod restart",
      binding: {
        kind: "incident",
        incidentId: "INC-1",
        correlationId: "corr-1",
      },
    };

    expect(resolveConversationSummary([stale], new Map([[bound.key, bound]]), bound.key))
      .toEqual(bound);
  });
});

describe("shouldDeferDeckOpen", () => {
  it("defers an automatic access request for active work or an unsent draft", () => {
    expect(shouldDeferDeckOpen({ onlyWhenIdle: true }, true, "")).toBe(true);
    expect(shouldDeferDeckOpen({ onlyWhenIdle: true }, false, "draft")).toBe(true);
    expect(shouldDeferDeckOpen({ onlyWhenIdle: true }, false, "  ")).toBe(false);
    expect(shouldDeferDeckOpen({}, true, "draft")).toBe(false);
  });

  it("submits only an explicitly marked context prompt", () => {
    expect(source).toContain("detail?.submitPrompt === true");
    expect(source).toContain("submitPrompt(seed)");
  });

  it("builds backend history from the selected session before appending the prompt", () => {
    expect(submitSource).toContain("const priorTurns = turnsRef.current");
    expect(submitSource).toContain("backendHistoryForTurns(priorTurns)");
    expect(submitSource).not.toContain("backendHistoryForTurns(turnsRef.current)");
  });
});
