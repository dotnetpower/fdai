import type {
  CostDecisionCase,
  CostGovernanceProjection,
  CostReadinessSurface,
  CostResourceCandidate,
  CostSettlementOutcome,
  CostSurfaceReadiness,
} from "../api-cost-governance";

export interface CostGovernanceRow {
  readonly id: string;
  readonly kind: string;
  readonly label: string;
  readonly service: string;
  readonly amount: number | null;
  readonly amountLabel: string;
  readonly currency: string;
  readonly recordCount: number;
  readonly status: string;
  readonly observedAt: string | null;
  readonly completeness: number | null;
  readonly relativeChange: number | null;
  readonly sourceAuthority: string | null;
  readonly provenanceDigest: string | null;
  readonly positiveBelowRoundingIncrement: boolean;
}

export interface CostGovernanceSummary {
  readonly rows: readonly CostGovernanceRow[];
  readonly knownTotal: number | null;
  readonly currency: string;
  readonly totalsByCurrency: Readonly<Record<string, number>>;
  readonly sourceRecordCount: number;
  readonly largestShare: number | null;
  readonly largestLabel: string | null;
}

export interface CostResourceEfficiencyView {
  readonly mode: "service_summary" | "resource_candidate";
  readonly serviceRows: readonly CostGovernanceRow[];
  readonly candidates: readonly CostResourceCandidate[];
}

export interface CostSettlementSummary {
  readonly verifiedSavings: number | null;
  readonly currency: string;
  readonly verifiedCount: number;
  readonly failedCount: number;
  readonly censoredCount: number;
  readonly unscorableCount: number;
  readonly rollbackCount: number;
  readonly pendingCount: number;
}

export type CompleteCostSettlementOutcome = CostSettlementOutcome & {
  readonly action_ref: string;
  readonly action_revision: number;
};

export function summarizeCostGovernance(
  projection: CostGovernanceProjection,
): CostGovernanceSummary {
  const rows = projection.items.map((item, index) => decodeRow(item, index));
  const knownRows = rows.filter(
    (row): row is CostGovernanceRow & { readonly amount: number } => row.amount !== null,
  );
  const currencies = [...new Set(rows.map((row) => row.currency).filter(Boolean))];
  const totalsByCurrency = Object.fromEntries(
    currencies.flatMap((currency) => {
      const currencyRows = rows.filter((row) => row.currency === currency);
      if (currencyRows.some((row) => row.amount === null)) return [];
      return [[
        currency,
        currencyRows.reduce((total, row) => total + (row.amount ?? 0), 0),
      ]];
    }),
  );
  const currency = currencies.length === 1 ? currencies[0]! : "";
  const knownTotal = currency ? totalsByCurrency[currency] ?? null : null;
  const sortedRows = [...rows].sort((left, right) => {
    const currencyOrder = left.currency.localeCompare(right.currency);
    return currencyOrder !== 0 ? currencyOrder : (right.amount ?? -1) - (left.amount ?? -1);
  });
  let largestShare: number | null = null;
  let largestLabel: string | null = null;
  for (const row of knownRows) {
    const share = costShare(row, totalsByCurrency);
    if (share === null) continue;
    if (largestShare === null || share > largestShare) {
      largestShare = share;
      largestLabel = row.label;
    }
  }
  return {
    rows: sortedRows,
    knownTotal,
    currency,
    totalsByCurrency,
    sourceRecordCount: rows.reduce((total, row) => total + row.recordCount, 0),
    largestShare,
    largestLabel,
  };
}

export function resourceEfficiencyView(
  projection: CostGovernanceProjection,
): CostResourceEfficiencyView {
  const summary = summarizeCostGovernance(projection);
  const itemCandidates = projection.items
    .filter((item) => item["kind"] === "resource_candidate")
    .map((item) => item as unknown as CostResourceCandidate);
  const legacyCandidates = projection.resource_efficiency_mode === undefined
    || projection.resource_efficiency_mode === null
    ? (projection.analytics?.recommendations ?? []).flatMap((item) => (
      item.resource_ref
      && item.current_sku
      && item.target_sku
      && item.utilization_percent !== null
      && item.utilization_metric
        ? [{
          kind: "resource_candidate" as const,
          recommendation_ref: item.recommendation_ref,
          resource: item.resource_ref,
          resource_type: item.resource_type,
          current_configuration: item.current_sku,
          proposed_configuration: item.target_sku,
          utilization_metric: item.utilization_metric,
          utilization_percent: item.utilization_percent,
          projected_monthly_savings: item.monthly_savings,
          currency: item.currency,
          observed_at: item.observed_at,
          source_authority: item.source_authority,
        }]
        : []
    ))
    : [];
  const candidates = itemCandidates.length > 0 ? itemCandidates : legacyCandidates;
  const mode = projection.resource_efficiency_mode
    ?? (candidates.length > 0 ? "resource_candidate" : "service_summary");
  return {
    mode,
    serviceRows: summary.rows.filter((row) =>
      ["summary", "service-cost"].includes(row.kind)
    ),
    candidates,
  };
}

export function canPlotResourceCandidates(
  candidates: readonly CostResourceCandidate[],
): boolean {
  return candidates.length > 0
    && candidates.every((item) =>
      item.currency !== null && item.projected_monthly_savings !== null
    )
    && new Set(candidates.map((item) => item.currency)).size === 1;
}

