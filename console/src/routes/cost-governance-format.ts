import type {
  CostDisclosurePolicy,
} from "../api-cost-governance";
import { getLocale } from "../i18n";
import type {
  CostGovernanceRow,
  CostGovernanceSummary,
} from "./cost-governance.view-model";
import { t } from "./i18n/cost-governance";

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

export function formatCostAmount(
  row: CostGovernanceRow,
  disclosure: CostDisclosurePolicy | null | undefined,
): string {
  if (row.positiveBelowRoundingIncrement) {
    const increment = disclosure?.rounding_increment ?? null;
    return increment !== null && row.currency
      ? t("costGovernance.metrics.belowRounding", {
        amount: formatCurrency(increment, row.currency),
      })
      : t("costGovernance.metrics.belowRoundingUnknown");
  }
  if (row.amountLabel === "suppressed") {
    return t("costGovernance.metrics.suppressed");
  }
  return formatCurrency(row.amount, row.currency, row.amountLabel);
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

export function totalHint(summary: CostGovernanceSummary): string {
  if (summary.knownTotal !== null) return t("costGovernance.metrics.disclosedTotal");
  return summary.currency
    ? t("costGovernance.metrics.undisclosedTotal")
    : t("costGovernance.metrics.multipleCurrencies");
}
