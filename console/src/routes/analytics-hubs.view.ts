import type { ViewSnapshot } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import type { AutonomyPayload, MetricVsBaseline } from "../types";
import { formatOutcomeMetric, type OutcomeKey } from "./operating-outcomes";

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
      `${autonomy.sample_size} events over ${autonomy.window_days} days.`,
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
      { key: "sample_size", label: "Sample size", value: autonomy.sample_size, group: "evidence" },
      { key: "confidence", label: "Confidence", value: autonomy.confidence, group: "evidence" },
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