export function costDecisionCases(
  projection: CostGovernanceProjection,
): readonly CostDecisionCase[] {
  return projection.items
    .filter((item) => item["kind"] === "decision_case")
    .map((item) => item as unknown as CostDecisionCase);
}

export function costSettlementOutcomes(
  projection: CostGovernanceProjection,
): readonly CompleteCostSettlementOutcome[] {
  return projection.items
    .filter((item) => item["kind"] === "settlement_outcome")
    .map((item) => item as unknown as CostSettlementOutcome)
    .filter(hasCompleteActionLineage);
}

export function incompleteSettlementLineageCount(
  projection: CostGovernanceProjection,
): number {
  return projection.items.filter((item) =>
    item["kind"] === "settlement_outcome"
    && !hasCompleteActionLineage(item as unknown as CostSettlementOutcome)
  ).length;
}

export function costReadiness(
  projection: CostGovernanceProjection,
  surface: CostReadinessSurface,
): CostSurfaceReadiness | null {
  return projection.evidence?.readiness.find((item) => item.surface === surface) ?? null;
}

export function summarizeSettlements(
  outcomes: readonly CompleteCostSettlementOutcome[],
): CostSettlementSummary {
  const verified = outcomes.filter((outcome) => settlementState(outcome) === "verified");
  const currencies = new Set(
    verified.map((outcome) => outcome.currency).filter((value): value is string => Boolean(value)),
  );
  const canSum = verified.length > 0
    && verified.every((outcome) => outcome.verified_savings !== null && outcome.currency)
    && currencies.size === 1;
  const states = outcomes.map(settlementState);
  return {
    verifiedSavings: canSum
      ? verified.reduce((total, outcome) => total + (outcome.verified_savings ?? 0), 0)
      : null,
    currency: canSum ? verified[0]?.currency ?? "" : "",
    verifiedCount: states.filter((state) => state === "verified").length,
    failedCount: states.filter((state) => state === "failed").length,
    censoredCount: states.filter((state) => state === "censored").length,
    unscorableCount: states.filter((state) => state === "unscorable").length,
    rollbackCount: states.filter((state) => state === "rollback").length,
    pendingCount: states.filter((state) => state === "pending").length,
  };
}

export function settlementState(
  outcome: CompleteCostSettlementOutcome,
): "verified" | "failed" | "censored" | "unscorable" | "rollback" | "pending" {
  if (outcome.rollback_requested) return "rollback";
  if (!outcome.terminal || outcome.effects.some((effect) => !effect.terminal)) return "pending";
  if (outcome.effects.some((effect) => effect.status === "failed")) return "failed";
  if (outcome.effects.some((effect) => effect.status === "censored")) return "censored";
  if (outcome.effects.some((effect) => effect.status === "unscorable")) return "unscorable";
  return outcome.verified_savings !== null
    && outcome.effects.every((effect) => effect.status === "verified")
    ? "verified"
    : "pending";
}

function hasCompleteActionLineage(
  outcome: CostSettlementOutcome,
): outcome is CompleteCostSettlementOutcome {
  return typeof outcome.action_ref === "string"
    && outcome.action_ref.trim().length > 0
    && typeof outcome.action_revision === "number"
    && Number.isInteger(outcome.action_revision)
    && outcome.action_revision > 0;
}

export function costShare(
  row: CostGovernanceRow,
  totalsByCurrency: Readonly<Record<string, number>>,
): number | null {
  if (row.amount === null) return null;
  const total = totalsByCurrency[row.currency];
  return total !== undefined && total > 0 ? row.amount / total : null;
}

function decodeRow(
  item: Readonly<Record<string, unknown>>,
  index: number,
): CostGovernanceRow {
  const positiveBelowRoundingIncrement =
    item["positive_below_rounding_increment"] === true;
  const amountValue = item["amount_exact"] ?? item["amount_rounded"];
  const amount = positiveBelowRoundingIncrement ? null : numericAmount(amountValue);
  const amountLabel = positiveBelowRoundingIncrement
    ? "positive_below_rounding_increment"
    : amountValue === undefined
    ? stringValue(item["amount_band"]) ?? (item["suppressed"] ? "suppressed" : "-")
    : String(amountValue);
  const label = stringValue(item["resource"])
    ?? stringValue(item["group_id"])
    ?? stringValue(item["service_id"])
    ?? `record-${index + 1}`;
  return {
    id: stringValue(item["record_id"]) ?? `${label}-${index}`,
    kind: stringValue(item["kind"]) ?? "unknown",
    label,
    service: stringValue(item["service_id"]) ?? label,
    amount,
    amountLabel,
    currency: stringValue(item["currency"]) ?? "",
    recordCount: nonNegativeInteger(item["record_count"]) ?? 1,
    status: stringValue(item["status"]) ?? "observed",
    observedAt: stringValue(item["observed_at"]),
    completeness: numericAmount(item["completeness"]),
    relativeChange: numericAmount(item["relative_change"]),
    sourceAuthority: stringValue(item["source_authority"]),
    provenanceDigest: stringValue(item["provenance_digest"]),
    positiveBelowRoundingIncrement,
  };
}

function numericAmount(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const parsed = Number(value.replaceAll(",", ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}
