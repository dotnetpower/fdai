import type { ComponentChildren } from "preact";
import { Tooltip } from "./tooltip";
import "./charts.css";

export {
  AreaChart,
  BarChart,
  ComboChart,
  LineChart,
  type ComboSeriesDefinition,
  type SeriesDatum,
  type SeriesDefinition,
} from "./charts-series";
export {
  DonutChart,
  ProgressBar,
  ProgressCircle,
  SparkAreaChart,
  SparkBarChart,
  SparkLineChart,
  Tracker,
  type DonutChartSegment,
  type SparkChartPoint,
  type TrackerBlock,
} from "./charts-compact";
export {
  MetricChartFrame,
  MetricDonutChart,
  MetricSeriesChart,
  type MetricSummaryItem,
} from "./charts-composed";

export interface TrendChartPoint {
  readonly label: string;
  readonly value: number;
  readonly detail?: string;
}

interface TrendChartProps {
  readonly title: string;
  readonly description?: string;
  readonly points: readonly TrendChartPoint[];
  readonly formatValue: (value: number) => string;
  readonly summary?: ComponentChildren;
  readonly summaryHint?: string;
  readonly referenceLabel: string;
  readonly className?: string;
  readonly compact?: boolean;
}

export interface ComparisonBarItem {
  readonly label: string;
  readonly value: number;
  readonly formattedValue?: string;
  readonly baseline?: number;
  readonly detail?: string;
}

export interface ComparisonBarChartProps {
  readonly label: string;
  readonly items: readonly ComparisonBarItem[];
  readonly formatValue: (value: number) => string;
  readonly maximum?: number;
}

export interface DistributionSegment {
  readonly label: string;
  readonly value: number;
  readonly detail?: string;
}

export interface DistributionBarProps {
  readonly label: string;
  readonly segments: readonly DistributionSegment[];
  readonly formatValue: (value: number) => string;
}

export interface DensityCell {
  readonly label: string;
  readonly value: number;
}

export interface DensityRow {
  readonly label: string;
  readonly cells: readonly DensityCell[];
}

interface DensityHeatmapProps {
  readonly label: string;
  readonly rows: readonly DensityRow[];
  readonly formatValue: (value: number) => string;
}

interface PositionedTrendPoint extends TrendChartPoint {
  readonly index: number;
  readonly x: number;
  readonly y: number;
}

export { ScatterChart, type ScatterChartPoint } from "./charts-scatter";

const TREND_WIDTH = 360;
const TREND_HEIGHT = 156;
const TREND_PAD_X = 18;
const TREND_PAD_TOP = 20;
const TREND_PAD_BOTTOM = 30;

