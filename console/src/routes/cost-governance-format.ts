import type { CostGovernanceRecommendation } from "../api-cost-governance";
import { getLocale } from "../i18n";
import type {
  CostGovernanceRow,
  CostGovernanceSummary,
} from "./cost-governance.view-model";
import { t } from "./i18n/cost-governance";

export interface SampleCostOutcomeSavings {
  readonly verifiedSavings: number;
  readonly projectedSavings: number;
  readonly realization: number;
  readonly currency: string;
}

export function costLocale(): string {
  return getLocale() === "ko" ? "ko-KR" : "en-US";
}

export function formatCurrency(
  amount: number | null,
  currency: string,
  fallback = "-",
): string {
  if (amount === null || !currency) return fallback;
  return new Intl.NumberFormat(costLocale(), {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

export function formatKnownTotal(summary: CostGovernanceSummary): string {
  if (summary.knownTotal !== null) {
    return formatCurrency(summary.knownTotal, summary.currency);
  }
  return summary.currency
    ? t("costGovernance.metrics.undisclosedAmount")
    : t("costGovernance.metrics.separateCurrencies");
}

export function formatNullablePercent(value: number | null): string {
  return value === null
    ? "-"
    : new Intl.NumberFormat(costLocale(), {
      style: "percent",
      maximumFractionDigits: 1,
    }).format(value);
}

export function formatSignedPercent(value: number | null): string {
  return value === null
    ? "-"
    : new Intl.NumberFormat(costLocale(), {
      style: "percent",
      signDisplay: "always",
      maximumFractionDigits: 1,
    }).format(value);
}

export function formatCompact(value: number): string {
  return new Intl.NumberFormat(costLocale(), {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function totalHint(summary: CostGovernanceSummary): string {
  if (summary.knownTotal !== null) return t("costGovernance.metrics.disclosedTotal");
  return summary.currency
    ? t("costGovernance.metrics.undisclosedTotal")
    : t("costGovernance.metrics.multipleCurrencies");
}

export function recommendationSavings(
  recommendations: readonly CostGovernanceRecommendation[],
): { readonly total: number | null; readonly currency: string } {
  const withSavings = recommendations.filter(
    (item): item is CostGovernanceRecommendation & {
      readonly monthly_savings: number;
      readonly currency: string;
    } => item.monthly_savings !== null && item.currency !== null,
  );
  const currencies = new Set(withSavings.map((item) => item.currency));
  if (
    withSavings.length !== recommendations.length
    || currencies.size !== 1
  ) return { total: null, currency: "" };
  return {
    total: withSavings.reduce((total, item) => total + item.monthly_savings, 0),
    currency: withSavings[0]?.currency ?? "",
  };
}

export function sampleOutcomeSavings(
  sourceAuthority: string,
  outcomes: readonly CostGovernanceRow[],
  recommendations: readonly CostGovernanceRecommendation[],
): SampleCostOutcomeSavings | null {
  if (
    sourceAuthority !== "synthetic-preview"
    || outcomes.length === 0
    || outcomes.some((row) => (
      row.kind !== "outcome"
      || row.status !== "effect_verified"
      || row.amount === null
      || !row.currency
    ))
  ) return null;
  const currencies = new Set(outcomes.map((row) => row.currency));
  const projected = recommendationSavings(recommendations);
  const verifiedSavings = outcomes.reduce(
    (total, row) => total + (row.amount ?? 0),
    0,
  );
  if (
    currencies.size !== 1
    || projected.total === null
    || projected.total <= 0
    || projected.currency !== outcomes[0]!.currency
    || verifiedSavings > projected.total
  ) return null;
  return {
    verifiedSavings,
    projectedSavings: projected.total,
    realization: verifiedSavings / projected.total,
    currency: projected.currency,
  };
}
