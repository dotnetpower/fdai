import { describe, expect, it } from "vitest";
import { decodeAssuranceDetail, decodeConversationAssurance } from "./conversation-assurance.model";
import {
  formatPantheonScore,
  pantheonSafetyTone,
  selectedAssessmentId,
} from "./conversation-assurance";

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

const unavailablePantheon = {
  available: false,
  turns: 0,
  pass: 0,
  review: 0,
  fail: 0,
  hard_zero_fail: 0,
  average_score: null,
  routing_accuracy: null,
  missed_t2_rate: null,
  unnecessary_t2_rate: null,
  agents: [],
};

describe("conversation assurance contracts", () => {
  it("selects only the exact requested turn and never falls back", () => {
    const data = decodeConversationAssurance({
      source: "ledger",
      read_only: true,
      disputes_available: true,
      policy_mutations_available: false,
      summary: {total: 1, pass: 1, fail: 0, inconclusive: 0, deferred: 0, disputes: 0, average_content_score: 100, model_calls: 0, cost_microusd: 0},
      pantheon: unavailablePantheon,
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
      pantheon: {
        available: true,
        turns: 1,
        pass: 1,
        review: 0,
        fail: 0,
        hard_zero_fail: 0,
        average_score: 30,
        routing_accuracy: 1,
        missed_t2_rate: 0,
        unnecessary_t2_rate: 0,
        agents: [{
          agent: "Njord",
          turns: 1,
          average_score: 30,
          minimum_score: 30,
          pass: 1,
          review: 0,
          fail: 0,
          hard_zero_fail: 0,
        }],
      },
      assessments: [assessment],
      disputes: [],
    });
    expect(value.assessments[0]?.verdict).toBe("pass");
    expect(value.pantheon.agents[0]?.agent).toBe("Njord");
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

  it("rejects unavailable Pantheon diagnostics that contain measurements", () => {
    expect(() => decodeConversationAssurance({
      source: "ledger",
      read_only: true,
      disputes_available: true,
      policy_mutations_available: false,
      summary: {total: 0, pass: 0, fail: 0, inconclusive: 0, deferred: 0, disputes: 0, average_content_score: null, model_calls: 0, cost_microusd: 0},
      pantheon: {...unavailablePantheon, average_score: 30},
      assessments: [],
      disputes: [],
    })).toThrow("unavailable Pantheon diagnostics");
  });

  it("keeps unmeasured and hard-zero Pantheon states visually distinct", () => {
    expect(formatPantheonScore(null)).not.toContain("0.0/30");
    expect(formatPantheonScore(0)).toBe("0.0/30");
    expect(pantheonSafetyTone(1)).toBe("danger");
    expect(pantheonSafetyTone(0)).toBe("positive");
  });
});
