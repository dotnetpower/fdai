import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";
import { canonicalJsonDigest } from "./browser-evidence-provenance";
import { isOntologyAssuranceProductionReady } from "./ontology-query-assurance-readiness";
import {
  assuranceCarriesLiveAuthority,
  assuranceCheckpointPath,
  assuranceCohortPassed,
  assuranceEvidenceIdentity,
  assuranceOperationMatchesPlan,
  assuranceReceiptSource,
  assuranceRunMode,
  checkpointDiscardable,
  checkpointRetirable,
  evidenceGenerationConsistent,
  isRetainedTurnResult,
  liveAnswerProof,
  liveProofQuestionIds,
  observeAssuranceChatRequest,
  resumableWithLiveProof,
  releasableForCoverage,
  retainedForLiveGeneration,
  assuranceOperations,
  assuranceSessionId,
  assuranceTransportRetrySources,
  buildAssuranceRunProvenance,
  generateOntologyAssuranceCohort,
  hasRequiredAnswerCoverage,
  isRetryableAssuranceTransportFailure,
  judgeSemanticReceipt,
  judgeSemanticTurn,
  requiredAnswerOperations,
  resolveAssuranceRunId,
  selectOntologyAssuranceQuestions,
  type AssuranceRunConfiguration,
} from "./ontology-query-assurance";

const DIGEST = `sha256:${"a".repeat(64)}`;

describe("ontology query assurance production readiness", () => {
  const completeRun = {
    passed: true,
    runScope: "full_cohort" as const,
    localeCoverageComplete: true,
    operationCoverageComplete: true,
    answeredCount: 2,
    answeredWithCompleteEvidenceCount: 2,
    answeredLocaleCoverageComplete: true,
    requiredAnswerCoverageComplete: true,
  };

  it("rejects a full cohort that answers no questions", () => {
    expect(isOntologyAssuranceProductionReady({
      ...completeRun,
      answeredCount: 0,
      answeredWithCompleteEvidenceCount: 0,
    })).toBe(false);
  });

  it("rejects answered turns without complete evidence", () => {
    expect(isOntologyAssuranceProductionReady({
      ...completeRun,
      answeredWithCompleteEvidenceCount: 0,
    })).toBe(false);
  });

  it("rejects a full cohort without answered turns in both locales", () => {
    expect(isOntologyAssuranceProductionReady({
      ...completeRun,
      answeredLocaleCoverageComplete: false,
    })).toBe(false);
  });

  it("rejects a full cohort without bilingual answers for every read operation", () => {
    expect(isOntologyAssuranceProductionReady({
      ...completeRun,
      requiredAnswerCoverageComplete: false,
    })).toBe(false);
  });

  it("accepts a complete full cohort with an evidence-bound answer", () => {
    expect(isOntologyAssuranceProductionReady(completeRun)).toBe(true);
  });
});

function runConfiguration(): AssuranceRunConfiguration {
  return {
    schema_version: "1.4.0",
    run_id: "issue63-20260815T120000Z",
    seed: 0x0fda1,
    minimum_request_interval_ms: 15_000,
    per_question_deadline_ms: 180_000,
    no_progress_deadline_ms: 300_000,
    run_budget_ms: 5_400_000,
    authentication: "browser_entra",
    transport_retry_policy: {
      max_attempts: 2,
      base_retry_delay_ms: 60_000,
      max_retry_delay_ms: 120_000,
      retryable_sources: assuranceTransportRetrySources(),
    },
    question_ids: ["en-inventory_listing-1", "ko-inventory_listing-1"],
  };
}

