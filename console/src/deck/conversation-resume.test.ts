import { describe, expect, test } from "vitest";
import { resumedConversationAt } from "./conversation-resume";

describe("resumedConversationAt", () => {
  const openedAt = Date.parse("2026-08-01T01:30:00Z");

  test("identifies a transcript restored from before this deck mount", () => {
    expect(resumedConversationAt([
      { recordedAt: "2026-07-31T10:57:32Z" },
    ], openedAt)).toBe("2026-07-31T10:57:32Z");
  });

  test("does not label a newly-created turn as restored", () => {
    expect(resumedConversationAt([
      { recordedAt: "2026-08-01T01:29:58Z" },
    ], openedAt)).toBeNull();
  });
});
