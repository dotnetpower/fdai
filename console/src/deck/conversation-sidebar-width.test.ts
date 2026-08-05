import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

import {
  clampConversationWidth,
  CONVERSATION_WIDTH_DEFAULT,
  CONVERSATION_WIDTH_MAX,
  CONVERSATION_WIDTH_MIN,
} from "./conversation-sidebar-width";

describe("conversation sidebar width", () => {
  test("clamps persisted and interactive values to the usable range", () => {
    expect(clampConversationWidth(120)).toBe(CONVERSATION_WIDTH_MIN);
    expect(clampConversationWidth(240)).toBe(240);
    expect(clampConversationWidth(500)).toBe(CONVERSATION_WIDTH_MAX);
    expect(CONVERSATION_WIDTH_DEFAULT).toBe(240);
  });

  test("uses one versioned local preference", () => {
    const source = readFileSync(
      fileURLToPath(new URL("./conversation-sidebar-width.ts", import.meta.url)),
      "utf8",
    );
    expect(source).toContain('"fdai.deck.conversation-width.v1"');
    expect(source).toContain("window.localStorage.getItem");
    expect(source).toContain("window.localStorage.setItem");
  });
});
