import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "./i18n";
import { formatConsoleTimestamp, isRfc3339Timestamp } from "./time-format";

afterEach(() => setLocale("en"));

describe("console evidence timestamps", () => {
  test("accepts only complete RFC 3339 instants", () => {
    expect(isRfc3339Timestamp("2026-07-17T08:00:00Z")).toBe(true);
    expect(isRfc3339Timestamp("2026-07-17T17:00:00.123+09:00")).toBe(true);
    expect(isRfc3339Timestamp("2026-07-17")).toBe(false);
    expect(isRfc3339Timestamp("2026-07-17T08:00:00")).toBe(false);
    expect(isRfc3339Timestamp("2026-13-45T25:00:00Z")).toBe(false);
  });

  test("distinguishes missing, malformed, and valid timestamps", () => {
    expect(formatConsoleTimestamp(null)).toBe("-");
    expect(formatConsoleTimestamp(null, "Unavailable")).toBe("Unavailable");
    expect(formatConsoleTimestamp("not-a-timestamp")).toBe("not-a-timestamp");
    expect(formatConsoleTimestamp("2026-07-17T08:00:00Z")).toMatch(/2026/);
  });

  test("uses the active product locale", () => {
    setLocale("ko");
    expect(formatConsoleTimestamp("2026-07-17T08:00:00Z")).toMatch(/2026/);
  });
});
