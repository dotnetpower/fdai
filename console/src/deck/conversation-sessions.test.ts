import { describe, expect, it } from "vitest";
import {
  conversationTitle,
  parseConversationIndex,
  serializeConversationIndex,
  upsertConversation,
  type ConversationSummary,
} from "./conversation-sessions";

const GENERAL: ConversationSummary = {
  key: "screen",
  label: "General",
  kind: "general",
  updatedAt: "2026-07-14T09:00:00Z",
};

describe("conversation index", () => {
  it("round-trips valid summaries and skips malformed entries", () => {
    const raw = JSON.stringify([
      GENERAL,
      { key: "missing-label", kind: "general", updatedAt: GENERAL.updatedAt },
      { key: "bad-date", label: "Bad", kind: "general", updatedAt: "not-a-date" },
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

describe("conversationTitle", () => {
  it("normalizes whitespace and truncates long first prompts", () => {
    expect(conversationTitle("  Explain   this incident  ")).toBe("Explain this incident");
    expect(conversationTitle("abcdefghij", 8)).toBe("abcde...");
  });
});
