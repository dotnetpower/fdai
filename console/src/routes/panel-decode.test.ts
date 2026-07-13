import { describe, expect, test } from "vitest";
import { decodeLlmCost } from "./llm-cost";
import { decodePromotionGates } from "./promotion-gates";

describe("optional panel response decoders", () => {
  test("reject malformed LLM cost and promotion responses", () => {
    expect(() => decodeLlmCost({})).toThrow(/invalid read API response/);
    expect(() => decodePromotionGates({ rows: null })).toThrow(/invalid read API response/);
    expect(() => decodePromotionGates({
      window_days: null,
      ready_count: 0,
      blocked_count: 1,
      rows: [{ action_type_name: "x", shadow_days_elapsed: 0, sample_count: 0, reviewed_count: 0, agreed_count: 0, policy_escapes: 0, accuracy: 0, ready: false, gaps: [null] }],
    })).toThrow(/only strings/);
  });
});