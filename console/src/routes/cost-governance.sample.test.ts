import { describe, expect, test } from "vitest";
import { sampleOutcomeSavings } from "./cost-governance-format";
import { sampleCostGovernance } from "./cost-governance.sample";
import { summarizeCostGovernance } from "./cost-governance.view-model";

describe("Cost Governance Sample projection", () => {
  test.each([
    ["overview", "service-cost"],
    ["resource-efficiency", "service-cost"],
    ["optimization-cases", "optimization_case"],
    ["outcomes", "outcome"],
  ] as const)("builds the %s surface with bounded %s records", (surface, expectedKind) => {
    const projection = sampleCostGovernance(surface);

    expect(projection.surface).toBe(surface);
    expect(projection.source_authority).toBe("synthetic-preview");
    expect(projection.items).not.toHaveLength(0);
    expect(projection.items.every((item) => item["kind"] === expectedKind)).toBe(true);
    expect(projection.items.every(
      (item) => item["resource"] === undefined || item["resource"] === null,
    )).toBe(true);
    expect(projection.analytics?.recommendations.every(
      (recommendation) => recommendation.resource_ref === null,
    )).toBe(true);
  });

  test("keeps Sample outcome records synthetic and effect-verified", () => {
    const projection = sampleCostGovernance("outcomes");

    expect(projection.items).toHaveLength(2);
    expect(projection.items.every((item) => (
      item["status"] === "effect_verified"
      && item["source_authority"] === "synthetic-preview"
    ))).toBe(true);
  });

  test("derives presentation-only Sample savings without changing Live evidence", () => {
    const projection = sampleCostGovernance("outcomes");
    const summary = summarizeCostGovernance(projection);
    const sample = sampleOutcomeSavings(
      projection.source_authority,
      summary.rows,
      projection.analytics!.recommendations,
    );

    expect(sample).toEqual({
      verifiedSavings: 41400,
      projectedSavings: 68200,
      realization: 41400 / 68200,
      currency: "USD",
    });
    expect(sampleOutcomeSavings(
      "authoritative-live-source",
      summary.rows,
      projection.analytics!.recommendations,
    )).toBeNull();
  });
});
