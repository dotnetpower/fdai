import { displayValue, type RenderedWidget } from "./processes.model";
import {
  asRows,
  boundedRatio,
  finiteNumber,
  numericPoints,
  percent,
} from "./process-view-widget-utils";
import { formatDateTimeValue, formatNumber, t } from "./i18n/workflow";
import {
  ComparisonBarChart,
  DensityHeatmap,
  DonutChart,
  ProgressBar,
  ProgressCircle,
  ScatterChart,
  SparkLineChart,
} from "../components/charts";
import { tremorChartColor } from "../components/chart-colors";

export const GRAPH_WIDGET_TYPES = new Set([
  "change",
  "distribution",
  "heatmap",
  "pie_chart",
  "scatter_plot",
  "sparkline",
  "gauge",
  "progress_bar",
]);

export function GraphWidget({ widget }: { readonly widget: RenderedWidget }) {
  if (widget.type === "change") return <ChangeWidget widget={widget} />;
  if (widget.type === "distribution") return <DistributionWidget widget={widget} />;
  if (widget.type === "heatmap") return <HeatmapWidget widget={widget} />;
  if (widget.type === "pie_chart") return <PieWidget widget={widget} />;
  if (widget.type === "scatter_plot") return <ScatterWidget widget={widget} />;
  if (widget.type === "sparkline") return <SparklineWidget widget={widget} />;
  if (widget.type === "gauge") return <GaugeWidget widget={widget} />;
  return <ProgressWidget widget={widget} />;
}

function ChangeWidget({ widget }: { readonly widget: RenderedWidget }) {
  const ratio = finiteNumber(widget.data["delta_ratio"]);
  const delta = finiteNumber(widget.data["delta_absolute"]);
  const direction = delta === null || delta === 0 ? "neutral" : delta > 0 ? "increase" : "decrease";
  return (
    <section class="process-widget-section report-change" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      <div class={`report-change-summary is-${direction}`}>
        <strong>{displayValue(widget.data["current"])}</strong>
        <span>{displayValue(delta)} ({ratio === null ? "-" : `${(ratio * 100).toFixed(1)}%`})</span>
      </div>
      <dl class="process-fallback"><dt>{t("workflow.process.previous")}</dt><dd>{displayValue(widget.data["previous"])}</dd></dl>
    </section>
  );
}

function DistributionWidget({ widget }: { readonly widget: RenderedWidget }) {
  const buckets = asRows(widget.data["buckets"]);
  const maximum = Math.max(1, ...buckets.map((bucket) => finiteNumber(bucket["count"]) ?? 0));
  const items = buckets.map((bucket) => ({
    label: t("workflow.process.bucketLimit", { value: displayValue(bucket["le"]) }),
    value: finiteNumber(bucket["count"]) ?? 0,
  }));
  return (
    <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      <ComparisonBarChart label={widget.title} items={items} maximum={maximum} formatValue={formatNumber} />
      {buckets.length === 0 ? <p class="muted small">{t("workflow.process.noDistributionBuckets")}</p> : null}
    </section>
  );
}

function HeatmapWidget({ widget }: { readonly widget: RenderedWidget }) {
  const series = asRows(widget.data["series"]);
  const rows = series.map((item) => ({
    label: displayValue(item["label"]),
    cells: numericPoints(item["points"]).map(([timestamp, value]) => ({ label: formatDateTimeValue(timestamp), value })),
  }));
  return (
    <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      <DensityHeatmap label={t("workflow.process.valuesCaption", { title: widget.title })} rows={rows} formatValue={formatNumber} />
      {series.length === 0 ? <p class="muted small">{t("workflow.process.noHeatmapSeries")}</p> : null}
    </section>
  );
}

function PieWidget({ widget }: { readonly widget: RenderedWidget }) {
  const slices = asRows(widget.data["slices"]);
  const segments = slices.map((slice) => ({
    label: displayValue(slice["label"]),
    value: boundedRatio(slice["percent"]) ?? 0,
    detail: displayValue(slice["value"]),
  }));
  return (
    <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      <DonutChart label={t("workflow.process.distributionAria", { title: widget.title })} segments={segments} formatValue={(value) => percent(value)} />
      {slices.length === 0 ? <p class="muted small">{t("workflow.process.noSlices")}</p> : null}
    </section>
  );
}

function ScatterWidget({ widget }: { readonly widget: RenderedWidget }) {
  const points = asRows(widget.data["points"]).flatMap((row, index) => {
    const x = finiteNumber(row["x"]);
    const y = finiteNumber(row["y"]);
    if (x === null || y === null) return [];
    return [{
      label: displayValue(row["label"] ?? `${index + 1}`),
      x,
      y,
      ...(row["group"] === undefined ? {} : { group: displayValue(row["group"]) }),
    }];
  });
  return (
    <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      {points.length > 0 ? <ScatterChart label={t("workflow.process.scatterAria", { title: widget.title, count: formatNumber(points.length) })} points={points} formatX={formatNumber} formatY={formatNumber} /> : <p class="muted small">{t("workflow.process.noScatterPoints")}</p>}
      <details><summary>{t("workflow.process.dataPoints")}</summary><ul class="report-compact-list">{points.map((point, index) => <li key={index}>{t(point.group === undefined ? "workflow.process.scatterPoint" : "workflow.process.scatterPointGroup", { x: formatNumber(point.x), y: formatNumber(point.y), group: point.group ?? "" })}</li>)}</ul></details>
    </section>
  );
}

function SparklineWidget({ widget }: { readonly widget: RenderedWidget }) {
  const series = asRows(widget.data["series"]);
  return (
    <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      <div class="report-small-multiples">{series.map((item, index) => {
        const values = Array.isArray(item["values"])
          ? item["values"].flatMap((value) => finiteNumber(value) ?? [])
          : [];
        const label = displayValue(item["label"]);
        return <article key={`${label}-${index}`}><strong>{label}</strong><SparkLineChart label={t("workflow.process.trendAria", { label })} points={values.map((value, pointIndex) => ({ label: `${pointIndex + 1}`, value }))} formatValue={formatNumber} color={tremorChartColor(index)} /><span class="muted small">{t("workflow.process.sparklineStats", { min: displayValue(item["min"]), max: displayValue(item["max"]), last: displayValue(item["last"]) })}</span></article>;
      })}</div>
      {series.length === 0 ? <p class="muted small">{t("workflow.process.noSparklineSeries")}</p> : null}
    </section>
  );
}

function GaugeWidget({ widget }: { readonly widget: RenderedWidget }) {
  const ratio = boundedRatio(widget.data["ratio"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-gauge"><ProgressCircle label={widget.title} value={ratio ?? 0} formatValue={() => `${displayValue(widget.data["value"])} ${displayValue(widget.data["unit"])}`} /><small>{t("workflow.process.gaugeRange", { min: displayValue(widget.data["min"]), max: displayValue(widget.data["max"]) })}</small></div></section>;
}

function ProgressWidget({ widget }: { readonly widget: RenderedWidget }) {
  const ratio = boundedRatio(widget.data["ratio"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-progress-head"><strong>{displayValue(widget.data["current"])} / {displayValue(widget.data["target"])} {displayValue(widget.data["unit"])}</strong></div><ProgressBar label={widget.title} value={ratio ?? 0} formatValue={(value) => percent(value)} />{ratio === null ? <p class="muted small">{t("workflow.process.ratioUnavailable")}</p> : null}</section>;
}
