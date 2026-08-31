import {
  panelArray,
  panelBoolean,
  panelNonNegativeInteger,
  panelNonNegativeNumber,
  panelRecord,
  panelString,
} from "./routes/panel-decode";

export type CostGovernanceSurface =
  | "overview"
  | "resource-efficiency"
  | "optimization-cases"
  | "outcomes";

export interface CostGovernanceTrendPoint {
  readonly observed_on: string;
  readonly amount: number;
  readonly currency: string;
  readonly completeness: number;
}

export interface CostGovernanceBudget {
  readonly budget_ref: string;
  readonly amount: number;
  readonly current_spend: number;
  readonly forecast_spend: number | null;
  readonly currency: string;
  readonly time_grain: string;
}

export interface CostGovernanceRecommendation {
  readonly recommendation_ref: string;
  readonly resource_ref: string | null;
  readonly resource_type: string;
  readonly problem: string;
  readonly solution: string;
  readonly impact: "High" | "Medium" | "Low" | "Unknown";
  readonly monthly_savings: number | null;
  readonly currency: string | null;
  readonly current_sku: string | null;
  readonly target_sku: string | null;
  readonly utilization_percent: number | null;
  readonly utilization_metric: string | null;
  readonly observed_at: string;
  readonly source_authority: string;
}

export interface CostGovernanceAnalytics {
  readonly source_authority: string;
  readonly observed_at: string;
  readonly complete: boolean;
  readonly trend: readonly CostGovernanceTrendPoint[];
  readonly budgets: readonly CostGovernanceBudget[];
  readonly recommendations: readonly CostGovernanceRecommendation[];
  readonly limitations: readonly string[];
}

export interface CostGovernanceProjection {
  readonly surface: CostGovernanceSurface;
  readonly complete: boolean;
  readonly source_authority: string;
  readonly items: readonly Readonly<Record<string, unknown>>[];
  readonly suppressed_count: number;
  readonly analytics?: CostGovernanceAnalytics | null;
}

export function decodeCostGovernanceProjection(value: unknown): CostGovernanceProjection {
  const record = panelRecord(value, "cost governance projection");
  const surface = panelString(record, "surface", "cost governance projection");
  if (!["overview", "resource-efficiency", "optimization-cases", "outcomes"].includes(surface)) {
    throw new Error("Unknown Cost Governance surface");
  }
  return {
    surface: surface as CostGovernanceSurface,
    complete: panelBoolean(record, "complete", "cost governance projection"),
    source_authority: panelString(record, "source_authority", "cost governance projection"),
    items: panelArray(record["items"], "items").map((item) => panelRecord(item, "item")),
    suppressed_count: panelNonNegativeInteger(
      record,
      "suppressed_count",
      "cost governance projection",
    ),
    analytics: record["analytics"] === undefined || record["analytics"] === null
      ? null
      : decodeAnalytics(record["analytics"]),
  };
}

function decodeAnalytics(value: unknown): CostGovernanceAnalytics {
  const record = panelRecord(value, "cost governance analytics");
  return {
    source_authority: panelString(record, "source_authority", "cost governance analytics"),
    observed_at: panelString(record, "observed_at", "cost governance analytics"),
    complete: panelBoolean(record, "complete", "cost governance analytics"),
    trend: panelArray(record["trend"], "trend").map((item, index) => {
      const point = panelRecord(item, `trend[${index}]`);
      return {
        observed_on: panelString(point, "observed_on", `trend[${index}]`),
        amount: decimal(point, "amount", `trend[${index}]`),
        currency: panelString(point, "currency", `trend[${index}]`),
        completeness: decimal(point, "completeness", `trend[${index}]`),
      };
    }),
    budgets: panelArray(record["budgets"], "budgets").map((item, index) => {
      const budget = panelRecord(item, `budgets[${index}]`);
      return {
        budget_ref: panelString(budget, "budget_ref", `budgets[${index}]`),
        amount: decimal(budget, "amount", `budgets[${index}]`),
        current_spend: decimal(budget, "current_spend", `budgets[${index}]`),
        forecast_spend: nullableDecimal(budget, "forecast_spend", `budgets[${index}]`),
        currency: panelString(budget, "currency", `budgets[${index}]`),
        time_grain: panelString(budget, "time_grain", `budgets[${index}]`),
      };
    }),
    recommendations: panelArray(record["recommendations"], "recommendations").map(
      (item, index) => decodeRecommendation(item, index),
    ),
    limitations: panelArray(record["limitations"], "limitations").map((item) => {
      if (typeof item !== "string") throw new Error("Invalid Cost Governance limitation");
      return item;
    }),
  };
}

function decodeRecommendation(value: unknown, index: number): CostGovernanceRecommendation {
  const label = `recommendations[${index}]`;
  const record = panelRecord(value, label);
  const impact = panelString(record, "impact", label);
  if (!["High", "Medium", "Low", "Unknown"].includes(impact)) {
    throw new Error("Invalid Cost Governance recommendation impact");
  }
  return {
    recommendation_ref: panelString(record, "recommendation_ref", label),
    resource_ref: nullableString(record, "resource_ref", label),
    resource_type: panelString(record, "resource_type", label),
    problem: panelString(record, "problem", label),
    solution: panelString(record, "solution", label),
    impact: impact as CostGovernanceRecommendation["impact"],
    monthly_savings: nullableDecimal(record, "monthly_savings", label),
    currency: nullableString(record, "currency", label),
    current_sku: nullableString(record, "current_sku", label),
    target_sku: nullableString(record, "target_sku", label),
    utilization_percent: nullableDecimal(record, "utilization_percent", label),
    utilization_metric: nullableString(record, "utilization_metric", label),
    observed_at: panelString(record, "observed_at", label),
    source_authority: panelString(record, "source_authority", label),
  };
}

function decimal(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number {
  const value = record[key];
  if (typeof value === "number") return panelNonNegativeNumber(record, key, label);
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed >= 0) return parsed;
  }
  throw new Error(`${label}.${key} MUST be a non-negative decimal`);
}

function nullableDecimal(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  return record[key] === null || record[key] === undefined
    ? null
    : decimal(record, key, label);
}

function nullableString(
  record: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  return record[key] === null || record[key] === undefined
    ? null
    : panelString(record, key, label);
}
