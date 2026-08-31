import { describe, expect, it } from "vitest";
import {
  decodeCostGovernanceAvailability,
  decodeCostGovernanceSettings,
} from "./api-cost-governance";
import { decodeCostGovernanceProjection } from "./api-cost-governance-projection";

describe("Cost Governance availability decoder", () => {
  it("preserves available and enabled as independent fields", () => {
    const decoded = decodeCostGovernanceAvailability({
      available: true,
      enabled: false,
      access_allowed: true,
      availability_reasons: [],
      reason: null,
      activation_revision: 7,
      package_version: "0.1.0",
      image_digest: `sha256:${"a".repeat(64)}`,
      asset_manifest_digest: `sha256:${"b".repeat(64)}`,
      semantic_profile_digest: `sha256:${"c".repeat(64)}`,
      ontology_release_digest: `sha256:${"d".repeat(64)}`,
    });

    expect(decoded.available).toBe(true);
    expect(decoded.enabled).toBe(false);
    expect(decoded.availability_reasons).toEqual([]);
    expect(decoded.activation_revision).toBe(7);
  });

  it("preserves bounded unavailability evidence", () => {
    const decoded = decodeCostGovernanceAvailability({
      available: false,
      enabled: false,
      access_allowed: true,
      availability_reasons: ["missing_provider:cost-estimator"],
      reason: "missing_provider",
      activation_revision: 8,
      package_version: "0.1.0",
      image_digest: `sha256:${"a".repeat(64)}`,
      asset_manifest_digest: `sha256:${"b".repeat(64)}`,
      semantic_profile_digest: `sha256:${"c".repeat(64)}`,
      ontology_release_digest: `sha256:${"d".repeat(64)}`,
    });

    expect(decoded.available).toBe(false);
    expect(decoded.enabled).toBe(false);
    expect(decoded.availability_reasons).toEqual(["missing_provider:cost-estimator"]);
  });
});

describe("Cost Governance settings decoder", () => {
  it("preserves activation authority and unavailable reasons", () => {
    expect(decodeCostGovernanceSettings({
      available: false,
      enabled: false,
      can_manage: true,
      activation_revision: null,
      availability_reasons: ["package_absent"],
      package_version: null,
    })).toEqual({
      available: false,
      enabled: false,
      can_manage: true,
      activation_revision: null,
      availability_reasons: ["package_absent"],
      package_version: null,
    });

  });
});

describe("Cost Governance analytics decoder", () => {
  it("decodes trend, budget, and candidate recommendation evidence", () => {
    const decoded = decodeCostGovernanceProjection({
      surface: "overview",
      complete: true,
      source_authority: "cost-observation",
      items: [],
      suppressed_count: 0,
      analytics: {
        source_authority: "azure-cost-management-budget-advisor",
        observed_at: "2026-08-31T00:00:00Z",
        complete: true,
        trend: [{ observed_on: "2026-08-30", amount: "12.5", currency: "USD", completeness: "1" }],
        budgets: [{
          budget_ref: "budget:0123456789abcdef",
          amount: "100",
          current_spend: "12.5",
          forecast_spend: "80",
          currency: "USD",
          time_grain: "Monthly",
        }],
        recommendations: [{
          recommendation_ref: "recommendation:0123456789abcdef",
          resource_ref: "resource:0123456789abcdef",
          resource_type: "microsoft.compute/disks",
          problem: "Unattached disk",
          solution: "Review whether the disk is required",
          impact: "Medium",
          monthly_savings: "10",
          currency: "USD",
          observed_at: "2026-08-31T00:00:00Z",
          source_authority: "azure-advisor",
        }],
        limitations: [],
      },
    });

    expect(decoded.analytics?.trend[0]?.amount).toBe(12.5);
    expect(decoded.analytics?.budgets[0]?.forecast_spend).toBe(80);
    expect(decoded.analytics?.recommendations[0]?.monthly_savings).toBe(10);
  });
});
