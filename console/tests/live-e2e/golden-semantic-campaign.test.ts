import { describe, expect, test, vi } from "vitest";

import {
  executeGoldenCampaign,
  pressureReason,
  type GoldenCampaignCase,
} from "./golden-semantic-campaign";

const CASES: readonly GoldenCampaignCase[] = [
  {
    caseId: "case-a.en",
    locale: "en",
    prompt: "Show verified evidence.",
    runtimeContext: "none",
  },
  {
    caseId: "case-a.ko",
    locale: "ko",
    prompt: "검증된 근거를 보여 주세요.",
    runtimeContext: "none",
  },
  {
    caseId: "case-b.en",
    locale: "en",
    prompt: "List current resources.",
    runtimeContext: "none",
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

  test("treats planner unavailability and missing typed assurance as pressure", () => {
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
});
