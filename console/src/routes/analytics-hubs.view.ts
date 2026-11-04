import type { ViewSnapshot } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import type { AutonomyPayload, MetricVsBaseline } from "../types";
import {
  formatOutcomeMetric,
  outcomeSampleSize,
  type OutcomeKey,
} from "./operating-outcomes";

interface OperatingOutcomeSnapshotInput {
  readonly autonomy: AutonomyPayload;
  readonly metric: MetricVsBaseline;
  readonly metricKey: OutcomeKey;
  readonly metricLabel: string;
  readonly unavailableLabel: string;
  readonly routeLabel: string;
}

export function buildOperatingOutcomeViewSnapshot({
  autonomy,
  metric,
  metricKey,
  metricLabel,
  unavailableLabel,
  routeLabel,
}: OperatingOutcomeSnapshotInput): ViewSnapshot {
  const current = metric.value === null
    ? unavailableLabel
    : formatOutcomeMetric(metric.value, metricKey);
  const baseline = metric.baseline === null
    ? unavailableLabel
    : formatOutcomeMetric(metric.baseline, metricKey);
  const showsVerticalBreakdown = metricKey === "auto-resolution";
  const currentFactValue = showsVerticalBreakdown && metric.value !== null
    ? Math.round(metric.value * 100) / 100
    : metric.value;
  const baselineFactValue = showsVerticalBreakdown && metric.baseline !== null
    ? Math.round(metric.baseline * 100) / 100
    : metric.baseline;
  const currentFactKey = showsVerticalBreakdown ? "current_rate" : "current_value";
  const baselineFactKey = showsVerticalBreakdown ? "baseline_rate" : "baseline_value";
  const metricSampleSize = outcomeSampleSize(autonomy, metricKey);
  return {
    routeId: "operating-outcomes",
    routeLabel,
    purpose: showsVerticalBreakdown
      ? "Inspect the measured auto-resolution outcome, its baseline and trend, and the " +
        "observed event contribution from each operational vertical."
      : "Inspect the selected operating outcome, its baseline, and the explicit availability " +
        "of trend and breakdown projections.",
    headline:
      `${metricLabel}: current ${current}, baseline ${baseline}; ` +
      `${metricSampleSize} metric samples from ${autonomy.sample_size} events over ` +
      `${autonomy.window_days} days.`,
    capturedAt: autonomy.source.as_of ?? new Date().toISOString(),
    glossary: composeGlossary([
      {
        term: "measured evidence",
        plain: "observations computed from the named source over the displayed window",
      },
      {
        term: "baseline",
        plain: "the reference measurement used to compare the current outcome",
      },
      {
        term: "confidence",
        plain: "the statistical confidence reported by the measurement source when available",
      },
    ]),
    facts: [
      { key: "selected_metric", label: metricLabel, value: metricKey, group: "metric" },
      {
        key: currentFactKey,
        label: "Current",
        aliases: [metricLabel, metricKey],
        value: currentFactValue,
        group: "metric",
      },
      {
        key: baselineFactKey,
        label: "Baseline",
        aliases: [`${metricLabel} baseline`],
        value: baselineFactValue,
        group: "metric",
      },
      { key: "direction", label: "Better when", value: metric.direction, group: "metric" },
      { key: "window_days", label: "Measurement window", value: autonomy.window_days, group: "evidence" },
      { key: "sample_size", label: "Metric sample size", value: metricSampleSize, group: "evidence" },
      { key: "event_sample_size", label: "Event sample size", value: autonomy.sample_size, group: "evidence" },
      {
        key: "measurement_gaps",
        label: "Measurement gaps",
        value: autonomy.measurement_gaps.join(", "),
        group: "evidence",
      },
      { key: "confidence", label: "Confidence", value: autonomy.confidence, group: "evidence" },
      {
        key: "evidence_qualification",
        label: "Evidence qualification",
        value: autonomy.provenance?.qualification ?? null,
        group: "evidence",
      },
      {
        key: "unknown_synthetic_marker_events",
        label: "Events with an unknown synthetic marker",
        value: autonomy.provenance?.synthetic_marker.unknown ?? null,
        group: "evidence",
      },
      { key: "source", label: "Evidence source", value: autonomy.source.name, group: "evidence" },
      { key: "source_kind", value: autonomy.source.kind, group: "evidence" },
      { key: "source_as_of", label: "Evidence as of", value: autonomy.source.as_of, group: "evidence" },
      { key: "finalized_events", label: "Finalized outcomes", value: autonomy.finalization.finalized_events, group: "evidence" },
      { key: "pending_finalization", label: "Pending finalization", value: autonomy.finalization.pending_events, group: "evidence" },
      { key: "adverse_outcomes", label: "Adverse outcomes", value: autonomy.finalization.adverse_events, group: "evidence" },
      { key: "synthetic", value: autonomy.synthetic, group: "evidence" },
    ],
    ...(showsVerticalBreakdown
      ? { records: { verticals: autonomy.verticals.map((vertical) => ({ ...vertical })) } }
      : {}),
    explanations: {
      provenance: {
        authority: autonomy.source.kind,
        refs: [autonomy.source.name],
      },
    },
  };
}

export interface DecisionQueueCardPayload {
  readonly rank: number;
  readonly case_id: string;
  readonly target_resource_ref: string;
  readonly recommended_action_type: string;
  readonly cost_badge: string;
  readonly blast_radius_tier: string;
  readonly change_risk_tier: string;
  readonly uncertainty: number;
  readonly quorum_label: string;
  readonly approval_status: string;
}

export interface DecisionQueueOperatorPayload {
  readonly read_only: true;
  readonly authority: "none";
  readonly state: "complete" | "unavailable";
  readonly scope_ref: string;
  readonly ranking_currency: string | null;
  readonly total_pending_count: number;
  readonly cards: readonly DecisionQueueCardPayload[];
}

export interface WorkflowValueClaimDrilldownInput {
  readonly workflow_ref: string;
  readonly objective_ref: string;
  readonly unit: "duration_seconds" | "cost_amount" | "count";
  readonly currency: string | null;
  readonly settled_claim_count: number;
  readonly total_conservative_improvement: string;
  readonly average_reduction_pct: number | null;
}

export function formatDecisionQueueHeadline(
  payload: DecisionQueueOperatorPayload,
  unavailableLabel = "Unavailable",
): string {
  if (payload.state !== "complete") {
    return `Decision Queue (${payload.scope_ref}): ${unavailableLabel}`;
  }
  const top = payload.cards[0];
  const topLabel = top
    ? `top candidate ${top.case_id} (${top.cost_badge}, ${top.recommended_action_type})`
    : "no queued items";
  return `Decision Queue (${payload.scope_ref}): ${payload.total_pending_count} pending; ${topLabel}.`;
}

export function formatWorkflowValueClaimDrilldown(
  drilldown: WorkflowValueClaimDrilldownInput,
  unavailableLabel = "Unavailable",
): string {
  if (drilldown.settled_claim_count <= 0) {
    return `${drilldown.workflow_ref}: ${unavailableLabel}`;
  }
  const unitLabel = drilldown.unit === "cost_amount" && drilldown.currency
    ? `${drilldown.total_conservative_improvement} ${drilldown.currency}`
    : `${drilldown.total_conservative_improvement} ${drilldown.unit}`;
  const pct = drilldown.average_reduction_pct !== null
    ? ` (-${drilldown.average_reduction_pct.toFixed(1)}% vs baseline)`
    : "";
  return `${drilldown.workflow_ref}: ${unitLabel} across ${drilldown.settled_claim_count} settled claim(s)${pct}`;
}
