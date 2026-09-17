import { describe, expect, test } from "vitest";
import { sampleCostGovernance } from "./cost-governance.sample";
import {
  costDecisionCases,
  costSettlementOutcomes,
  resourceEfficiencyView,
  summarizeSettlements,
} from "./cost-governance.view-model";

describe("Cost Governance Sample projection", () => {
  test.each([
    ["overview", "service-cost"],
    ["resource-efficiency", "resource_candidate"],
    ["optimization-cases", "decision_case"],
    ["outcomes", "settlement_outcome"],
  ] as const)("builds the %s surface with bounded %s records", (surface, expectedKind) => {
    const projection = sampleCostGovernance(surface);

    expect(projection.surface).toBe(surface);
    expect(projection.source_authority).toBe("synthetic-preview");
    expect(projection.items).not.toHaveLength(0);
    expect(projection.items.every((item) => item["kind"] === expectedKind)).toBe(true);
    if (surface === "resource-efficiency") {
      expect(projection.items.every(
        (item) => typeof item["resource"] === "string",
      )).toBe(true);
    }
    expect(projection.analytics?.recommendations.every(
      (recommendation) => recommendation.resource_ref === null,
    )).toBe(true);
  });

  test("keeps Sample candidates, cases, and outcomes explicitly typed", () => {
    const resources = sampleCostGovernance("resource-efficiency");
    const cases = sampleCostGovernance("optimization-cases");
    const projection = sampleCostGovernance("outcomes");

    expect(resourceEfficiencyView(resources).mode).toBe("resource_candidate");
    expect(resourceEfficiencyView(resources).candidates).toHaveLength(2);
    expect(costDecisionCases(cases)).toHaveLength(2);
    const outcomes = costSettlementOutcomes(projection);
    expect(outcomes).toHaveLength(2);
    expect(outcomes.every((item) => item.action_ref && item.action_revision === 1)).toBe(true);
  });

  test("derives presentation-only Sample savings without changing Live evidence", () => {
    const projection = sampleCostGovernance("outcomes");
    const sample = summarizeSettlements(costSettlementOutcomes(projection));

    expect(sample).toMatchObject({
      verifiedSavings: 41400,
      currency: "USD",
      verifiedCount: 2,
    });
  });
});
