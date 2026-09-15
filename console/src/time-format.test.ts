import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "./i18n";
import {
  formatConsoleCompactTimestamp,
  formatConsoleTime,
  formatConsoleTimestamp,
  isRfc3339Timestamp,
} from "./time-format";

afterEach(() => setLocale("en"));

describe("console evidence timestamps", () => {
  test("accepts only complete RFC 3339 instants", () => {
    expect(isRfc3339Timestamp("2026-07-17T08:00:00Z")).toBe(true);
    expect(isRfc3339Timestamp("2026-07-17T17:00:00.123+09:00")).toBe(true);
    expect(isRfc3339Timestamp("2026-07-17")).toBe(false);
    expect(isRfc3339Timestamp("2026-07-17T08:00:00")).toBe(false);
    expect(isRfc3339Timestamp("2026-13-45T25:00:00Z")).toBe(false);
    expect(isRfc3339Timestamp("2026-02-31T00:00:00Z")).toBe(false);
    expect(isRfc3339Timestamp("2026-01-01T24:00:00Z")).toBe(false);
    expect(isRfc3339Timestamp("2026-01-01T00:00:00+09:60")).toBe(false);
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

  test("formats Agent Activity time only in the operator timezone", () => {
    expect(formatConsoleTime("2026-07-24T04:33:12Z", "Asia/Seoul"))
      .toBe("13:33:12 KST");
    expect(formatConsoleTime("2026-07-24T04:33:12Z", "UTC"))
      .toBe("04:33:12 UTC");
    expect(formatConsoleTime("not-a-timestamp", "Asia/Seoul"))
      .toBe("not-a-timestamp");
  });

  test("keeps a date and timezone in compact roster timestamps", () => {
    expect(formatConsoleCompactTimestamp("2026-07-24T04:33:12Z", "Asia/Seoul"))
      .toBe("24 Jul 2026, 13:33 KST");
    expect(formatConsoleCompactTimestamp("2026-07-24T04:33:12Z", "UTC"))
      .toBe("24 Jul 2026, 04:33 UTC");
    expect(formatConsoleCompactTimestamp("not-a-timestamp", "Asia/Seoul"))
      .toBe("not-a-timestamp");
  });
});
