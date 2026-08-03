import { describe, expect, test } from "vitest";
import {
  customLlmUsageRange,
  llmUsageRangeApiParams,
  llmUsageRangeFromSearch,
  llmUsageRangeInputDates,
  llmUsageRangeSearchParams,
  presetLlmUsageRange,
} from "./llm-cost-range";

const now = new Date("2026-08-04T12:30:00.000Z");

describe("LLM usage date ranges", () => {
  test("builds bounded UTC presets", () => {
    expect(presetLlmUsageRange("24h", now)).toEqual({
      preset: "24h",
      from: "2026-08-03T12:30:00.000Z",
      to: "2026-08-04T12:30:00.000Z",
    });
    expect(presetLlmUsageRange("7d", now)).toEqual({
      preset: "7d",
      from: "2026-07-29T00:00:00.000Z",
      to: "2026-08-05T00:00:00.000Z",
    });
  });

  test("treats a custom end date as inclusive and caps the range", () => {
    const range = customLlmUsageRange("2026-07-20", "2026-07-29");
    expect(range).toEqual({
      preset: "custom",
      from: "2026-07-20T00:00:00.000Z",
      to: "2026-07-30T00:00:00.000Z",
    });
    expect(range && llmUsageRangeInputDates(range)).toEqual({
      fromDate: "2026-07-20",
      toDate: "2026-07-29",
    });
    expect(customLlmUsageRange("2026-01-01", "2026-07-29")).toBeNull();
    expect(customLlmUsageRange("2026-07-30", "2026-07-29")).toBeNull();
  });

  test("restores exact URL cutoffs and separates API params", () => {
    const range = llmUsageRangeFromSearch(new URLSearchParams(
      "range=30d&from=2026-07-06T00%3A00%3A00.000Z&to=2026-08-05T00%3A00%3A00.000Z",
    ), now);
    expect(range.preset).toBe("30d");
    expect(llmUsageRangeSearchParams(range)).toEqual({
      range: "30d",
      from: "2026-07-06T00:00:00.000Z",
      to: "2026-08-05T00:00:00.000Z",
    });
    expect(llmUsageRangeApiParams(range)).toEqual({
      from: "2026-07-06T00:00:00.000Z",
      to: "2026-08-05T00:00:00.000Z",
    });
  });
});
