import { describe, expect, it } from "vitest";

import { hasOverflowingText } from "./command-deck-presenters";

describe("conversation title overflow", () => {
  it("enables the full-title tooltip only when the rendered text is truncated", () => {
    expect(hasOverflowingText({ clientWidth: 120, scrollWidth: 121 })).toBe(true);
    expect(hasOverflowingText({ clientWidth: 120, scrollWidth: 120 })).toBe(false);
    expect(hasOverflowingText({ clientWidth: 120, scrollWidth: 80 })).toBe(false);
  });
});