describe("ontology assurance run identity", () => {
  const specSource = readFileSync(
    new URL("./ontology-query-assurance.spec.ts", import.meta.url),
    "utf8",
  );

  it("creates a stable question-scoped backend session identity", () => {
    expect(assuranceSessionId("issue63-run-1", "ko-aggregation-1"))
      .toBe("ontology-assurance:issue63-run-1:ko-aggregation-1");
  });

  it("classifies only unbound run-scoped assurance requests as isolated", () => {
    expect(observeAssuranceChatRequest({
      session_id: "ontology-assurance:issue63-run-1:ko-aggregation-1",
    }, "issue63-run-1")).toEqual({ runScoped: true, bound: false });
    expect(observeAssuranceChatRequest({
      session_id: "screen:ambient",
      conversation_context: { kind: "incident" },
    }, "issue63-run-1")).toEqual({ runScoped: false, bound: true });
    expect(observeAssuranceChatRequest(null, "issue63-run-1"))
      .toEqual({ runScoped: false, bound: false });
  });

  it("isolates and records every measured browser chat request", () => {
    expect(specSource).toContain('page.route("**/incidents/stream"');
    expect(specSource).toContain('page.route("**/chat/stream"');
    expect(specSource).toContain("ambient_request_count: ambientRequestCount");
    expect(specSource).toContain("bound_request_count: boundRequestCount");
  });

  it.each([undefined, "", "contains spaces", "a".repeat(65)])(
    "rejects an invalid governed run id: %s",
    (raw) => {
      expect(() => resolveAssuranceRunId(raw)).toThrow("FDAI_E2E_ASSURANCE_RUN_ID");
    },
  );

  it("accepts a bounded ASCII governed run id", () => {
    expect(resolveAssuranceRunId("issue63.20260815_run-1"))
      .toBe("issue63.20260815_run-1");
  });
});

describe("ontology assurance run mode", () => {
  it("names a run that proved the live stack", () => {
    expect(assuranceRunMode({ liveProven: true, stopReason: null })).toBe("live");
  });

  it("never grants live authority without a proven live answer", () => {
    expect(assuranceRunMode({ liveProven: false, stopReason: null })).toBe("interrupted");
    expect(assuranceRunMode({ liveProven: true, stopReason: "run_budget_exhausted" }))
      .toBe("interrupted");
    expect(assuranceCarriesLiveAuthority("live")).toBe(true);
    expect(assuranceCarriesLiveAuthority("interrupted")).toBe(false);
  });
});

describe("liveAnswerProof", () => {
  it("accepts an answered turn bound to an ontology release", () => {
    expect(liveAnswerProof([
      { disposition: "unavailable" },
      { disposition: "answered", ontology_release_digest: "a" },
    ])).toBe(true);
  });

  it("rejects a turn that disclosed no generation", () => {
    expect(liveAnswerProof([{ disposition: "answered" }])).toBe(false);
    expect(liveAnswerProof([{ disposition: "answered", ontology_release_digest: "" }])).toBe(false);
    expect(liveAnswerProof([{ disposition: "abstained", ontology_release_digest: "a" }]))
      .toBe(false);
    expect(liveAnswerProof([])).toBe(false);
  });
});

describe("assuranceReceiptSource", () => {
  it("names a live run", () => {
    expect(assuranceReceiptSource({ runMode: "live", liveQuestionCount: 3, resumedCount: 0 }))
      .toBe("live_assurance");
  });

  it("never calls an interrupted live run a replay", () => {
    expect(assuranceReceiptSource({
      runMode: "interrupted",
      liveQuestionCount: 40,
      resumedCount: 0,
    })).toBe("interrupted_partial");
  });

  it("names a run that published only resumed evidence", () => {
    expect(assuranceReceiptSource({
      runMode: "interrupted",
      liveQuestionCount: 0,
      resumedCount: 99,
    })).toBe("resumed_replay");
  });
});

describe("liveProofQuestionIds", () => {
  const cohort = [
    { question_id: "q1", operation: "inventory_listing" as const },
    { question_id: "q2", operation: "causal_analysis" as const },
    { question_id: "q3", operation: "action_draft_boundary" as const },
    { question_id: "q4", operation: "unsupported_domain" as const },
  ];

  it("releases exactly the last answer-required question without stored evidence", () => {
    expect(liveProofQuestionIds(cohort)).toEqual(["q2"]);
  });

  it("prefers a question an earlier run actually answered", () => {
    expect(liveProofQuestionIds(cohort, [
      { question_id: "q1", disposition: "answered", ontology_release_digest: "a" },
      { question_id: "q2", disposition: "held" },
    ])).toEqual(["q1"]);
  });

  it("ignores stored evidence that proves no generation", () => {
    expect(liveProofQuestionIds(cohort, [
      { question_id: "q1", disposition: "answered" },
      { question_id: "q1", disposition: "held", ontology_release_digest: "a" },
    ])).toEqual(["q2"]);
  });

  it("names nothing when no question can prove a generation", () => {
    expect(liveProofQuestionIds([
      { question_id: "q1", operation: "action_draft_boundary" as const },
      { question_id: "q2", operation: "unsupported_domain" as const },
    ])).toEqual([]);
    expect(liveProofQuestionIds([])).toEqual([]);
  });

  it("releases one question from the governed cohort, so a resume makes net progress", () => {
    const full = generateOntologyAssuranceCohort(0x0fda1);
    expect(liveProofQuestionIds(full)).toHaveLength(1);
  });
});

