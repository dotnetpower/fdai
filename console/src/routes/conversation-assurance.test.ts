import { describe, expect, it } from "vitest";
import { decodeAssuranceDetail, decodeConversationAssurance } from "./conversation-assurance.model";
import { selectedAssessmentId } from "./conversation-assurance";

const assessment = {
  assessment_id: "assessment-1",
  turn_id: "turn-1",
  conversation_id: "conversation-1",
  state: "completed",
  verdict: "pass",
  content_score: 100,
  confidence: 1,
  criteria: [],
  reasons: ["deterministic_answer_verified"],
  evaluator_identities: [],
  disagreement: false,
  model_calls: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  cost_microusd: 0,
  rubric_version: "1.0.0",
  assessed_at: "2026-07-31T00:00:00+00:00",
};

describe("conversation assurance contracts", () => {
  it("selects only the exact requested turn and never falls back", () => {
    const data = decodeConversationAssurance({
      source: "ledger",
      read_only: true,
      disputes_available: true,
      policy_mutations_available: false,
      summary: {total: 1, pass: 1, fail: 0, inconclusive: 0, deferred: 0, disputes: 0, average_content_score: 100, model_calls: 0, cost_microusd: 0},
      assessments: [assessment],
      disputes: [],
    });

    expect(selectedAssessmentId(data, "turn-1", null)).toBe("assessment-1");
    expect(selectedAssessmentId(data, "turn-missing", "assessment-1")).toBeNull();
    expect(selectedAssessmentId(data, null, null)).toBe("assessment-1");
  });

  it("decodes a bounded read-mostly projection", () => {
    const value = decodeConversationAssurance({
      source: "ledger",
      read_only: true,
      disputes_available: true,
      policy_mutations_available: false,
      summary: {total: 1, pass: 1, fail: 0, inconclusive: 0, deferred: 0, disputes: 0, average_content_score: 100, model_calls: 0, cost_microusd: 0},
      assessments: [assessment],
      disputes: [],
    });
    expect(value.assessments[0]?.verdict).toBe("pass");
  });

  it("rejects policy mutation authority", () => {
    expect(() => decodeConversationAssurance({
      source: "ledger",
      read_only: true,
      disputes_available: true,
      policy_mutations_available: true,
      summary: {},
      assessments: [],
      disputes: [],
    })).toThrow("policy mutation");
  });

  it("rejects inconsistent turn detail availability", () => {
    expect(() => decodeAssuranceDetail({
      assessment,
      turn: {available: true, question: null, answer: null},
    })).toThrow("availability is inconsistent");
  });
});
