import path from "node:path";

import { describe, expect, test, vi } from "vitest";

import {
  executeGoldenCampaign,
  executeGoldenSequence,
  loadGoldenCampaignCases,
  pressureReason,
  selectGoldenCampaignRange,
  typedOracleReason,
  type GoldenCampaignCase,
} from "./golden-semantic-campaign";

const CASES: readonly GoldenCampaignCase[] = [
  {
    caseId: "case-a.en",
    locale: "en",
    prompt: "Show verified evidence.",
  },
  {
    caseId: "case-a.ko",
    locale: "ko",
    prompt: "검증된 근거를 보여 주세요.",
  },
  {
    caseId: "case-b.en",
    locale: "en",
    prompt: "List current resources.",
  },
];

function typedTurn() {
  return {
    source: "ontology-query",
    semanticReceipt: {
      schema_version: "2.0.0",
      assurance_observation: { schema_version: "1.0.0" },
      execution_authority: false,
    },
  };
}

function oracleTurn(
  campaignCase: GoldenCampaignCase,
  overrides: {
    readonly disposition?: string;
    readonly operation?: string;
    readonly subjectTypes?: readonly string[];
    readonly temporalScope?: string;
    readonly capabilities?: readonly string[];
    readonly receiptAuthority?: boolean;
    readonly assuranceAuthority?: boolean;
  } = {},
) {
  const oracle = campaignCase.oracle;
  if (oracle === undefined) throw new Error("typed oracle is required");
  const disposition = overrides.disposition ?? (
    oracle.allowedDispositions.includes("answered")
      ? "answered"
      : oracle.allowedDispositions[0]
  );
  return {
    source: "ontology-query",
    semanticReceipt: {
      schema_version: "2.0.0",
      disposition,
      execution_authority: overrides.receiptAuthority ?? false,
      assurance_observation: {
        schema_version: "1.0.0",
        frame: {
          operation: overrides.operation ?? oracle.operation,
          subject_types: overrides.subjectTypes ?? [oracle.subjectType],
          temporal_scope: overrides.temporalScope ?? oracle.temporalScope,
        },
        capabilities: overrides.capabilities ?? oracle.requiredCapabilities,
        object_types: oracle.requiredObjectTypes,
        link_types: oracle.requiredLinkTypes,
        function_types: oracle.requiredFunctionTypes,
        fact_kinds: oracle.requiredFactKinds,
        limitation_kinds: oracle.requiredLimitations,
        claim_kinds: [],
        evidence_posture: oracle.evidencePosture,
        authority_posture: oracle.authorityPosture,
        execution_authority: overrides.assuranceAuthority ?? false,
      },
    },
  };
}

