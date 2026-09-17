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

  it("decodes additive evidence, readiness, and resource candidates", () => {
    const decoded = decodeCostGovernanceProjection({
      surface: "resource-efficiency",
      complete: false,
      generated_at: "2026-09-17T02:30:00Z",
      source_authority: "cost-observation",
      suppressed_count: 0,
      disclosure: {
        granularity: "resource",
        identity_visibility: "pseudonymous",
        amount_precision: "rounded",
        small_cell_minimum: 3,
        rounding_increment: "100",
      },
      resource_efficiency_mode: "resource_candidate",
      items: [{
        kind: "resource_candidate",
        recommendation_ref: "recommendation:0123456789abcdef",
        resource: "resource:0123456789abcdef01234567",
        resource_type: "compute.virtual-machine",
        current_configuration: "general-purpose-4",
        proposed_configuration: "general-purpose-2",
        utilization_metric: "cpu.hourly_average.p95",
        utilization_percent: "18.5",
        projected_monthly_savings: "42.25",
        currency: "USD",
        observed_at: "2026-09-17T02:00:00Z",
        source_authority: "azure-advisor",
      }],
      evidence: {
        window_start_at: "2026-08-18T00:00:00Z",
        window_end_at: "2026-09-17T00:00:00Z",
        latest_source_at: "2026-09-17T02:00:00Z",
        freshness: "fresh",
        freshness_threshold_seconds: 172800,
        complete_count: 9,
        partial_count: 1,
        sources: [{
          source_authority: "azure-cost-management",
          state: "partial",
          window_start_at: "2026-08-18T00:00:00Z",
          window_end_at: "2026-09-17T00:00:00Z",
          latest_source_at: "2026-09-17T02:00:00Z",
          complete_count: 9,
          partial_count: 1,
          reason: "pagination_incomplete",
        }],
        disclosure: {
          granularity: "resource",
          identity_visibility: "pseudonymous",
          amount_precision: "rounded",
          small_cell_minimum: 3,
          rounding_increment: "100",
        },
        readiness: [
          { surface: "observations", state: "partial", reason: "observations_partial", record_count: 10, latest_evidence_at: "2026-09-17T02:00:00Z" },
          { surface: "analytics", state: "complete", reason: null, record_count: 1, latest_evidence_at: "2026-09-17T02:00:00Z" },
          { surface: "resource-candidates", state: "complete", reason: null, record_count: 1, latest_evidence_at: "2026-09-17T02:00:00Z" },
          { surface: "decision-cases", state: "unavailable", reason: "decision_cases_missing", record_count: 0, latest_evidence_at: null },
          { surface: "settlements", state: "unavailable", reason: "settlements_missing", record_count: 0, latest_evidence_at: null },
        ],
        latest_analytics_run: {
          run_id: `costrun:${"f".repeat(64)}`,
          scope_digest: `sha256:${"e".repeat(64)}`,
          venue: "local",
          window_start_at: "2026-08-18T00:00:00Z",
          window_end_at: "2026-09-17T00:00:00Z",
          started_at: "2026-09-17T01:58:00Z",
          finished_at: "2026-09-17T02:00:00Z",
          status: "complete",
          sources: [],
          observation_count: 10,
          trend_point_count: 30,
          budget_count: 1,
          recommendation_count: 1,
          utilization_count: 1,
          limitations: [],
          failure_reason: null,
          snapshot_id: `analytics:${"d".repeat(64)}`,
        },
      },
    });

    expect(decoded.resource_efficiency_mode).toBe("resource_candidate");
    expect(decoded.disclosure?.rounding_increment).toBe(100);
    expect(decoded.evidence?.freshness).toBe("fresh");
    expect(decoded.evidence?.readiness).toHaveLength(5);
    expect(decoded.evidence?.latest_analytics_run?.status).toBe("complete");
    expect(decoded.items[0]?.["utilization_percent"]).toBe(18.5);
  });

  it.each([
    ["analytics", "analytics_snapshot_missing"],
    ["observations", "projection_truncated"],
  ] as const)("accepts the %s readiness reason %s", (surface, reason) => {
    const decoded = decodeCostGovernanceProjection({
      surface: "overview",
      complete: false,
      source_authority: "azure-cost-management",
      items: [],
      suppressed_count: 0,
      evidence: {
        window_start_at: null,
        window_end_at: null,
        latest_source_at: null,
        freshness: "unknown",
        freshness_threshold_seconds: 172800,
        complete_count: 0,
        partial_count: 0,
        sources: [],
        disclosure: {
          granularity: "group",
          identity_visibility: "none",
          amount_precision: "rounded",
          small_cell_minimum: 3,
          rounding_increment: 100,
        },
        readiness: [
          {
            surface: "observations",
            state: surface === "observations" ? "unavailable" : "complete",
            reason: surface === "observations" ? reason : null,
            record_count: 0,
            latest_evidence_at: null,
          },
          {
            surface: "analytics",
            state: surface === "analytics" ? "unavailable" : "complete",
            reason: surface === "analytics" ? reason : null,
            record_count: 0,
            latest_evidence_at: null,
          },
          {
            surface: "resource-candidates",
            state: "complete",
            reason: null,
            record_count: 0,
            latest_evidence_at: null,
          },
          {
            surface: "decision-cases",
            state: "complete",
            reason: null,
            record_count: 0,
            latest_evidence_at: null,
          },
          {
            surface: "settlements",
            state: "complete",
            reason: null,
            record_count: 0,
            latest_evidence_at: null,
          },
        ],
        latest_analytics_run: null,
      },
    });

    expect(
      decoded.evidence?.readiness.find((item) => item.surface === surface)?.reason,
    ).toBe(reason);
  });

  it("keeps legacy projections valid when additive evidence is absent", () => {
    const decoded = decodeCostGovernanceProjection({
      surface: "resource-efficiency",
      complete: true,
      source_authority: "cost-observation",
      items: [{
        kind: "summary",
        group_id: "Compute",
        amount_rounded: "100",
        positive_below_rounding_increment: true,
        currency: "USD",
        record_count: 3,
      }],
      suppressed_count: 0,
    });

    expect(decoded.evidence).toBeNull();
    expect(decoded.resource_efficiency_mode).toBeNull();
    expect(decoded.items[0]?.["positive_below_rounding_increment"]).toBe(true);
  });

  it("decodes owned decision cases and independently settled outcomes", () => {
    const caseProjection = decodeCostGovernanceProjection({
      surface: "optimization-cases",
      complete: true,
      source_authority: "forseti-observation-mode",
      suppressed_count: 0,
      items: [{
        kind: "decision_case",
        case_ref: "case:0123456789abcdef01234567",
        revision: 1,
        target_refs: ["resource:0123456789abcdef01234567"],
        evidence_cutoff: "2026-09-17T02:00:00Z",
        decision_frame_digest: `sha256:${"a".repeat(64)}`,
        option_ids: ["option.no-action"],
        selected_option_id: "option.no-action",
        verdict: "hold",
        reason: "observation_mode",
        evidence_refs: ["observation:1"],
        evidence_sources: ["forseti"],
        recovery_steps: [],
        recorded_at: "2026-09-17T02:00:00Z",
        source_authority: "forseti-observation-mode",
      }],
    });
    const outcomeProjection = decodeCostGovernanceProjection({
      surface: "outcomes",
      complete: true,
      source_authority: "heimdall-settlement",
      suppressed_count: 0,
      items: [{
        kind: "settlement_outcome",
        case_ref: "case:0123456789abcdef01234567",
        revision: 2,
        action_ref: "action:0123456789abcdef01234567",
        action_revision: 1,
        decision_frame_digest: `sha256:${"a".repeat(64)}`,
        terminal: true,
        verified_savings: "12.5",
        currency: "USD",
        rollback_requested: false,
        recovery_observed: false,
        effects: [{
          effect_id: "effect-cost",
          kind: "cost",
          status: "verified",
          reason: "expected_effect_observed",
          terminal: true,
          observation_digest: `sha256:${"b".repeat(64)}`,
          completeness_digest: `sha256:${"c".repeat(64)}`,
        }],
        settled_at: "2026-09-17T02:00:00Z",
      }],
    });

    expect(caseProjection.items[0]?.["case_ref"]).toBe(
      "case:0123456789abcdef01234567",
    );
    expect(outcomeProjection.items[0]?.["verified_savings"]).toBe(12.5);
  });

  it("decodes a retained settlement that predates additive action lineage", () => {
    const decoded = decodeCostGovernanceProjection({
      surface: "outcomes",
      complete: false,
      source_authority: "heimdall-settlement",
      suppressed_count: 0,
      items: [{
        kind: "settlement_outcome",
        case_ref: "case:0123456789abcdef01234567",
        revision: 1,
        decision_frame_digest: `sha256:${"a".repeat(64)}`,
        terminal: false,
        verified_savings: null,
        currency: null,
        rollback_requested: false,
        recovery_observed: false,
        effects: [{
          effect_id: "effect-cost",
          kind: "cost",
          status: "unscorable",
          reason: "action_lineage_not_reported",
          terminal: false,
          observation_digest: null,
          completeness_digest: null,
        }],
        settled_at: "2026-09-17T02:00:00Z",
      }],
    });

    expect(decoded.items[0]?.["action_ref"]).toBeNull();
    expect(decoded.items[0]?.["action_revision"]).toBeNull();
  });

  it("rejects a partial action-lineage pair", () => {
    expect(() => decodeCostGovernanceProjection({
      surface: "outcomes",
      complete: false,
      source_authority: "heimdall-settlement",
      suppressed_count: 0,
      items: [{
        kind: "settlement_outcome",
        case_ref: "case:0123456789abcdef01234567",
        revision: 1,
        action_ref: "action:0123456789abcdef01234567",
        decision_frame_digest: `sha256:${"a".repeat(64)}`,
        terminal: false,
        verified_savings: null,
        currency: null,
        rollback_requested: false,
        recovery_observed: false,
        effects: [{
          effect_id: "effect-cost",
          kind: "cost",
          status: "unscorable",
          reason: "settlement_pending",
          terminal: false,
          observation_digest: null,
          completeness_digest: null,
        }],
        settled_at: "2026-09-17T02:00:00Z",
      }],
    })).toThrow(/reported together/);
  });

  it("rejects a verified savings value without its currency", () => {
    expect(() => decodeCostGovernanceProjection({
      surface: "outcomes",
      complete: true,
      source_authority: "heimdall-settlement",
      suppressed_count: 0,
      items: [{
        kind: "settlement_outcome",
        case_ref: "case:0123456789abcdef01234567",
        revision: 2,
        action_ref: "action:0123456789abcdef01234567",
        action_revision: 1,
        decision_frame_digest: `sha256:${"a".repeat(64)}`,
        terminal: true,
        verified_savings: "12.5",
        rollback_requested: false,
        recovery_observed: false,
        effects: [{
          effect_id: "effect-cost",
          kind: "cost",
          status: "verified",
          reason: "expected_effect_observed",
          terminal: true,
          observation_digest: `sha256:${"b".repeat(64)}`,
          completeness_digest: `sha256:${"c".repeat(64)}`,
        }],
        settled_at: "2026-09-17T02:00:00Z",
      }],
    })).toThrow(/currency/);
  });
});
