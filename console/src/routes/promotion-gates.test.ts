import { describe, expect, it } from "vitest";
import { decodePromotionGates, filterPromotionRows, promotionReasonFromValue } from "./promotion-gates";

const rows = [
  {
    action_type_name: "safe-action",
    shadow_days_elapsed: 7,
    sample_count: 100,
    reviewed_count: 100,
    agreed_count: 100,
    policy_escapes: 0,
    accuracy: 1,
    ready: true,
    gaps: [],
  },
  {
    action_type_name: "escaped-action",
    shadow_days_elapsed: 3,
    sample_count: 20,
    reviewed_count: 10,
    agreed_count: 8,
    policy_escapes: 2,
    accuracy: 0.8,
    ready: false,
    gaps: ["zero policy escapes required"],
  },
] as const;

describe("promotion gate drilldown filters", () => {
  const response = (overrides: Readonly<Record<string, unknown>> = {}) => ({
    window_days: 7,
    ready_count: 0,
    blocked_count: 1,
    rows: [{ ...rows[1], ...overrides }],
  });

  it("rejects malformed metrics at the read API boundary", () => {
    expect(() => decodePromotionGates(response({ action_type_name: " " }))).toThrow(/MUST NOT be empty/);
    expect(() => decodePromotionGates(response({ sample_count: -1 }))).toThrow(/non-negative integer/);
    expect(() => decodePromotionGates(response({ accuracy: 1.1 }))).toThrow(/between 0 and 1/);
    expect(() => decodePromotionGates(response({ shadow_days_elapsed: -0.1 }))).toThrow(/non-negative/);
    expect(() => decodePromotionGates(response({ agreed_count: 11 }))).toThrow(/MUST NOT exceed/);
  });

  it("rejects summary counts that contradict the returned rows", () => {
    expect(() => decodePromotionGates({ ...response(), ready_count: 1, blocked_count: 0 }))
      .toThrow(/summary counts MUST match rows/);
    expect(() => decodePromotionGates({ ...response(), ready_count: -1 }))
      .toThrow(/non-negative integer/);
    expect(() => decodePromotionGates({ ...response(), window_days: -1 }))
      .toThrow(/non-negative number or null/);
  });

  it("deduplicates and stabilizes promotion gaps", () => {
    expect(decodePromotionGates(response({ gaps: ["samples", "accuracy", "samples"] })).rows[0]?.gaps)
      .toEqual(["accuracy", "samples"]);
  });

  it("distinguishes a supported reason from an invalid explicit reason", () => {
    expect(promotionReasonFromValue(null)).toEqual({ reason: null, invalid: null });
    expect(promotionReasonFromValue("policy-escape")).toEqual({
      reason: "policy-escape",
      invalid: null,
    });
    expect(promotionReasonFromValue("missing")).toEqual({ reason: null, invalid: "missing" });
  });

  it("shows only blocked rows with recorded policy escapes", () => {
    expect(filterPromotionRows(rows, "blocked", "", "policy-escape").map((row) => row.action_type_name))
      .toEqual(["escaped-action"]);
  });

  it("combines status and free-text filters without policy escape mode", () => {
    expect(filterPromotionRows(rows, "ready", "safe", null).map((row) => row.action_type_name))
      .toEqual(["safe-action"]);
  });
});
