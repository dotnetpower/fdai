import { describe, expect, test } from "vitest";
import { visibleNavigationGroups } from "./navigation-shell";

describe("navigation shell groups", () => {
  test("shows Labs only in development mode", () => {
    expect(visibleNavigationGroups(false).map((group) => group.id)).toEqual([
      "overview", "operations", "agents", "governance", "evidence",
    ]);
    expect(visibleNavigationGroups(true).map((group) => group.id)).toEqual([
      "overview", "operations", "agents", "governance", "evidence", "labs",
    ]);
  });
});