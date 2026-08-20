import { describe, expect, test } from "vitest";
import { UserContextRequestError } from "../user-context-client";
import type { ConversationSummary } from "./conversation-sessions";
import {
  conversationHydrationFailureStatus,
  shouldExposeConversationHydration,
} from "./use-command-deck-sessions";

const DURABLE_CONVERSATION: ConversationSummary = {
  key: "conversation:durable",
  label: "Saved investigation",
  kind: "screen-thread",
  originPath: "/overview",
  originLabel: "Overview",
  createdAt: "2026-08-20T00:00:00Z",
  updatedAt: "2026-08-20T00:01:00Z",
  restoredFromServer: true,
};

describe("conversation history hydration", () => {
  test.each([404, 501, 503])("classifies HTTP %s as unavailable", (status) => {
    expect(conversationHydrationFailureStatus(
      new UserContextRequestError("unavailable", status),
    )).toBe("unavailable");
  });

  test("keeps unexpected and transport failures visible as errors", () => {
    expect(conversationHydrationFailureStatus(
      new UserContextRequestError("failed", 500),
    )).toBe("error");
    expect(conversationHydrationFailureStatus(new Error("network failed"))).toBe("error");
  });

  test("keeps default screen restoration non-blocking", () => {
    expect(shouldExposeConversationHydration({
      ...DURABLE_CONVERSATION,
      key: "screen:user:/overview",
      kind: "screen-default",
    })).toBe(false);
    expect(shouldExposeConversationHydration(DURABLE_CONVERSATION)).toBe(true);
    expect(shouldExposeConversationHydration({
      ...DURABLE_CONVERSATION,
      restoredFromServer: false,
    })).toBe(false);
  });
});
