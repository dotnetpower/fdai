import { describe, expect, it } from "vitest";
import type { CostGovernanceProjection } from "../api-cost-governance";
import { formatCostAmount } from "./cost-governance-format";
import {
  canPlotResourceCandidates,
  costDecisionCases,
  costSettlementOutcomes,
  incompleteSettlementLineageCount,
  resourceEfficiencyView,
  summarizeCostGovernance,
  summarizeSettlements,
} from "./cost-governance.view-model";

describe("Cost Governance view model", () => {
  it("summarizes disclosed service groups without inventing unavailable values", () => {
    const projection: CostGovernanceProjection = {
      surface: "overview",
      complete: false,
      source_authority: "cost-observation",
      items: [
        {
          kind: "summary",
          group_id: "Compute",
          amount_rounded: "1,200",
          currency: "USD",
          record_count: 3,
          suppressed: false,
        },
        {
          kind: "summary",
          group_id: "Storage",
          amount_band: "100-500",
          currency: "USD",
          record_count: 2,
          suppressed: false,
        },
      ],
      suppressed_count: 0,
    };

    const summary = summarizeCostGovernance(projection);

    expect(summary.knownTotal).toBeNull();
    expect(summary.currency).toBe("USD");
    expect(summary.totalsByCurrency).toEqual({});
    expect(summary.sourceRecordCount).toBe(5);
    expect(summary.rows[0]?.label).toBe("Compute");
    expect(summary.rows[1]?.amount).toBeNull();
    expect(summary.rows[1]?.amountLabel).toBe("100-500");
    expect(summary.largestShare).toBeNull();
  });

  it("does not combine totals across currencies", () => {
    const projection: CostGovernanceProjection = {
      surface: "overview",
      complete: true,
      source_authority: "cost-observation",
      items: [
        { kind: "summary", group_id: "Compute", amount_exact: "10", currency: "USD", record_count: 1 },
        { kind: "summary", group_id: "Compute", amount_exact: "20", currency: "EUR", record_count: 1 },
      ],
      suppressed_count: 0,
    };

    const summary = summarizeCostGovernance(projection);

    expect(summary.knownTotal).toBeNull();
    expect(summary.currency).toBe("");
    expect(summary.totalsByCurrency).toEqual({ USD: 10, EUR: 20 });
  });

  it("keeps positive values below the rounding increment distinct from measured zero", () => {
    const projection: CostGovernanceProjection = {
      surface: "resource-efficiency",
      complete: true,
      source_authority: "cost-observation",
      items: [{
        kind: "summary",
        group_id: "Low-volume service",
        amount_rounded: "100",
        positive_below_rounding_increment: true,
        currency: "USD",
        record_count: 3,
      }],
      suppressed_count: 0,
      disclosure: {
        granularity: "group",
        identity_visibility: "none",
        amount_precision: "rounded",
        small_cell_minimum: 3,
        rounding_increment: 100,
      },
    };

    const summary = summarizeCostGovernance(projection);

    expect(summary.rows[0]?.amount).toBeNull();
    expect(summary.knownTotal).toBeNull();
    expect(formatCostAmount(summary.rows[0]!, projection.disclosure)).toBe("Less than $100");
  });

  it("selects mutually exclusive service-summary and resource-candidate modes", () => {
    const summaryProjection: CostGovernanceProjection = {
      surface: "resource-efficiency",
      complete: true,
      source_authority: "cost-observation",
      items: [{
        kind: "summary",
        group_id: "Compute",
        amount_exact: "10",
        currency: "USD",
        record_count: 1,
      }],
      suppressed_count: 0,
      resource_efficiency_mode: "service_summary",
    };
    const candidateProjection: CostGovernanceProjection = {
      ...summaryProjection,
      items: [{
        kind: "resource_candidate",
        recommendation_ref: "recommendation:0123456789abcdef",
        resource: "resource:0123456789abcdef01234567",
        resource_type: "compute.virtual-machine",
        current_configuration: "general-purpose-4",
        proposed_configuration: "general-purpose-2",
        utilization_metric: "cpu.hourly_average.p95",
        utilization_percent: 18,
        projected_monthly_savings: 25,
        currency: "USD",
        observed_at: "2026-09-17T02:00:00Z",
        source_authority: "azure-advisor",
      }],
      resource_efficiency_mode: "resource_candidate",
    };

    expect(resourceEfficiencyView(summaryProjection)).toMatchObject({
      mode: "service_summary",
      candidates: [],
    });
    expect(resourceEfficiencyView(candidateProjection)).toMatchObject({
      mode: "resource_candidate",
    });
    const candidates = resourceEfficiencyView(candidateProjection).candidates;
    expect(candidates).toHaveLength(1);
    expect(canPlotResourceCandidates(candidates)).toBe(true);
    expect(canPlotResourceCandidates([
      candidates[0]!,
      { ...candidates[0]!, currency: null },
    ])).toBe(false);
    expect(canPlotResourceCandidates([
      candidates[0]!,
      { ...candidates[0]!, currency: "EUR" },
    ])).toBe(false);
  });

  it("uses only owned case and settlement records for later-stage views", () => {
    const projection: CostGovernanceProjection = {
      surface: "outcomes",
      complete: true,
      source_authority: "cost-observation",
      items: [
        {
          kind: "optimization_case",
          record_id: "legacy-case",
          status: "review_ready",
        },
        {
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
        },
        {
          kind: "outcome",
          record_id: "legacy-outcome",
          status: "effect_verified",
          amount_exact: 999,
          currency: "USD",
        },
        {
          kind: "settlement_outcome",
          case_ref: "case:0123456789abcdef01234567",
          revision: 2,
          action_ref: "action:0123456789abcdef01234567",
          action_revision: 1,
          decision_frame_digest: `sha256:${"a".repeat(64)}`,
          terminal: true,
          verified_savings: 12.5,
          currency: "USD",
          rollback_requested: false,
          recovery_observed: false,
          effects: [{
            effect_id: "cost",
            kind: "cost",
            status: "verified",
            reason: "expected_effect_observed",
            terminal: true,
            observation_digest: `sha256:${"b".repeat(64)}`,
            completeness_digest: `sha256:${"c".repeat(64)}`,
          }],
          settled_at: "2026-09-17T02:00:00Z",
        },
        {
          kind: "settlement_outcome",
          case_ref: "case:fedcba9876543210fedcba98",
          revision: 1,
          decision_frame_digest: `sha256:${"d".repeat(64)}`,
          terminal: false,
          verified_savings: null,
          currency: null,
          rollback_requested: false,
          recovery_observed: false,
          effects: [{
            effect_id: "cost",
            kind: "cost",
            status: "unscorable",
            reason: "action_lineage_not_reported",
            terminal: false,
            observation_digest: null,
            completeness_digest: null,
          }],
          settled_at: "2026-09-17T02:00:00Z",
        },
      ],
      suppressed_count: 0,
    };

    expect(costDecisionCases(projection)).toHaveLength(1);
    const outcomes = costSettlementOutcomes(projection);
    expect(outcomes).toHaveLength(1);
    expect(incompleteSettlementLineageCount(projection)).toBe(1);
    expect(summarizeSettlements(outcomes)).toMatchObject({
      verifiedSavings: 12.5,
      currency: "USD",
      verifiedCount: 1,
      failedCount: 0,
    });
  });
});