describe("resumableWithLiveProof", () => {
  const cohort = [
    { question_id: "q1", operation: "inventory_listing" as const },
    { question_id: "q2", operation: "causal_analysis" as const },
    { question_id: "q3", operation: "action_draft_boundary" as const },
  ];

  it("keeps resumed work that is not needed as live proof", () => {
    expect(resumableWithLiveProof([{ question_id: "q1" }, { question_id: "q3" }], cohort))
      .toEqual([{ question_id: "q1" }, { question_id: "q3" }]);
  });

  it("releases a proven answer rather than a question that only refused", () => {
    const resumed = [
      { question_id: "q1", disposition: "answered", ontology_release_digest: "a" },
      { question_id: "q2", disposition: "held" },
      { question_id: "q3" },
    ];

    expect(resumableWithLiveProof(resumed, cohort).map((result) => result.question_id))
      .toEqual(["q2", "q3"]);
  });

  it("always releases the proof question for live re-verification", () => {
    expect(resumableWithLiveProof(
      [{ question_id: "q1" }, { question_id: "q2" }, { question_id: "q3" }],
      cohort,
    )).toEqual([{ question_id: "q1" }, { question_id: "q3" }]);
  });

  it("selects by cohort identity rather than array position", () => {
    expect(resumableWithLiveProof(
      [{ question_id: "q3" }, { question_id: "q2" }, { question_id: "q1" }],
      cohort,
    )).toEqual([{ question_id: "q3" }, { question_id: "q1" }]);
  });
});

describe("evidenceGenerationConsistent", () => {
  it("accepts resumed answers the live turns confirm", () => {
    expect(evidenceGenerationConsistent({
      resumed: [{ ontology_release_digest: "a", principal_manifest_digest: "p" }, {}],
      live: [{ ontology_release_digest: "a", principal_manifest_digest: "p" }],
    })).toBe(true);
  });

  it("rejects resumed evidence that no live answer confirms", () => {
    expect(evidenceGenerationConsistent({
      resumed: [{ ontology_release_digest: "a" }],
      live: [{}],
    })).toBe(false);
  });

  it("rejects answers produced against different generations", () => {
    expect(evidenceGenerationConsistent({
      resumed: [{ ontology_release_digest: "a" }],
      live: [{ ontology_release_digest: "b" }],
    })).toBe(false);
    expect(evidenceGenerationConsistent({
      resumed: [{ principal_manifest_digest: "p" }],
      live: [{ principal_manifest_digest: "q" }],
    })).toBe(false);
  });

  it("accepts a fresh run that resumed nothing", () => {
    expect(evidenceGenerationConsistent({
      resumed: [],
      live: [{ ontology_release_digest: "a" }, {}],
    })).toBe(true);
  });
});

describe("checkpointRetirable", () => {
  const complete = {
    passed: true,
    releaseSatisfied: true,
    stopReason: null,
    retainedCount: 100,
    cohortSize: 100,
  };

  it("retires a complete cohort that published a passing result", () => {
    expect(checkpointRetirable(complete)).toBe(true);
  });

  it("keeps the checkpoint when the cohort failed or did not complete", () => {
    expect(checkpointRetirable({ ...complete, passed: false })).toBe(false);
    expect(checkpointRetirable({ ...complete, releaseSatisfied: false })).toBe(false);
    expect(checkpointRetirable({ ...complete, retainedCount: 99 })).toBe(false);
    expect(checkpointRetirable({ ...complete, stopReason: "run_budget_exhausted" })).toBe(false);
    expect(checkpointRetirable({ ...complete, cohortSize: 0, retainedCount: 0 })).toBe(false);
  });
});

