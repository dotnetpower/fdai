import type {
  CostGovernanceProjection,
  CostGovernanceSurface,
} from "../api-cost-governance";

const SAMPLE_AT = "2026-08-31T09:00:00Z";
const SAMPLE_DIGEST = `sha256:${"a".repeat(64)}`;

const COST_ITEMS: CostGovernanceProjection["items"] = [
  {
    record_id: "sample-compute",
    kind: "service-cost",
    service_id: "Compute",
    amount_exact: 42800,
    currency: "USD",
    record_count: 84,
    status: "observed",
    observed_at: SAMPLE_AT,
    completeness: 1,
    relative_change: -0.08,
    source_authority: "synthetic-preview",
  },
  {
    record_id: "sample-database",
    kind: "service-cost",
    service_id: "Databases",
    amount_exact: 31600,
    currency: "USD",
    record_count: 42,
    status: "observed",
    observed_at: SAMPLE_AT,
    completeness: 1,
    relative_change: 0.04,
    source_authority: "synthetic-preview",
  },
  {
    record_id: "sample-observability",
    kind: "service-cost",
    service_id: "Observability",
    amount_exact: 18400,
    currency: "USD",
    record_count: 36,
    status: "observed",
    observed_at: SAMPLE_AT,
    completeness: 1,
    relative_change: -0.03,
    source_authority: "synthetic-preview",
  },
  {
    record_id: "sample-ai",
    kind: "service-cost",
    service_id: "AI services",
    amount_exact: 12700,
    currency: "USD",
    record_count: 28,
    status: "observed",
    observed_at: SAMPLE_AT,
    completeness: 1,
    relative_change: 0.06,
    source_authority: "synthetic-preview",
  },
];

const OPTIMIZATION_CASE_ITEMS: CostGovernanceProjection["items"] = [
  {
    record_id: "sample-case-compute",
    kind: "optimization_case",
    resource: null,
    service_id: "Compute",
    amount_exact: 18400,
    currency: "USD",
    status: "review_ready",
    observed_at: SAMPLE_AT,
    completeness: 1,
    relative_change: -0.08,
    source_authority: "synthetic-preview",
    provenance_digest: SAMPLE_DIGEST,
  },
  {
    record_id: "sample-case-database",
    kind: "optimization_case",
    resource: null,
    service_id: "Databases",
    amount_exact: 49800,
    currency: "USD",
    status: "review_ready",
    observed_at: SAMPLE_AT,
    completeness: 1,
    relative_change: -0.12,
    source_authority: "synthetic-preview",
    provenance_digest: SAMPLE_DIGEST,
  },
];

const OUTCOME_ITEMS: CostGovernanceProjection["items"] = [
  {
    record_id: "sample-outcome-compute",
    kind: "outcome",
    resource: null,
    service_id: "Compute",
    amount_exact: 12800,
    currency: "USD",
    status: "effect_verified",
    observed_at: SAMPLE_AT,
    completeness: 1,
    relative_change: -0.06,
    source_authority: "synthetic-preview",
    provenance_digest: SAMPLE_DIGEST,
  },
  {
    record_id: "sample-outcome-database",
    kind: "outcome",
    resource: null,
    service_id: "Databases",
    amount_exact: 28600,
    currency: "USD",
    status: "effect_verified",
    observed_at: SAMPLE_AT,
    completeness: 1,
    relative_change: -0.09,
    source_authority: "synthetic-preview",
    provenance_digest: SAMPLE_DIGEST,
  },
];

function sampleItems(
  surface: CostGovernanceSurface,
): CostGovernanceProjection["items"] {
  if (surface === "optimization-cases") return OPTIMIZATION_CASE_ITEMS;
  if (surface === "outcomes") return OUTCOME_ITEMS;
  return COST_ITEMS;
}

export function sampleCostGovernance(
  surface: CostGovernanceSurface,
): CostGovernanceProjection {
  return {
    surface,
    complete: true,
    source_authority: "synthetic-preview",
    items: sampleItems(surface),
    suppressed_count: 0,
    analytics: {
      source_authority: "synthetic-preview",
      observed_at: SAMPLE_AT,
      complete: true,
      trend: [
        { observed_on: "2026-08-25", amount: 118400, currency: "USD", completeness: 1 },
        { observed_on: "2026-08-26", amount: 116900, currency: "USD", completeness: 1 },
        { observed_on: "2026-08-27", amount: 114800, currency: "USD", completeness: 1 },
        { observed_on: "2026-08-28", amount: 112600, currency: "USD", completeness: 1 },
        { observed_on: "2026-08-29", amount: 108900, currency: "USD", completeness: 1 },
        { observed_on: "2026-08-30", amount: 106700, currency: "USD", completeness: 1 },
        { observed_on: "2026-08-31", amount: 105500, currency: "USD", completeness: 1 },
      ],
      budgets: [
        {
          budget_ref: "sample-budget-primary",
          amount: 140000,
          current_spend: 105500,
          forecast_spend: 128400,
          currency: "USD",
          time_grain: "Monthly",
        },
      ],
      recommendations: [
        {
          recommendation_ref: "sample-rec-compute",
          resource_ref: null,
          resource_type: "compute.virtual-machine",
          problem: "Underused compute capacity",
          solution: "Review a smaller SKU",
          impact: "Medium",
          monthly_savings: 18400,
          currency: "USD",
          current_sku: "sample-large",
          target_sku: "sample-medium",
          utilization_percent: 18,
          utilization_metric: "cpu",
          observed_at: SAMPLE_AT,
          source_authority: "synthetic-preview",
        },
        {
          recommendation_ref: "sample-rec-database",
          resource_ref: null,
          resource_type: "data.postgresql",
          problem: "Excess reserved capacity",
          solution: "Review the reserved capacity envelope",
          impact: "High",
          monthly_savings: 49800,
          currency: "USD",
          current_sku: "sample-memory-optimized",
          target_sku: "sample-general-purpose",
          utilization_percent: 42,
          utilization_metric: "capacity",
          observed_at: SAMPLE_AT,
          source_authority: "synthetic-preview",
        },
      ],
      limitations: ["synthetic_preview_not_operational_evidence"],
    },
  };
}
