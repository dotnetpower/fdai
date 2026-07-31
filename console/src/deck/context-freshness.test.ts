import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "../i18n";
import { classifyContextFreshness, contextAgeLabel } from "./context-freshness";

afterEach(() => setLocale("en"));

describe("context freshness", () => {
  const now = Date.parse("2026-08-01T01:30:00Z");

  test("marks a five-minute-old snapshot stale", () => {
    expect(classifyContextFreshness("2026-08-01T01:25:00Z", now)).toEqual({
      state: "stale",
      ageMinutes: 5,
    });
  });

  test("rejects invalid and implausibly future timestamps", () => {
    expect(classifyContextFreshness("invalid", now).state).toBe("unknown");
    expect(classifyContextFreshness("2026-08-01T01:32:00Z", now).state).toBe("unknown");
  });

  test("localizes a visible age instead of showing a bare clock", () => {
    setLocale("ko");
    expect(contextAgeLabel({ state: "stale", ageMinutes: 125 })).toBe("2시간 전");
  });
});