describe("golden semantic campaign", () => {
  test("stops before full execution on the first readiness pressure signal", async () => {
    const submit = vi.fn().mockResolvedValue({
      source: "unavailable (backend 429)",
      semanticReceipt: null,
    });

    const result = await executeGoldenCampaign(CASES, submit, {
      readinessCount: 3,
      runFull: true,
      perTurnTimeoutMs: 1_000,
    });

    expect(result).toEqual({
      readinessCompleted: 0,
      fullStarted: false,
      fullCompleted: 0,
      stoppedReason: "http_429",
    });
    expect(submit).toHaveBeenCalledTimes(1);
  });

  test("runs every full turn once only after readiness passes", async () => {
    const submit = vi.fn().mockResolvedValue(typedTurn());

    const result = await executeGoldenCampaign(CASES, submit, {
      readinessCount: 2,
      runFull: true,
      perTurnTimeoutMs: 1_000,
    });

    expect(result).toEqual({
      readinessCompleted: 2,
      fullStarted: true,
      fullCompleted: 3,
      stoppedReason: null,
    });
    expect(submit).toHaveBeenCalledTimes(5);
    expect(submit.mock.calls.every((call) => call.length === 2)).toBe(true);
  });

  test("selects one bounded absolute range without reordering", () => {
    expect(selectGoldenCampaignRange(CASES, 1, 3)).toEqual(CASES.slice(1, 3));
    expect(() => selectGoldenCampaignRange(CASES, -1, 1)).toThrow(
      "golden campaign range is invalid",
    );
    expect(() => selectGoldenCampaignRange(CASES, 1, 1)).toThrow(
      "golden campaign range is invalid",
    );
    expect(() => selectGoldenCampaignRange(CASES, 0, 4)).toThrow(
      "golden campaign range is invalid",
    );
  });

  test("runs a readiness-free sequence exactly once with pressure probes", async () => {
    const submit = vi.fn().mockResolvedValue(typedTurn());
    const pressureProbe = vi.fn().mockResolvedValue(null);

    const result = await executeGoldenSequence(CASES, submit, {
      perTurnTimeoutMs: 1_000,
      pressureProbe,
    });

    expect(result).toEqual({ completed: 3, stoppedReason: null });
    expect(submit).toHaveBeenCalledTimes(3);
    expect(submit.mock.calls.every((call) => call[1] === "full")).toBe(true);
    expect(pressureProbe).toHaveBeenCalledTimes(6);
  });

  test("stops a sequence without retry on typed failure or pressure", async () => {
    const failedSubmit = vi.fn().mockResolvedValue({
      source: "ontology-query",
      semanticReceipt: null,
    });
    const noPressure = vi.fn().mockResolvedValue(null);

    expect(await executeGoldenSequence(CASES, failedSubmit, {
      perTurnTimeoutMs: 1_000,
      pressureProbe: noPressure,
    })).toEqual({ completed: 0, stoppedReason: "semantic_receipt_missing" });
    expect(failedSubmit).toHaveBeenCalledTimes(1);

    const submit = vi.fn().mockResolvedValue(typedTurn());
    const pressure = vi.fn()
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce("runtime_pressure");
    expect(await executeGoldenSequence(CASES, submit, {
      perTurnTimeoutMs: 1_000,
      pressureProbe: pressure,
    })).toEqual({ completed: 0, stoppedReason: "runtime_pressure" });
    expect(submit).toHaveBeenCalledTimes(1);
  });

  test("treats planner unavailability and missing typed assurance as pressure", () => {
    expect(pressureReason({
      source: "unavailable (backend 503)",
      semanticReceipt: null,
    })).toBe("http_503");
    expect(pressureReason({
      source: "ontology-query",
      semanticReceipt: {
        schema_version: "2.0.0",
        unavailable_reason: "semantic_planner_unavailable",
      },
    })).toBe("semantic_planner_unavailable");
    expect(pressureReason({
      source: "ontology-query",
      semanticReceipt: { schema_version: "2.0.0" },
    })).toBe("assurance_observation_missing");
  });

  test("loads exactly 35 direct logical expectations in both locales", async () => {
    const cases = await loadGoldenCampaignCases(
      path.resolve(process.cwd(), "../eval/golden-dataset"),
      { variationKinds: ["direct"], expectedCaseCount: 70 },
    );

    expect(cases).toHaveLength(70);
    expect(new Set(cases.map((item) => item.caseId))).toHaveLength(70);
    expect(new Set(cases.map((item) => item.locale))).toEqual(new Set(["en", "ko"]));
    expect(cases.every((item) => item.oracle !== undefined)).toBe(true);
  });

  test("validates positive and negative typed axes for all 35 direct families", async () => {
    const cases = await loadGoldenCampaignCases(
      path.resolve(process.cwd(), "../eval/golden-dataset"),
      { variationKinds: ["direct"], expectedCaseCount: 70 },
    );
    const logicalFamilies = cases.filter((item) => item.locale === "en");

    expect(logicalFamilies).toHaveLength(35);
    for (const campaignCase of logicalFamilies) {
      const oracle = campaignCase.oracle;
      if (oracle === undefined) throw new Error("typed oracle is required");
      expect(typedOracleReason(campaignCase, oracleTurn(campaignCase))).toBeNull();
      expect(typedOracleReason(campaignCase, oracleTurn(campaignCase, {
        operation: oracle.operation === "select" ? "validate" : "select",
      }))).toBe("semantic_frame_mismatch");
      expect(typedOracleReason(campaignCase, oracleTurn(campaignCase, {
        subjectTypes: [],
      }))).toBe("semantic_frame_mismatch");
      expect(typedOracleReason(campaignCase, oracleTurn(campaignCase, {
        subjectTypes: [oracle.subjectType, "UnexpectedSubject"],
      }))).toBe("semantic_frame_mismatch");
      expect(typedOracleReason(campaignCase, oracleTurn(campaignCase, {
        temporalScope: oracle.temporalScope === "current" ? "historical" : "current",
      }))).toBe("semantic_frame_mismatch");
      expect(typedOracleReason(campaignCase, oracleTurn(campaignCase, {
        receiptAuthority: true,
      }))).toBe("execution_authority_present");
      expect(typedOracleReason(campaignCase, oracleTurn(campaignCase, {
        assuranceAuthority: true,
      }))).toBe("assurance_authority_present");
      if (oracle.allowedDispositions.includes("answered")) {
        expect(typedOracleReason(campaignCase, oracleTurn(campaignCase, {
          capabilities: [],
        }))).toBe("capabilities_mismatch");
      }
      if (oracle.operation !== "action_draft") {
        expect(typedOracleReason(campaignCase, oracleTurn(campaignCase, {
          disposition: "action_draft",
        }))).toBe("disposition_mismatch");
      }
    }
  });

  test("rejects typed receipt substitution without answer matching", () => {
    const campaignCase: GoldenCampaignCase = {
      caseId: "case-a.en",
      locale: "en",
      prompt: "Show verified evidence.",
      oracle: {
        operation: "select",
        subjectType: "Resource",
        temporalScope: "current",
        requiredCapabilities: ["object_set"],
        allowedDispositions: ["answered"],
        requiredObjectTypes: ["Resource"],
        requiredLinkTypes: [],
        requiredFunctionTypes: [],
        requiredFactKinds: ["resource.state"],
        requiredLimitations: [],
        forbiddenClaims: ["execution.completed"],
        evidencePosture: "fresh",
        authorityPosture: "read_only",
      },
    };
    const turn = {
      source: "ontology-query",
      semanticReceipt: {
        schema_version: "2.0.0",
        disposition: "answered",
        execution_authority: false,
        assurance_observation: {
          schema_version: "1.0.0",
          frame: {
            operation: "select",
            subject_types: ["Incident"],
            temporal_scope: "current",
          },
          capabilities: ["object_set"],
          object_types: ["Resource"],
          link_types: [],
          function_types: [],
          fact_kinds: ["resource.state"],
          limitation_kinds: [],
          claim_kinds: [],
          evidence_posture: "fresh",
          authority_posture: "read_only",
          execution_authority: false,
        },
      },
    };

    expect(typedOracleReason(campaignCase, turn)).toBe("semantic_frame_mismatch");
  });

  test("accepts an allowed typed action draft without invented read evidence", () => {
    const campaignCase: GoldenCampaignCase = {
      caseId: "action-a.en",
      locale: "en",
      prompt: "Draft a review-only action.",
      oracle: {
        operation: "action_draft",
        subjectType: "ActionType",
        temporalScope: "none",
        requiredCapabilities: ["action_draft", "ontology_declaration"],
        allowedDispositions: ["action_draft", "held"],
        requiredObjectTypes: ["ActionType"],
        requiredLinkTypes: [],
        requiredFunctionTypes: ["query.ontology_declaration"],
        requiredFactKinds: ["action_type.authority_ceiling"],
        requiredLimitations: ["draft_is_not_approval"],
        forbiddenClaims: ["execution.completed"],
        evidencePosture: "unavailable",
        authorityPosture: "draft_only",
      },
    };
    const turn = {
      source: "ontology-query",
      semanticReceipt: {
        schema_version: "2.0.0",
        disposition: "action_draft",
        execution_authority: false,
        assurance_observation: {
          schema_version: "1.0.0",
          frame: {
            operation: "action_draft",
            subject_types: ["ActionType"],
            temporal_scope: "none",
          },
          capabilities: [],
          object_types: [],
          link_types: [],
          function_types: [],
          fact_kinds: [],
          limitation_kinds: [],
          claim_kinds: [],
          evidence_posture: "unavailable",
          authority_posture: "draft_only",
          execution_authority: false,
        },
      },
    };

    expect(typedOracleReason(campaignCase, turn)).toBeNull();
  });
});