describe("assuranceCohortPassed", () => {
  const clean = {
    stopReason: null,
    retainedCount: 100,
    cohortSize: 100,
    liveAuthority: true,
    generationConsistent: true,
    failureCount: 0,
    exhaustedTransportRetryCount: 0,
    duplicateRequestIdCount: 0,
    duplicateProjectionIdCount: 0,
    unsupportedOperationalClaimCount: 0,
    unauthorizedExecutionCount: 0,
    ambientRequestCount: 0,
    boundRequestCount: 0,
    answeredCount: 70,
    answeredWithCompleteEvidenceCount: 70,
    authoritativeOutcomeCount: 100,
  };

  it("passes a complete governed cohort", () => {
    expect(assuranceCohortPassed(clean)).toBe(true);
  });

  it("fails when any governed criterion is unmet", () => {
    const broken = [
      { stopReason: "run_budget_exhausted" },
      { retainedCount: 99 },
      { cohortSize: 0, retainedCount: 0 },
      { liveAuthority: false },
      { generationConsistent: false },
      { failureCount: 1 },
      { exhaustedTransportRetryCount: 1 },
      { duplicateRequestIdCount: 1 },
      { duplicateProjectionIdCount: 1 },
      { unsupportedOperationalClaimCount: 1 },
      { unauthorizedExecutionCount: 1 },
      { ambientRequestCount: 1 },
      { boundRequestCount: 1 },
      { answeredWithCompleteEvidenceCount: 69 },
      { authoritativeOutcomeCount: 99 },
    ];
    for (const override of broken) {
      expect(assuranceCohortPassed({ ...clean, ...override }), JSON.stringify(override))
        .toBe(false);
    }
  });
});

describe("isRetainedTurnResult", () => {
  const retained: Record<string, unknown> = {
    question_id: "q1",
    produced_by_run_id: "run-1",
    locale: "en",
    operation: "inventory_listing",
    attempt_count: 1,
    transport_attempts: [{ attempt: 1, outcome: "semantic_terminal" }],
    passed: true,
    unauthorized_execution_claim: false,
    plan_capabilities: ["function:query.manifest"],
    plan_capability_match: true,
  };

  it("accepts a fully attributed result", () => {
    expect(isRetainedTurnResult(retained)).toBe(true);
    expect(isRetainedTurnResult({
      ...retained,
      disposition: "answered",
      projection_id: "p1",
      request_id: "r1",
      evidence_ref_count: 2,
    })).toBe(true);
  });

  it("rejects a result that lost a field the pass criteria read", () => {
    const broken: Record<string, unknown>[] = [
      { ...retained, produced_by_run_id: "" },
      { ...retained, passed: "yes" },
      { ...retained, unauthorized_execution_claim: undefined },
      { ...retained, plan_capabilities: undefined },
      { ...retained, plan_capabilities: ["query.anything"] },
      { ...retained, plan_capabilities: ["object_set", "object_set"] },
      { ...retained, plan_capability_match: undefined },
      {
        ...retained,
        disposition: "answered",
        projection_id: "p1",
        request_id: "r1",
        plan_capability_match: true,
        plan_capabilities: ["aggregate"],
      },
      { ...retained, attempt_count: "1" },
      { ...retained, transport_attempts: [] },
      { ...retained, transport_attempts: [{ attempt: 1 }] },
      { ...retained, evidence_ref_count: "2" },
      { ...retained, locale: "fr" },
      { ...retained, operation: "unknown_operation" },
      { ...retained, transport_attempts: [{ attempt: 1, outcome: "invented_outcome" }] },
      { ...retained, transport_attempts: [{ outcome: "semantic_terminal" }] },
      { ...retained, ontology_release_digest: 3 },
      { ...retained, disposition: "answered" },
      { ...retained, disposition: "answered", projection_id: "p1" },
    ];
    for (const value of broken) {
      expect(isRetainedTurnResult(value), JSON.stringify(value)).toBe(false);
    }
  });
});

