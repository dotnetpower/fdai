import { describe, expect, test } from "vitest";
import { parseAnswerPlan } from "./backend";

const validPlan = {
  intent: "comparison",
  detail_level: "deep",
  format: "table",
  sections: ["criteria", "items", "trade_offs", "recommendation"],
  evidence_requirement: "server_read_model",
  max_words: 650,
  discuss: "skip",
  subject: "Compare T1 and T2",
  explicit_overrides: ["deep", "table"],
};

describe("AnswerPlan boundary parser", () => {
  test("keeps bounded presentation metadata and drops the raw subject", () => {
    expect(parseAnswerPlan(validPlan)).toEqual({
      intent: "comparison",
      detail_level: "deep",
      format: "table",
      sections: ["criteria", "items", "trade_offs", "recommendation"],
      evidence_requirement: "server_read_model",
      max_words: 650,
      discuss: "skip",
      explicit_overrides: ["deep", "table"],
      preference_applied: false,
    });
  });

  test.each([
    { ...validPlan, intent: "execute" },
    { ...validPlan, max_words: 100_000 },
    { ...validPlan, sections: Array.from({ length: 13 }, (_, index) => `s${index}`) },
    { ...validPlan, sections: ["s".repeat(65)] },
    { ...validPlan, explicit_overrides: ["x".repeat(129)] },
    { ...validPlan, discuss: "recursive" },
  ])("rejects malformed metadata", (value) => {
    expect(parseAnswerPlan(value)).toBeUndefined();
  });
});
