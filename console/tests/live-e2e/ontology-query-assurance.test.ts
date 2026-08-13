import { describe, expect, it } from "vitest";
import {
  assuranceOperations,
  generateOntologyAssuranceCohort,
  judgeSemanticReceipt,
  judgeSemanticTurn,
} from "./ontology-query-assurance";

const DIGEST = `sha256:${"a".repeat(64)}`;

function answeredReceipt(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "1.0.0",
    projection_id: `00000000-0000-4000-8000-${"0".repeat(12)}`,
    request_id: `00000000-0000-4000-8000-${"0".repeat(11)}1`,
    disposition: "answered",
    reason_code: "semantic_execution_completed",
    semantic_route: "verified_query_plan",
    ontology_release_digest: DIGEST,
    principal_manifest_digest: DIGEST,
    plan_digest: DIGEST,
    execution_receipt_digest: DIGEST,
    execution_authority: false,
    ...overrides,
  };
}

function verifiedAnswer(overrides: Record<string, unknown> = {}) {
  return {
    status: "verified",
    authority: "ontology-query",
    checks_completed: 2,
    checks_total: 2,
    evidence_refs: ["semantic-plan:generic", "query-execution:generic"],
    reason_code: "semantic_answer_verified",
    claims: [],
    failed_claim_ids: [],
    ...overrides,
  };
}

describe("ontology query assurance cohort", () => {
  it("generates a deterministic, unique 50/50 bilingual cohort", () => {
    const first = generateOntologyAssuranceCohort(0x0fda1);
    const second = generateOntologyAssuranceCohort(0x0fda1);

    expect(first).toEqual(second);
    expect(first).toHaveLength(100);
    expect(new Set(first.map((question) => question.question_id))).toHaveLength(100);
    expect(new Set(first.map((question) => question.prompt))).toHaveLength(100);
    expect(first.filter((question) => question.locale === "en")).toHaveLength(50);
    expect(first.filter((question) => question.locale === "ko")).toHaveLength(50);
    for (const operation of assuranceOperations()) {
      expect(first.filter((question) => question.operation === operation)).toHaveLength(10);
    }
  });

  it("changes only ordering when the seed changes", () => {
    const first = generateOntologyAssuranceCohort(1);
    const second = generateOntologyAssuranceCohort(2);

    expect(first.map((question) => question.question_id)).not.toEqual(
      second.map((question) => question.question_id),
    );
    expect(new Set(first.map((question) => question.question_id))).toEqual(
      new Set(second.map((question) => question.question_id)),
    );
  });

  it("contains no expected answer text or prose-derived oracle fields", () => {
    const questions = generateOntologyAssuranceCohort(0x0fda1);

    for (const question of questions) {
      expect(Object.keys(question).sort()).toEqual([
        "locale",
        "operation",
        "prompt",
        "question_id",
      ]);
    }
  });
});

describe("typed semantic receipt oracle", () => {
  it("accepts a complete authority-free answered receipt", () => {
    expect(judgeSemanticReceipt(answeredReceipt())).toEqual({
      passed: true,
      receipt: answeredReceipt(),
    });
  });

  it.each([
    undefined,
    {},
    answeredReceipt({ semantic_route: undefined }),
    answeredReceipt({ semantic_route: "semantic_clarification" }),
    answeredReceipt({ unavailable_reason: "semantic_planner_unavailable" }),
    answeredReceipt({ execution_receipt_digest: undefined }),
    answeredReceipt({ execution_authority: true }),
  ])("fails closed without inferring a result from prose: %o", (raw) => {
    expect(judgeSemanticReceipt(raw)).toEqual({
      passed: false,
      failure_reason: "invalid_semantic_receipt",
    });
  });

  it("accepts a typed hold without answer digests", () => {
    const held = answeredReceipt({
      disposition: "held",
      reason_code: "historical_evidence_unavailable",
      semantic_route: undefined,
      unavailable_reason: "historical_evidence_unavailable",
      ontology_release_digest: undefined,
      principal_manifest_digest: undefined,
      plan_digest: undefined,
      execution_receipt_digest: undefined,
    });

    expect(judgeSemanticReceipt(held)).toEqual({ passed: true, receipt: held });
  });

  it("requires complete verified evidence for answered turns", () => {
    expect(judgeSemanticTurn(answeredReceipt(), verifiedAnswer())).toEqual({
      passed: true,
      receipt: answeredReceipt(),
      verification: verifiedAnswer(),
    });
  });

  it.each([
    [undefined, "missing_answer_verification"],
    [verifiedAnswer({ status: "unverified" }), "answer_not_verified"],
    [verifiedAnswer({ checks_completed: 1 }), "answer_not_verified"],
    [verifiedAnswer({ checks_completed: 0, checks_total: 0 }), "incomplete_evidence_checks"],
    [verifiedAnswer({ evidence_refs: [] }), "invalid_evidence_refs"],
    [
      verifiedAnswer({ evidence_refs: ["semantic-plan:generic", "semantic-plan:generic"] }),
      "answer_not_verified",
    ],
    [verifiedAnswer({ failed_claim_ids: ["claim-1"] }), "unsupported_or_failed_claim"],
  ])("rejects an answered turn with invalid evidence: %s", (verification, failureReason) => {
    expect(judgeSemanticTurn(answeredReceipt(), verification)).toEqual({
      passed: false,
      failure_reason: failureReason,
    });
  });
});
