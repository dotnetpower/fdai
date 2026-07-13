import { describe, expect, test } from "vitest";
import { isRuleListUpdating } from "./rule-catalog.model";

describe("rule catalog list state", () => {
  test("locks stale rows during the search debounce window", () => {
    expect(isRuleListUpdating("disk.unattached", "", false)).toBe(true);
  });

  test("stays locked while the applied query is loading", () => {
    expect(isRuleListUpdating("disk.unattached", "disk.unattached", true)).toBe(true);
  });

  test("unlocks only when the displayed rows match the applied query", () => {
    expect(isRuleListUpdating("disk.unattached", "disk.unattached", false)).toBe(false);
  });
});