/** Renders one bounded, keyboard-inspectable series without inferring missing evidence. */
export function TrendChart({
  title,
  description,
  points,
  formatValue,
  summary,
  summaryHint,
  referenceLabel,
  className,
  compact = false,
}: TrendChartProps) {
  const positioned = positionTrendPoints(points);
  if (positioned.length < 2) return null;
  const values = positioned.map((point) => point.value);
  const median = sortedMedian(values);
  const medianY = trendY(median, Math.min(...values), Math.max(...values));
  const line = positioned.map((point) => `${point.x},${point.y}`).join(" ");
  const area = `M${positioned[0]!.x} ${TREND_HEIGHT - TREND_PAD_BOTTOM} L${line.replaceAll(" ", " L")} L${positioned.at(-1)!.x} ${TREND_HEIGHT - TREND_PAD_BOTTOM} Z`;
  const peak = positioned.reduce((current, point) => point.value > current.value ? point : current);
  const current = positioned.at(-1)!;

  return (
    <figure class={`fd-chart fd-trend-chart${compact ? " is-compact" : ""}${className ? ` ${className}` : ""}`}>
      <figcaption class="fd-chart-head">
        <span>
          <strong>{title}</strong>
          {description ? <small>{description}</small> : null}
        </span>
        {summary ? <span class="fd-chart-summary"><strong>{summary}</strong>{summaryHint ? <small>{summaryHint}</small> : null}</span> : null}
      </figcaption>
      <div class="fd-chart-plot" role="group" aria-label={description ?? title}>
        <svg viewBox={`0 0 ${TREND_WIDTH} ${TREND_HEIGHT}`} aria-hidden="true" preserveAspectRatio="none">
          <path class="fd-chart-grid" d={`M${TREND_PAD_X} 24H${TREND_WIDTH - TREND_PAD_X} M${TREND_PAD_X} 74H${TREND_WIDTH - TREND_PAD_X} M${TREND_PAD_X} ${TREND_HEIGHT - TREND_PAD_BOTTOM}H${TREND_WIDTH - TREND_PAD_X}`} />
          <path class="fd-chart-area" d={area} />
          <path class="fd-chart-reference" d={`M${TREND_PAD_X} ${medianY}H${TREND_WIDTH - TREND_PAD_X}`} />
          <polyline class="fd-chart-line" points={line} />
        </svg>
        <span class="fd-chart-reference-label" style={{ top: `${(medianY / TREND_HEIGHT) * 100}%` }}>
          {referenceLabel} {formatValue(median)}
        </span>
        {positioned.map((point, positionedIndex) => {
          const value = formatValue(point.value);
          const label = `${point.label}: ${value}${point.detail ? `. ${point.detail}` : ""}`;
          const role = point.index === current.index ? "current" : point.index === peak.index ? "peak" : "point";
          const previousX = positionedIndex === 0 ? 0 : (positioned[positionedIndex - 1]!.x + point.x) / 2;
          const nextX = positionedIndex === positioned.length - 1 ? TREND_WIDTH : (point.x + positioned[positionedIndex + 1]!.x) / 2;
          return (
            <Tooltip
              key={`${point.label}-${point.index}`}
              content={label}
              placement="top"
              anchorClassName="fd-chart-slice-anchor"
              anchorStyle={{
                "--chart-slice-left": `${previousX / TREND_WIDTH * 100}%`,
                "--chart-slice-width": `${(nextX - previousX) / TREND_WIDTH * 100}%`,
              }}
            >
              <button
                type="button"
                class="fd-chart-point"
                data-role={role}
                aria-label={label}
                style={{
                  "--chart-category-x": `${(point.x - previousX) / Math.max(1, nextX - previousX) * 100}%`,
                  "--chart-point-y": `${(point.y - TREND_PAD_TOP) / (TREND_HEIGHT - TREND_PAD_TOP - TREND_PAD_BOTTOM) * 100}%`,
                }}
              />
            </Tooltip>
          );
        })}
        <span class="fd-chart-direct-label is-peak" style={{ left: `${(peak.x / TREND_WIDTH) * 100}%`, top: `${(peak.y / TREND_HEIGHT) * 100}%` }}>
          {formatValue(peak.value)}
        </span>
        <span class="fd-chart-direct-label is-current" style={{ left: `${(current.x / TREND_WIDTH) * 100}%`, top: `${(current.y / TREND_HEIGHT) * 100}%` }}>
          {formatValue(current.value)}
        </span>
        <div class="fd-chart-axis" aria-hidden="true">
          {positioned.map((point) => <span key={`${point.label}-${point.index}`}>{point.label}</span>)}
        </div>
      </div>
    </figure>
  );
}

/** Renders exact categorical values with an optional baseline marker. */
export function ComparisonBarChart({ label, items, formatValue, maximum }: ComparisonBarChartProps) {
  const finite = items.filter((item) => Number.isFinite(item.value));
  const domainMaximum = Math.max(
    1,
    maximum ?? 0,
    ...finite.flatMap((item) => item.baseline === undefined ? [item.value] : [item.value, item.baseline]),
  );
  return (
    <div class="fd-bar-chart" role="list" aria-label={label}>
      {finite.map((item, index) => {
        const current = item.formattedValue ?? formatValue(item.value);
        const baseline = item.baseline === undefined ? null : formatValue(item.baseline);
        const accessible = `${item.label}: ${current}${baseline === null ? "" : `, baseline ${baseline}`}${item.detail ? `. ${item.detail}` : ""}`;
        return (
          <div class="fd-bar-row" role="listitem" key={`${item.label}-${index}`}>
            <span class="fd-bar-label">{item.label}</span>
            <Tooltip content={accessible} placement="top">
              <button
                type="button"
                class="fd-bar-track"
                aria-label={accessible}
                style={{
                  "--bar-current": `${Math.max(0, item.value / domainMaximum) * 100}%`,
                  "--bar-baseline": `${Math.max(0, (item.baseline ?? 0) / domainMaximum) * 100}%`,
                }}
              >
                <span class="fd-bar-fill" />
                {item.baseline === undefined ? null : <span class="fd-bar-baseline" />}
              </button>
            </Tooltip>
            <strong>{current}</strong>
          </div>
        );
      })}
    </div>
  );
}

