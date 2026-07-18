import { displayValue, type RenderedWidget } from "./processes.model";
import {
  asRows,
  boundedRatio,
  finiteNumber,
  normalizedPointPositions,
  numericPoints,
  percent,
  sparkline,
} from "./process-view-widget-utils";

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
      <dl class="process-fallback"><dt>Previous</dt><dd>{displayValue(widget.data["previous"])}</dd></dl>
    </section>
  );
}

function DistributionWidget({ widget }: { readonly widget: RenderedWidget }) {
  const buckets = asRows(widget.data["buckets"]);
  const maximum = Math.max(1, ...buckets.map((bucket) => finiteNumber(bucket["count"]) ?? 0));
  return (
    <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      <div class="report-bars">
        {buckets.map((bucket, index) => {
          const count = finiteNumber(bucket["count"]) ?? 0;
          return <div class="report-bar-row" key={`${displayValue(bucket["le"])}-${index}`}>
            <span>&le; {displayValue(bucket["le"])}</span>
            <span class="report-bar-track" aria-hidden="true"><span style={{ width: `${Math.max(0, count / maximum) * 100}%` }} /></span>
            <strong>{displayValue(bucket["count"])}</strong>
          </div>;
        })}
      </div>
      {buckets.length === 0 ? <p class="muted small">No distribution buckets.</p> : null}
    </section>
  );
}

function HeatmapWidget({ widget }: { readonly widget: RenderedWidget }) {
  const series = asRows(widget.data["series"]);
  const values = series.flatMap((item) => numericPoints(item["points"]).map(([, value]) => value));
  const maximum = Math.max(1, ...values.map((value) => Math.abs(value)));
  return (
    <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      <div class="scroll"><table class="report-matrix"><caption class="sr-only">{widget.title} values</caption><tbody>
        {series.map((item, rowIndex) => <tr key={`${displayValue(item["label"])}-${rowIndex}`}>
          <th scope="row">{displayValue(item["label"])}</th>
          {numericPoints(item["points"]).map(([timestamp, value], columnIndex) => (
            <td key={`${timestamp}-${columnIndex}`} style={{ "--cell-intensity": Math.min(1, Math.abs(value) / maximum) }} aria-label={`${timestamp}: ${value}`}>{value}</td>
          ))}
        </tr>)}
      </tbody></table></div>
      {series.length === 0 ? <p class="muted small">No heatmap series.</p> : null}
    </section>
  );
}

function PieWidget({ widget }: { readonly widget: RenderedWidget }) {
  const slices = asRows(widget.data["slices"]);
  return (
    <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      <div class="report-segments" role="img" aria-label={`${widget.title} distribution`}>
        {slices.map((slice, index) => <span key={`${displayValue(slice["label"])}-${index}`} style={{ flexGrow: boundedRatio(slice["percent"]) ?? 0 }} />)}
      </div>
      <dl class="report-legend">
        {slices.map((slice, index) => <div key={`${displayValue(slice["label"])}-${index}`}><dt>{displayValue(slice["label"])}</dt><dd>{displayValue(slice["value"])} ({percent(slice["percent"])})</dd></div>)}
      </dl>
      {slices.length === 0 ? <p class="muted small">No slices.</p> : null}
    </section>
  );
}

function ScatterWidget({ widget }: { readonly widget: RenderedWidget }) {
  const points = normalizedPointPositions(asRows(widget.data["points"]));
  return (
    <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      {points.length > 0 ? <svg class="report-xyplot" viewBox="0 0 320 96" role="img" aria-label={`${widget.title}, ${points.length} points`}>
        <path d="M8 8 V88 H312" fill="none" stroke="currentColor" opacity=".35" />
        {points.map((point, index) => <circle key={index} cx={point.x} cy={point.y} r="4"><title>{`x ${displayValue(point.row["x"])}, y ${displayValue(point.row["y"])}, group ${displayValue(point.row["group"])}`}</title></circle>)}
      </svg> : <p class="muted small">No scatter points.</p>}
      <details><summary>Data points</summary><ul class="report-compact-list">{points.map((point, index) => <li key={index}>x {displayValue(point.row["x"])}, y {displayValue(point.row["y"])}{point.row["group"] === undefined ? "" : `, ${displayValue(point.row["group"])}`}</li>)}</ul></details>
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
        const points = values.map((value, pointIndex) => [pointIndex, value] as const);
        return <article key={`${displayValue(item["label"])}-${index}`}><strong>{displayValue(item["label"])}</strong><svg viewBox="0 0 160 48" role="img" aria-label={`${displayValue(item["label"])} trend`}><polyline points={sparkline(points, 160, 48)} fill="none" stroke="currentColor" stroke-width="2" /></svg><span class="muted small">min {displayValue(item["min"])} / max {displayValue(item["max"])} / last {displayValue(item["last"])}</span></article>;
      })}</div>
      {series.length === 0 ? <p class="muted small">No sparkline series.</p> : null}
    </section>
  );
}

function GaugeWidget({ widget }: { readonly widget: RenderedWidget }) {
  const ratio = boundedRatio(widget.data["ratio"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-gauge" role="meter" aria-valuemin={finiteNumber(widget.data["min"]) ?? 0} aria-valuemax={finiteNumber(widget.data["max"]) ?? 100} aria-valuenow={finiteNumber(widget.data["value"]) ?? undefined}><span style={{ "--gauge-ratio": ratio ?? 0 }} /><strong>{displayValue(widget.data["value"])} {displayValue(widget.data["unit"])}</strong><small>{displayValue(widget.data["min"])} to {displayValue(widget.data["max"])}</small></div></section>;
}

function ProgressWidget({ widget }: { readonly widget: RenderedWidget }) {
  const ratio = boundedRatio(widget.data["ratio"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-progress-head"><strong>{displayValue(widget.data["current"])} / {displayValue(widget.data["target"])} {displayValue(widget.data["unit"])}</strong><span>{percent(ratio)}</span></div><progress max={1} value={ratio ?? 0}>{percent(ratio)}</progress>{ratio === null ? <p class="muted small">A ratio is unavailable because the target is zero or missing.</p> : null}</section>;
}