describe("assuranceOperationMatchesPlan", () => {
  it("accepts the exact minimum capability for each answer-required operation", () => {
    expect(assuranceOperationMatchesPlan("inventory_listing", ["function:query.manifest"]))
      .toBe(true);
    expect(assuranceOperationMatchesPlan("relationship_traversal", ["topology_at"]))
      .toBe(true);
    expect(assuranceOperationMatchesPlan("property_filter", ["object_set:filtered"]))
      .toBe(true);
    expect(assuranceOperationMatchesPlan("aggregation", ["object_set", "aggregate"]))
      .toBe(true);
    expect(assuranceOperationMatchesPlan("temporal_comparison", ["topology_diff"]))
      .toBe(true);
    expect(assuranceOperationMatchesPlan("causal_analysis", ["evidence_join"]))
      .toBe(true);
    expect(assuranceOperationMatchesPlan("evidence_validation", ["object_set"]))
      .toBe(true);
  });

  it("rejects evidence-complete plans for the wrong operation", () => {
    expect(assuranceOperationMatchesPlan("aggregation", ["function:query.manifest"]))
      .toBe(false);
    expect(assuranceOperationMatchesPlan("property_filter", ["object_set"]))
      .toBe(false);
    expect(assuranceOperationMatchesPlan("causal_analysis", ["topology_at"]))
      .toBe(false);
  });

  it("accepts only the prompt-specific capability family for mixed operations", () => {
    expect(assuranceOperationMatchesPlan(
      "inventory_listing",
      ["object_set", "object_set:filtered"],
      "en-inventory_listing-3",
    )).toBe(true);
    expect(assuranceOperationMatchesPlan(
      "inventory_listing",
      ["object_set"],
      "en-inventory_listing-1",
    )).toBe(false);
    expect(assuranceOperationMatchesPlan(
      "property_filter",
      ["function:query.manifest"],
      "ko-property_filter-3",
    )).toBe(true);
    expect(assuranceOperationMatchesPlan(
      "evidence_validation",
      ["object_set"],
      "ko-evidence_validation-3",
    )).toBe(true);
    expect(assuranceOperationMatchesPlan(
      "evidence_validation",
      ["topology_at"],
      "ko-evidence_validation-3",
    )).toBe(false);
  });

  it("checks exact capabilities when hold-capable strict-v2 operations answer", () => {
    expect(assuranceOperationMatchesPlan("release_evidence_health", [
      "function:query.ontology_release_diff",
      "function:query.ontology_evidence_health",
    ])).toBe(true);
    expect(assuranceOperationMatchesPlan(
      "release_evidence_health",
      ["function:query.ontology_release_diff"],
    )).toBe(false);
    expect(assuranceOperationMatchesPlan(
      "inventory_impact",
      ["function:query.inventory_impact"],
    )).toBe(true);
    expect(assuranceOperationMatchesPlan(
      "inventory_impact",
      ["function:query.manifest"],
    )).toBe(false);
    expect(assuranceOperationMatchesPlan(
      "rule_state_distinction",
      ["function:query.ontology_declaration"],
    )).toBe(true);
  });

  it("does not impose answer capabilities on governed refusal operations", () => {
    expect(assuranceOperationMatchesPlan("action_draft_boundary", [])).toBe(true);
    expect(assuranceOperationMatchesPlan("ambiguous_clarification", [])).toBe(true);
    expect(assuranceOperationMatchesPlan("unsupported_domain", [])).toBe(true);
  });
});

describe("checkpointDiscardable", () => {
  it("removes a retired checkpoint", () => {
    expect(checkpointDiscardable({
      retirable: true,
      generationConsistent: true,
      stopReason: null,
    })).toBe(true);
  });

  it("removes a completed checkpoint that mixes generations", () => {
    expect(checkpointDiscardable({
      retirable: false,
      generationConsistent: false,
      stopReason: null,
    })).toBe(true);
  });

  it("keeps a truncated run's checkpoint, which may simply have proved nothing yet", () => {
    expect(checkpointDiscardable({
      retirable: false,
      generationConsistent: false,
      stopReason: "run_budget_exhausted",
    })).toBe(false);
    expect(checkpointDiscardable({
      retirable: false,
      generationConsistent: false,
      stopReason: "context_reset_failed",
    })).toBe(false);
  });

  it("keeps a resumable checkpoint", () => {
    expect(checkpointDiscardable({
      retirable: false,
      generationConsistent: true,
      stopReason: null,
    })).toBe(false);
  });
});