/** Renders a proportional distribution with every segment keyboard inspectable. */
export function DistributionBar({ label, segments, formatValue }: DistributionBarProps) {
  const finite = segments.filter((segment) => Number.isFinite(segment.value) && segment.value >= 0);
  const total = finite.reduce((sum, segment) => sum + segment.value, 0);
  return (
    <div class="fd-distribution" aria-label={label}>
      <div class="fd-distribution-track">
        {finite.map((segment, index) => {
          const share = total === 0 ? 0 : (segment.value / total) * 100;
          const accessible = `${segment.label}: ${formatValue(segment.value)}${segment.detail ? `. ${segment.detail}` : ""}`;
          return (
            <Tooltip key={`${segment.label}-${index}`} content={accessible} placement="top">
              <button
                type="button"
                class="fd-distribution-segment"
                data-index={index % 6}
                aria-label={accessible}
                style={{ "--segment-share": `${share}%` }}
              />
            </Tooltip>
          );
        })}
      </div>
      <dl class="fd-distribution-legend">
        {finite.map((segment, index) => (
          <div key={`${segment.label}-${index}`} data-index={index % 6}>
            <dt><i />{segment.label}</dt>
            <dd>{formatValue(segment.value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export const BarList = ComparisonBarChart;
export const CategoryBar = DistributionBar;

/** Renders a semantic exact-value table with density encoded as a secondary cue. */
export function DensityHeatmap({ label, rows, formatValue }: DensityHeatmapProps) {
  const values = rows.flatMap((row) => row.cells.map((cell) => cell.value)).filter(Number.isFinite);
  const minimum = values.length === 0 ? 0 : Math.min(...values);
  const maximum = values.length === 0 ? 1 : Math.max(...values);
  const range = Math.max(1, maximum - minimum);
  return (
    <div class="fd-heatmap-wrap">
      <table class="fd-heatmap">
        <caption class="sr-only">{label}</caption>
        <thead>
          <tr><th scope="col" />{rows[0]?.cells.map((cell, index) => <th scope="col" key={`${cell.label}-${index}`}>{cell.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`${row.label}-${rowIndex}`}>
              <th scope="row">{row.label}</th>
              {row.cells.map((cell, columnIndex) => {
                const exact = formatValue(cell.value);
                const accessible = `${row.label}, ${cell.label}: ${exact}`;
                return (
                  <td key={`${cell.label}-${columnIndex}`}>
                    <Tooltip content={accessible} placement="top">
                      <button
                        type="button"
                        aria-label={accessible}
                        style={{ "--cell-intensity": Math.max(0, (cell.value - minimum) / range) }}
                      >
                        {exact}
                      </button>
                    </Tooltip>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div class="fd-heatmap-scale" aria-hidden="true"><span>{formatValue(minimum)}</span><i /><span>{formatValue(maximum)}</span></div>
    </div>
  );
}

/** Maps finite trend values into the shared chart viewport. */
export function positionTrendPoints(points: readonly TrendChartPoint[]): readonly PositionedTrendPoint[] {
  const finite = points.filter((point) => Number.isFinite(point.value));
  if (finite.length < 2) return [];
  const values = finite.map((point) => point.value);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const span = Math.max(1, maximum - minimum);
  const width = TREND_WIDTH - TREND_PAD_X * 2;
  const height = TREND_HEIGHT - TREND_PAD_TOP - TREND_PAD_BOTTOM;
  return finite.map((point, index) => ({
    ...point,
    index,
    x: TREND_PAD_X + (index / (finite.length - 1)) * width,
    y: TREND_PAD_TOP + height - ((point.value - minimum) / span) * height,
  }));
}

function trendY(value: number, minimum: number, maximum: number): number {
  const height = TREND_HEIGHT - TREND_PAD_TOP - TREND_PAD_BOTTOM;
  return TREND_PAD_TOP + height - ((value - minimum) / Math.max(1, maximum - minimum)) * height;
}

function sortedMedian(values: readonly number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[middle - 1]! + sorted[middle]!) / 2
    : sorted[middle]!;
}
