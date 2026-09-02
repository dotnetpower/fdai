import type { AutonomyPayload, DashboardKpi } from "../types";
import type { CostGovernanceProjection } from "../api-cost-governance";
import { getLocale } from "../i18n";

export type OverviewHealth = "healthy" | "attention" | "unknown";

export interface GateRow {
  readonly policy_escapes: number;
  readonly ready: boolean;
}

export interface GatesSummary {
  readonly rows: readonly GateRow[];
  readonly ready_count: number;
  readonly blocked_count: number;
}

export interface DistributionRow {
  readonly key: string;
  readonly count: number;
  readonly share: number;
}

export type DashboardEvidenceGap = "baseline" | "confidence" | "guards" | "leading" | "outcomes";

type DashboardEvidence = Pick<AutonomyPayload, "confidence" | "guards" | "leading" | "success">;

const CONTROL_OUTCOME_ORDER = ["auto", "approval", "held", "deny", "other"] as const;

export function auditSampleParams(
  kpi: DashboardKpi,
): Readonly<Record<string, number>> {
  const sample = kpi.audit_sample;
  return sample !== null && sample.from_seq !== null && sample.through_seq !== null
    ? { from_seq: sample.from_seq, through_seq: sample.through_seq }
    : {};
}

export function formatShare(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatUsd(value: number): string {
  return value.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function overviewCostEvidence(
  cost: CostGovernanceProjection | null,
): { readonly monthlySavings: number | null; readonly recommendationCount: number | "n/a" } {
  const analytics = cost?.analytics;
  if (cost === null || !cost.complete || analytics === null || analytics === undefined ||
      !analytics.complete) {
    return { monthlySavings: null, recommendationCount: "n/a" };
  }
  if (analytics.recommendations.some((item) => item.monthly_savings === null)) {
    return { monthlySavings: null, recommendationCount: analytics.recommendations.length };
  }
  return {
    monthlySavings: analytics.recommendations.reduce(
      (sum, item) => sum + (item.monthly_savings ?? 0),
      0,
    ),
    recommendationCount: analytics.recommendations.length,
  };
}

export function overviewT0Share(byTier: Readonly<Record<string, number>>): string {
  const total = Object.values(byTier).reduce((sum, count) => sum + count, 0);
  if (!Object.hasOwn(byTier, "t0") || total <= 0) return "unavailable";
  return `${Math.round((byTier["t0"]! / total) * 100)}%`;
}

export function distributionRows(values: Readonly<Record<string, number>>): readonly DistributionRow[] {
  const total = Object.values(values).reduce((sum, count) => sum + count, 0);
  if (total <= 0) return [];
  return Object.entries(values)
    .filter(([, count]) => count > 0)
    .sort(([, left], [, right]) => right - left)
    .map(([key, count]) => ({ key, count, share: count / total }));
}

export function dashboardEvidenceGaps(
  autonomy: DashboardEvidence | null,
): readonly DashboardEvidenceGap[] {
  if (autonomy === null) return ["baseline", "confidence", "guards", "leading", "outcomes"];
  const success = Object.values(autonomy.success);
  const leading = Object.values(autonomy.leading);
  const gaps: DashboardEvidenceGap[] = [];
  if (success.some((metric) => metric.baseline === null)) gaps.push("baseline");
  if (autonomy.confidence === null) gaps.push("confidence");
  if (autonomy.guards.length === 0) gaps.push("guards");
  if (leading.some((metric) => metric.value === null)) gaps.push("leading");
  if (success.some((metric) => metric.value === null)) gaps.push("outcomes");
  return gaps;
}

export function overviewHealth(
  kpi: DashboardKpi,
  policyEscapes: number | null,
  autonomy: Pick<AutonomyPayload, "guards" | "synthetic"> | null,
): OverviewHealth {
  const measuredGuards = autonomy !== null && !autonomy.synthetic;
  const knownFailure =
    kpi.shadow_share < 0.95 ||
    kpi.hil_pending > 0 ||
    (policyEscapes !== null && policyEscapes > 0) ||
    (measuredGuards && autonomy.guards.some((guard) => !guard.ok));
  if (knownFailure) return "attention";
  if (
    policyEscapes === null ||
    autonomy === null ||
    autonomy.synthetic ||
    autonomy.guards.length === 0
  ) return "unknown";
  return "healthy";
}

export function overviewAttentionCount(
  kpi: DashboardKpi,
  policyEscapes: number | null,
  autonomy: Pick<AutonomyPayload, "guards" | "synthetic"> | null,
): number {
  const failedGuards = autonomy !== null && !autonomy.synthetic
    ? autonomy.guards.filter((guard) => !guard.ok).length
    : 0;
  return kpi.hil_pending + (policyEscapes ?? 0) + failedGuards;
}

export type AttentionState = "attention" | "clear" | "unknown";

export interface ControlGapSummary {
  readonly count: number;
  readonly state: AttentionState;
  readonly measured: boolean;
}

/**
 * A counted gap is a true lower bound, so it is reported even while another source is
 * missing. A zero is only reportable once every source that could raise it was measured.
 */
export function controlGapSummary(
  kpi: DashboardKpi,
  policyEscapes: number | null,
  gates: GatesSummary | null,
  autonomy: Pick<AutonomyPayload, "guards" | "synthetic"> | null,
): ControlGapSummary {
  const measuredGuards = autonomy !== null && !autonomy.synthetic;
  const count =
    (measuredGuards ? autonomy.guards.filter((guard) => !guard.ok).length : 0) +
    (kpi.shadow_share < 0.95 ? 1 : 0) +
    (gates !== null && gates.blocked_count > 0 ? 1 : 0) +
    (policyEscapes !== null && policyEscapes > 0 ? 1 : 0);
  const sourcesMeasured = measuredGuards && gates !== null && policyEscapes !== null;
  if (count > 0) return { count, state: "attention", measured: true };
  if (sourcesMeasured) return { count, state: "clear", measured: true };
  return { count, state: "unknown", measured: false };
}

export function controlOutcomeGroup(outcome: string): (typeof CONTROL_OUTCOME_ORDER)[number] {
  const normalized = outcome.trim().toLowerCase().replaceAll("-", "_");
  if (
    normalized === "auto" ||
    normalized.includes("executed") ||
    normalized.includes("remediated") ||
    normalized.includes("resolved") ||
    normalized.includes("succeeded") ||
    normalized === "success" ||
    normalized.includes("verified")
  ) return "auto";
  if (normalized.includes("hil") || normalized.includes("approval")) return "approval";
  if (normalized.includes("abstain") || normalized.includes("held")) return "held";
  if (
    normalized.includes("deny") ||
    normalized.includes("denied") ||
    normalized.includes("reject")
  ) return "deny";
  return "other";
}