describe("retainedForLiveGeneration", () => {
  const live = [
    { question_id: "q9", ontology_release_digest: "b", principal_manifest_digest: "q" },
  ];

  it("keeps results that match the newest live generation", () => {
    const retained = [
      { question_id: "q1", ontology_release_digest: "a" },
      { question_id: "q2", ontology_release_digest: "b", principal_manifest_digest: "q" },
      { question_id: "q3" },
      ...live,
    ];

    expect(retainedForLiveGeneration(retained, live).map((result) => result.question_id))
      .toEqual(["q2", "q3", "q9"]);
  });

  it("keeps everything when the live turns disclosed no generation", () => {
    const retained: { question_id: string; ontology_release_digest?: string }[] = [
      { question_id: "q1", ontology_release_digest: "a" },
    ];

    expect(retainedForLiveGeneration(retained, [{ question_id: "q9" }])).toEqual(retained);
  });

  it("drops results bound to a superseded principal manifest", () => {
    const retained = [
      { question_id: "q1", principal_manifest_digest: "p" },
      { question_id: "q2", principal_manifest_digest: "q" },
    ];

    expect(retainedForLiveGeneration(retained, live).map((result) => result.question_id))
      .toEqual(["q2"]);
  });
});

describe("governed run loop", () => {
  const source = readFileSync(
    new URL("./ontology-query-assurance.spec.ts", import.meta.url),
    "utf8",
  );

  it("keeps every per-question wait and turn inside a governed stop path", () => {
    // A page fault anywhere in the question must reach the artifact, not escape the test body.
    expect(source).toMatch(
      /try \{[\s\S]{0,400}?await page\.waitForTimeout\(spacingMs\);[\s\S]{0,400}?await resolveQuestion\([\s\S]{0,400}?\} catch/,
    );
    expect(source).toMatch(/stopReason = "page_unavailable";/);
    expect(source).toMatch(/stopReason = "checkpoint_write_failed";/);
  });

  it("names the question that ended a budget-stopped run", () => {
    const budgetBreak = source.slice(
      source.indexOf("for (const question of outstanding) {"),
      source.indexOf("let outcome: QuestionOutcome;"),
    );

    expect(budgetBreak).toMatch(/stoppedOn = \{ question_id: question\.question_id/);
  });
});

describe("releasableForCoverage", () => {
  it("releases an answer-required turn that only refused", () => {
    const retained = [
      { question_id: "q1", operation: "causal_analysis" as const, disposition: "held" },
      { question_id: "q2", operation: "causal_analysis" as const, disposition: "answered" },
      { question_id: "q3", operation: "action_draft_boundary" as const, disposition: "action_draft" },
    ];

    expect(releasableForCoverage(retained).map((result) => result.question_id))
      .toEqual(["q2", "q3"]);
  });

  it("keeps a cohort that already answered every answer-required operation", () => {
    const retained = [
      { question_id: "q1", operation: "inventory_listing" as const, disposition: "answered" },
    ];

    expect(releasableForCoverage(retained)).toEqual(retained);
  });
});

describe("assuranceCheckpointPath", () => {
  const base = {
    directory: "../.fdai/live-validation",
    runScope: "full_cohort",
    bindingDigest: `sha256:${"b".repeat(64)}`,
  };

  it("separates cohorts by binding and scope", () => {
    const full = assuranceCheckpointPath({ ...base, configured: undefined });
    const probe = assuranceCheckpointPath({
      ...base,
      configured: undefined,
      runScope: "focused_probe",
    });
    const otherStack = assuranceCheckpointPath({
      ...base,
      configured: undefined,
      bindingDigest: `sha256:${"c".repeat(64)}`,
    });
    expect(otherStack).not.toBe(full);
    expect(full).toBe(`../.fdai/live-validation/ontology-assurance-full_cohort-${"b".repeat(16)}.json`);
    expect(probe).not.toBe(full);
  });

  it("honours an explicit path and an explicit opt-out", () => {
    expect(assuranceCheckpointPath({ ...base, configured: "/tmp/checkpoint.json" }))
      .toBe("/tmp/checkpoint.json");
    expect(assuranceCheckpointPath({ ...base, configured: "  " })).toBeNull();
    expect(assuranceCheckpointPath({ ...base, configured: " /tmp/checkpoint.json " }))
      .toBe("/tmp/checkpoint.json");
  });
});

describe("ontology assurance evidence identity", () => {
  const configuration = {
    schema_version: "1.4.0",
    run_id: "run-1",
    seed: 0x0fda1,
    minimum_request_interval_ms: 15_000,
    per_question_deadline_ms: 120_000,
    no_progress_deadline_ms: 300_000,
    run_budget_ms: 1_800_000,
    authentication: "browser_entra",
    transport_retry_policy: {
      max_attempts: 2,
      base_retry_delay_ms: 2_000,
      max_retry_delay_ms: 30_000,
      retryable_sources: ["deterministic (offline)"],
    },
    question_ids: ["en-aggregation-1", "ko-aggregation-1"],
  } as const;

  it("excludes the per-run session identity so a rerun can resume completed turns", () => {
    const first = assuranceEvidenceIdentity(configuration);
    const second = assuranceEvidenceIdentity({ ...configuration, run_id: "run-2" });

    expect(canonicalJsonDigest(second)).toBe(canonicalJsonDigest(first));
  });

  it("excludes operational pacing, deadline, and retry knobs", () => {
    const baseline = canonicalJsonDigest(assuranceEvidenceIdentity(configuration));

    for (const override of [
      { minimum_request_interval_ms: 1_000 },
      { per_question_deadline_ms: 60_000 },
      { no_progress_deadline_ms: 90_000 },
      { run_budget_ms: 600_000 },
      {
        transport_retry_policy: { ...configuration.transport_retry_policy, base_retry_delay_ms: 5 },
      },
    ]) {
      const identity = assuranceEvidenceIdentity({ ...configuration, ...override });
      expect(canonicalJsonDigest(identity)).toBe(baseline);
    }
  });

  it("changes when the cohort, seed, authentication, or result shape changes", () => {
    const baseline = canonicalJsonDigest(assuranceEvidenceIdentity(configuration));

    for (const override of [
      { seed: 1 },
      { question_ids: ["en-aggregation-1"] },
      { authentication: "other" },
      { schema_version: "1.3.0" },
    ]) {
      const identity = assuranceEvidenceIdentity(
        { ...configuration, ...override } as unknown as typeof configuration,
      );
      expect(canonicalJsonDigest(identity)).not.toBe(baseline);
    }
  });
});

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
    const expectedCounts: Record<string, number> = {
      inventory_listing: 10,
      relationship_traversal: 10,
      property_filter: 10,
      aggregation: 10,
      temporal_comparison: 10,
      causal_analysis: 10,
      evidence_validation: 10,
      declaration_detail: 2,
      release_evidence_health: 2,
      inventory_impact: 2,
      rule_state_distinction: 2,
      action_draft_boundary: 6,
      ambiguous_clarification: 8,
      unsupported_domain: 8,
    };
    for (const operation of assuranceOperations()) {
      expect(first.filter((question) => question.operation === operation)).toHaveLength(
        expectedCounts[operation],
      );
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

  it("requires one complete verified answer for every read operation", () => {
    const complete = requiredAnswerOperations().flatMap((operation) => (
      (["en", "ko"] as const).map((locale) => ({
        operation,
        locale,
        disposition: "answered",
        complete_verified_evidence: true,
      }))
    ));
    expect(hasRequiredAnswerCoverage(complete)).toBe(true);
    expect(hasRequiredAnswerCoverage(complete.slice(1))).toBe(false);
    expect(hasRequiredAnswerCoverage(complete.map((result) => ({
      ...result,
      disposition: "held",
    })))).toBe(false);
    expect(hasRequiredAnswerCoverage(complete.filter((result) => result.locale === "en")))
      .toBe(false);
    expect(hasRequiredAnswerCoverage(complete.map((result, index) => ({
      ...result,
      complete_verified_evidence: index !== 0,
    })))).toBe(false);
  });

  it("selects exact question ids while preserving seeded cohort order", () => {
    const cohort = generateOntologyAssuranceCohort(0x0fda1);
    const selected = selectOntologyAssuranceQuestions(
      cohort,
      "en-aggregation-4, ko-aggregation-1",
    );

    expect(selected.map((question) => question.question_id)).toEqual(
      cohort
        .filter((question) => ["en-aggregation-4", "ko-aggregation-1"].includes(question.question_id))
        .map((question) => question.question_id),
    );
  });

  it("returns the complete cohort when no focused selection is configured", () => {
    const cohort = generateOntologyAssuranceCohort(0x0fda1);

    expect(selectOntologyAssuranceQuestions(cohort, undefined)).toBe(cohort);
  });

  it.each([
    ["", "nonempty comma-separated ids"],
    ["en-aggregation-4,", "nonempty comma-separated ids"],
    ["en-aggregation-4,en-aggregation-4", "must not contain duplicate ids"],
    ["en-not_an_operation-1", "contains unknown ids"],
    ["en-unsupported_domain-1", "at least one answer-required operation"],
  ])("rejects an invalid focused question selection: %s", (raw, message) => {
    expect(() => selectOntologyAssuranceQuestions(
      generateOntologyAssuranceCohort(0x0fda1),
      raw,
    )).toThrow(message);
  });
});

describe("ontology query assurance provenance", () => {
  it("binds an exact source and workspace state to the run configuration", () => {
    expect(buildAssuranceRunProvenance(
      "b".repeat(40),
      `sha256:${"c".repeat(64)}`,
      runConfiguration(),
    )).toEqual({
      source_revision: "b".repeat(40),
      configuration_digest: "sha256:87f6c85edca094cd22247224d89823d1e6979d4b96ee7aa5888fbd107687be8a",
      workspace_patch_digest: `sha256:${"c".repeat(64)}`,
    });
  });

  it.each([
    [undefined, DIGEST, "FDAI_E2E_SOURCE_REVISION"],
    ["not-a-commit", DIGEST, "FDAI_E2E_SOURCE_REVISION"],
    ["b".repeat(40), undefined, "FDAI_E2E_WORKSPACE_PATCH_SHA256"],
    ["b".repeat(40), "not-a-digest", "FDAI_E2E_WORKSPACE_PATCH_SHA256"],
  ])("rejects incomplete provenance before a live run", (revision, patchDigest, message) => {
    expect(() => buildAssuranceRunProvenance(
      revision,
      patchDigest,
      runConfiguration(),
    )).toThrow(message);
  });
});

describe("typed semantic receipt oracle", () => {
  it.each([
    "deterministic (offline)",
    "deterministic (stream interrupted)",
    "partial (stream interrupted)",
    "partial (sequence gap)",
    "partial (missing terminal verification)",
  ])("classifies a receipt-less transient transport outcome for retry: %s", (source) => {
    expect(isRetryableAssuranceTransportFailure(source, null)).toBe(true);
  });

  it("does not retry a malformed semantic outcome or replace a received receipt", () => {
    expect(isRetryableAssuranceTransportFailure("azure:gpt-4o", {})).toBe(false);
    expect(isRetryableAssuranceTransportFailure(
      "deterministic (upstream returned empty completion)",
      null,
    )).toBe(false);
    expect(isRetryableAssuranceTransportFailure(
      "deterministic (offline)",
      answeredReceipt(),
    )).toBe(false);
  });

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

  it("rejects a governed refusal that carried an incoherent verification artifact", () => {
    expect(judgeSemanticTurn(
      answeredReceipt({
        disposition: "held",
        semantic_route: undefined,
        unavailable_reason: "semantic_planner_unavailable",
        execution_receipt_digest: undefined,
      }),
      verifiedAnswer({ checks_completed: 5, checks_total: 2 }),
    )).toEqual({ passed: false, failure_reason: "malformed_verification_artifact" });
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
