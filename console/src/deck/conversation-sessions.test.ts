import { describe, expect, it } from "vitest";
import {
  conversationLabelForPrompt,
  conversationGroups,
  conversationIndexKeyFor,
  conversationFallbackForRoute,
  conversationPath,
  conversationUserScope,
  conversationTitle,
  isScreenConversationKey,
  parseConversationIndex,
  screenConversationKey,
  serializeConversationIndex,
  upsertConversation,
  userConversationKey,
  type ConversationSummary,
} from "./conversation-sessions";
import { shouldHydrateServerTurns } from "./use-command-deck-sessions";

const GENERAL: ConversationSummary = {
  key: "screen",
  label: "General",
  kind: "screen-default",
  originPath: "/overview",
  originLabel: "Overview",
  createdAt: "2026-07-14T09:00:00Z",
  updatedAt: "2026-07-14T09:00:00Z",
};

describe("conversation index", () => {
  it("round-trips valid summaries and skips malformed entries", () => {
    const raw = JSON.stringify([
      GENERAL,
      { key: "missing-label", kind: "screen-default", updatedAt: GENERAL.updatedAt },
      { key: "bad-date", label: "Bad", kind: "screen-thread", updatedAt: "not-a-date" },
    ]);

    expect(parseConversationIndex(raw)).toEqual([GENERAL]);
    expect(parseConversationIndex(serializeConversationIndex([GENERAL]))).toEqual([GENERAL]);
  });

  it("deduplicates and orders the newest conversation first", () => {
    const updated = { ...GENERAL, label: "General updated", updatedAt: "2026-07-14T10:00:00Z" };
    const agent: ConversationSummary = {
      key: "agent:Forseti",
      label: "Forseti",
      kind: "agent",
      agent: "Forseti",
      originPath: "/agents",
      originLabel: "Agents",
      createdAt: "2026-07-14T09:30:00Z",
      updatedAt: "2026-07-14T09:30:00Z",
    };

    expect(upsertConversation([GENERAL, agent], updated)).toEqual([updated, agent]);
  });

  it("caps the index while retaining the general conversation", () => {
    const conversations = [
      GENERAL,
      { ...GENERAL, key: "conversation:1", label: "One", updatedAt: "2026-07-14T10:00:00Z" },
      { ...GENERAL, key: "conversation:2", label: "Two", updatedAt: "2026-07-14T11:00:00Z" },
    ];

    expect(upsertConversation(conversations, conversations[2]!, 2).map((item) => item.key))
      .toEqual(["conversation:2", "screen"]);
  });
});

describe("conversationGroups", () => {
  it("separates current-screen, other-screen, and agent conversations", () => {
    const currentThread: ConversationSummary = {
      ...GENERAL,
      key: "user:scope:conversation:1",
      label: "Why approvals increased",
      kind: "screen-thread",
      createdAt: "2026-07-14T10:00:00Z",
      updatedAt: "2026-07-14T10:00:00Z",
    };
    const other: ConversationSummary = {
      ...GENERAL,
      key: "screen:scope:/live",
      label: "Live",
      originPath: "/live",
      originLabel: "Live",
    };
    const agent: ConversationSummary = {
      ...GENERAL,
      key: "user:scope:agent:Forseti",
      label: "Forseti",
      kind: "agent",
      agent: "Forseti",
    };

    expect(conversationGroups([GENERAL, currentThread, other, agent], "/overview"))
      .toEqual({
        current: [currentThread, GENERAL],
        other: [other],
        agents: [agent],
      });
  });
});

describe("conversation fallback", () => {
  it("never selects an unrelated-route conversation", () => {
    const otherRoute: ConversationSummary = {
      ...GENERAL,
      key: "screen:scope:/agents",
      originPath: "/agents",
      originLabel: "Agents",
    };

    expect(conversationFallbackForRoute([otherRoute], "scope", "/overview"))
      .toBeUndefined();
  });

  it("prefers the default conversation for the current route", () => {
    const currentThread: ConversationSummary = {
      ...GENERAL,
      key: "user:scope:conversation:1",
      kind: "screen-thread",
    };

    expect(conversationFallbackForRoute([currentThread, GENERAL], "scope", "/overview"))
      .toEqual(GENERAL);
  });

  it("uses a current-route thread when the default is absent", () => {
    const currentThread: ConversationSummary = {
      ...GENERAL,
      key: "user:scope:conversation:1",
      kind: "screen-thread",
    };

    expect(conversationFallbackForRoute([currentThread], "scope", "/overview"))
      .toEqual(currentThread);
  });
});

describe("user and route conversation ownership", () => {
  it("isolates users without exposing their identity in storage keys", () => {
    const first = conversationUserScope("first@example.com", false);
    const second = conversationUserScope("second@example.com", false);

    expect(first).not.toBe(second);
    expect(first).toMatch(/^[0-9a-f]{8}$/);
    expect(conversationIndexKeyFor(first)).not.toContain("example.com");
  });

  it("creates a distinct default session per canonical pathname", () => {
    const scope = conversationUserScope("operator@example.com", false);

    expect(screenConversationKey(scope, "/overview"))
      .not.toBe(screenConversationKey(scope, "/operating-outcomes/mttr"));
    expect(screenConversationKey(scope, "//OVERVIEW/"))
      .toBe(screenConversationKey(scope, "/overview"));
    expect(conversationPath("/overview?window=30d")).toBe("/overview");
    expect(isScreenConversationKey(screenConversationKey(scope, "/overview"))).toBe(true);
    expect(isScreenConversationKey("conversation:1")).toBe(false);
  });

  it("scopes explicit agent sessions once per user", () => {
    const scope = conversationUserScope("operator@example.com", false);
    const key = userConversationKey(scope, "agent:Forseti");

    expect(userConversationKey(scope, key)).toBe(key);
    expect(key).toContain("agent:Forseti");
  });
});

describe("conversationTitle", () => {
  it("normalizes whitespace and truncates long first prompts", () => {
    expect(conversationTitle("  Explain   this incident  ")).toBe("Explain this incident");
    expect(conversationTitle("abcdefghij", 8)).toBe("abcde...");
  });

  it("titles a user-scoped manual thread from its first prompt", () => {
    const manual: ConversationSummary = {
      ...GENERAL,
      key: "user:abc123:conversation:1",
      label: "New conversation",
      kind: "screen-thread",
    };

    expect(conversationLabelForPrompt(manual, "  Explain approvals  ", false))
      .toBe("Explain approvals");
    expect(conversationLabelForPrompt(manual, "Second prompt", true))
      .toBe("New conversation");
    expect(conversationLabelForPrompt(GENERAL, "Explain approvals", false))
      .toBe("General");
  });
});

describe("durable conversation hydration", () => {
  it("skips new ephemeral threads and hydrates only registered empty sessions", () => {
    expect(shouldHydrateServerTurns(false, 0)).toBe(false);
    expect(shouldHydrateServerTurns(true, 0)).toBe(true);
    expect(shouldHydrateServerTurns(true, 1)).toBe(false);
  });
});
