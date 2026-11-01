import { describe, expect, test } from "vitest";
import { formatDurationMinutes, formatRelative, formatTimestamp } from "./format";

describe("formatTimestamp", () => {
  test("renders a dash for null", () => {
    expect(formatTimestamp(null)).toBe("\u2013");
  });

  test("renders an invalid string unchanged", () => {
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
  });

  test("renders a valid ISO timestamp as non-empty text with optional origin zone", () => {
    expect(formatTimestamp("2026-10-14T02:00:00Z").length).toBeGreaterThan(0);
    expect(formatTimestamp("2026-10-14T02:00:00Z", "Asia/Seoul")).toContain("(Asia/Seoul)");
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-10-14T12:00:00Z");

  test("renders a dash for null", () => {
    expect(formatRelative(null, now)).toBe("\u2013");
  });

  test("renders seconds ago for a recent past timestamp", () => {
    expect(formatRelative("2026-10-14T11:59:48Z", now)).toContain("second");
  });

  test("renders hours from now for a future timestamp", () => {
    expect(formatRelative("2026-10-14T19:00:00Z", now)).toContain("hour");
  });
});

describe("formatDurationMinutes", () => {
  test("collapses whole days and hours", () => {
    expect(formatDurationMinutes(1_440)).toBe("1 day");
    expect(formatDurationMinutes(2_880)).toBe("2 days");
    expect(formatDurationMinutes(120)).toBe("2 hours");
  });

  test("falls back to minutes", () => {
    expect(formatDurationMinutes(1)).toBe("1 minute");
    expect(formatDurationMinutes(35)).toBe("35 minutes");
  });

  test("returns en-dash safely for negative or non-finite values", () => {
    expect(formatDurationMinutes(Number.NaN)).toBe("\u2013");
    expect(formatDurationMinutes(Number.POSITIVE_INFINITY)).toBe("\u2013");
    expect(formatDurationMinutes(-10)).toBe("\u2013");
  });
});
