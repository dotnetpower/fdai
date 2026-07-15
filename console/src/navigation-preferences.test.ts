import { describe, expect, test } from "vitest";
import {
  DEFAULT_NAVIGATION_PREFERENCES,
  navigationPreferenceKey,
  readNavigationPreferences,
  resetNavigationPreferences,
  writeNavigationPreferences,
} from "./navigation-preferences";

function storage(values: Readonly<Record<string, string>> = {}) {
  const data = new Map(Object.entries(values));
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => { data.set(key, value); },
    removeItem: (key: string) => { data.delete(key); },
  };
}

describe("navigation preferences", () => {
  test("uses an account-scoped storage key", () => {
    expect(navigationPreferenceKey("account-a")).toBe("fdai:console:navigation:v1:account-a");
    expect(navigationPreferenceKey(null)).toBe("fdai:console:navigation:v1:local");
  });

  test("returns stable defaults without stored state", () => {
    expect(readNavigationPreferences(["dashboard"], "account-a", null))
      .toEqual(DEFAULT_NAVIGATION_PREFERENCES);
  });

  test("filters unknown panels and duplicate ids", () => {
    const key = navigationPreferenceKey("account-a");
    const store = storage({
      [key]: JSON.stringify({
        explorerOpen: false,
        hiddenPanelIds: ["audit", "removed", "audit"],
        groupOrder: {
          evidence: ["audit", "removed", "audit", "rca"],
          labs: ["labs"],
          obsolete: ["audit"],
        },
      }),
    });

    expect(readNavigationPreferences(["audit", "rca", "labs"], "account-a", store)).toEqual({
      explorerOpen: false,
      hiddenPanelIds: ["audit"],
      groupOrder: { evidence: ["audit", "rca"], labs: ["labs"] },
    });
  });

  test("writes and resets the scoped preference", () => {
    const store = storage();
    const preferences = {
      explorerOpen: true,
      hiddenPanelIds: ["audit"],
      groupOrder: { evidence: ["rca", "audit"] },
    } as const;

    expect(writeNavigationPreferences(preferences, "account-a", store)).toBe(true);
    expect(readNavigationPreferences(["audit", "rca"], "account-a", store)).toEqual(preferences);
    expect(resetNavigationPreferences("account-a", store)).toBe(true);
    expect(readNavigationPreferences(["audit", "rca"], "account-a", store))
      .toEqual(DEFAULT_NAVIGATION_PREFERENCES);
  });
});
