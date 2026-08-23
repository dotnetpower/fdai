import type { ComponentChildren } from "preact";
import { useId, useState } from "preact/hooks";
import { Tooltip } from "./tooltip";
import {
  TREMOR_CHART_HEX,
  tremorChartColor,
  type TremorChartColor,
} from "./chart-colors";

export interface SeriesDefinition {
  readonly label: string;
  readonly color?: TremorChartColor;
  readonly colorForValue?: (value: number, datum: SeriesDatum) => TremorChartColor;
}

export interface ComboSeriesDefinition extends SeriesDefinition {
  readonly kind: "area" | "bar" | "line";
}

export interface SeriesDatum {
  readonly label: string;
  readonly values: readonly number[];
  readonly detail?: string;
}

export type SeriesChartType = "default" | "percent" | "stacked";
export type SeriesChartLayout = "horizontal" | "vertical";
export type AreaFill = "gradient" | "none" | "solid";

export interface SeriesTooltipEntry {
  readonly label: string;
  readonly value: number;
  readonly color: string;
}

export type SeriesTooltipRenderer = (
  datum: SeriesDatum,
  entries: readonly SeriesTooltipEntry[],
) => ComponentChildren;

interface SeriesChartOptions {
  readonly showHeader?: boolean;
  readonly showLegend?: boolean;
  readonly showXAxis?: boolean;
  readonly showYAxis?: boolean;
  readonly showGridLines?: boolean;
  readonly startEndOnly?: boolean;
  readonly xAxisTickCount?: number;
  readonly yAxisWidth?: number;
  readonly minValue?: number;
  readonly maxValue?: number;
  readonly type?: SeriesChartType;
  readonly layout?: SeriesChartLayout;
  readonly xAxisLabel?: string;
  readonly yAxisLabel?: string;
  readonly fill?: AreaFill;
  readonly customTooltip?: SeriesTooltipRenderer;
  readonly barRadius?: number;
  readonly barGradient?: boolean;
  readonly onActiveDatumChange?: (datum: SeriesDatum | null) => void;
  readonly onValueChange?: (datum: SeriesDatum | null) => void;
}

interface SeriesChartProps extends SeriesChartOptions {
  readonly title: string;
  readonly description?: string;
  readonly data: readonly SeriesDatum[];
  readonly series: readonly ComboSeriesDefinition[];
  readonly formatValue: (value: number) => string;
  readonly className?: string;
}

interface StandardSeriesChartProps extends SeriesChartOptions {
  readonly title: string;
  readonly description?: string;
  readonly data: readonly SeriesDatum[];
  readonly series: readonly SeriesDefinition[];
  readonly formatValue: (value: number) => string;
  readonly className?: string;
}

const WIDTH = 360;
const HEIGHT = 180;
const PAD_TOP = 16;
const PAD_BOTTOM = 32;

export function AreaChart(props: StandardSeriesChartProps) {
  return <SeriesChart {...props} series={withKind(props.series, "area")} />;
}

export function LineChart(props: StandardSeriesChartProps) {
  return <SeriesChart {...props} series={withKind(props.series, "line")} />;
}

export function BarChart(props: StandardSeriesChartProps) {
  return <SeriesChart {...props} series={withKind(props.series, "bar")} />;
}

export function ComboChart(props: SeriesChartProps) {
  return <SeriesChart {...props} />;
}

function SeriesChart({
  title,
  description,
  data,
  series,
  formatValue,
  className,
  showHeader = true,
  showLegend = true,
  showXAxis = true,
  showYAxis = false,
  showGridLines = true,
  startEndOnly = false,
  xAxisTickCount = 7,
  yAxisWidth = 44,
  minValue,
  maxValue,
  type = "default",
  layout = "horizontal",
  xAxisLabel,
  yAxisLabel,
  fill = "gradient",
  customTooltip,
  barRadius = 2,
  barGradient = false,
  onActiveDatumChange,
  onValueChange,
}: SeriesChartProps) {
  const gradientPrefix = useId().replaceAll(":", "");
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const usableSeries = availableSeriesIndices(data, series.length).map((sourceIndex) => ({
    definition: series[sourceIndex]!,
    sourceIndex,
  }));
  if (type === "percent" && !percentSeriesDataIsValid(data, usableSeries.map(({ sourceIndex }) => sourceIndex))) return null;
  const projectedValues = projectSeriesValues(
    data,
    usableSeries.map(({ sourceIndex }) => sourceIndex),
    type,
  );
  const values = projectedValues.flatMap((row) => row.filter(Number.isFinite));
  if (data.length === 0 || usableSeries.length === 0 || values.length === 0) return null;
  const bounds = seriesBounds(projectedValues, type);
  const minimum = minValue ?? bounds.minimum;
  const requestedMaximum = maxValue ?? bounds.maximum;
  const maximum = requestedMaximum <= minimum ? minimum + 1 : requestedMaximum;
  const range = Math.max(1, maximum - minimum);
  const padLeft = showYAxis ? Math.max(28, Math.min(72, yAxisWidth)) : 12;
  const padRight = 12;
  const plotWidth = WIDTH - padLeft - padRight;
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const pointX = (index: number) => padLeft + (data.length === 1 ? plotWidth / 2 : (index / (data.length - 1)) * plotWidth);
  const pointY = (value: number) => PAD_TOP + plotHeight - ((value - minimum) / range) * plotHeight;
  const zeroY = pointY(Math.max(minimum, Math.min(maximum, 0)));
  const barSeries = usableSeries.filter(({ definition }) => definition.kind === "bar");
  const groupWidth = Math.max(12, plotWidth / Math.max(1, data.length) * 0.62);
  const stacked = type !== "default";
  const barWidth = stacked ? groupWidth : groupWidth / Math.max(1, barSeries.length);

  if (layout === "vertical" && barSeries.length > 0) {
    return renderVerticalBarChart({
      title, description, data, usableSeries, projectedValues, formatValue, className,
      showHeader, showLegend, showXAxis, showYAxis, showGridLines, xAxisLabel,
      yAxisLabel, minimum, maximum, type, customTooltip, barRadius,
      barGradient, gradientPrefix, onActiveDatumChange, onValueChange,
      selectedIndex, setSelectedIndex, yAxisWidth,
    });
  }

  return (
    <figure class={`fd-series-chart${className ? ` ${className}` : ""}`} data-type={type} data-fill={fill} data-layout={layout}>
      {showHeader ? <figcaption class="fd-chart-head">
        <span><strong>{title}</strong>{description ? <small>{description}</small> : null}</span>
      </figcaption> : null}
      <div class="fd-series-plot" role="group" aria-label={description ?? title}>
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true" preserveAspectRatio="none">
          {barGradient || fill === "gradient" ? <defs>
            {barGradient ? barSeries.map(({ definition }, index) => {
              const color = TREMOR_CHART_HEX[definition.color ?? tremorChartColor(index)];
              return <linearGradient key={`bar-${definition.label}`} id={`${gradientPrefix}-bar-${index}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color={color} stop-opacity=".62" /><stop offset="1" stop-color={color} /></linearGradient>;
            }) : null}
            {fill === "gradient" ? usableSeries.flatMap(({ definition }, index) => definition.kind === "area" ? [<linearGradient key={`area-${definition.label}`} id={`${gradientPrefix}-area-${index}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color={TREMOR_CHART_HEX[definition.color ?? tremorChartColor(index)]} stop-opacity=".34" /><stop offset="1" stop-color={TREMOR_CHART_HEX[definition.color ?? tremorChartColor(index)]} stop-opacity=".03" /></linearGradient>] : []) : null}
          </defs> : null}
          {showGridLines ? <path class="fd-chart-grid" d={`M${padLeft} ${PAD_TOP}H${WIDTH - padRight} M${padLeft} ${PAD_TOP + plotHeight / 2}H${WIDTH - padRight} M${padLeft} ${zeroY}H${WIDTH - padRight}`} /> : null}
          {usableSeries.map(({ definition, sourceIndex }, seriesIndex) => {
            const color = TREMOR_CHART_HEX[definition.color ?? tremorChartColor(seriesIndex)];
            const points = data.flatMap((datum, dataIndex) => {
              const projected = projectedValues[dataIndex]?.[seriesIndex];
              if (projected === undefined || !Number.isFinite(projected)) return [];
              const base = stacked ? stackBase(projectedValues[dataIndex]!, seriesIndex) : 0;
              return datum.values[sourceIndex] === undefined
                ? []
                : [{ dataIndex, datum, x: pointX(dataIndex), y: pointY(base + projected), baseY: pointY(base), value: projected }];
            });
            if (definition.kind === "bar") {
              const barIndex = barSeries.findIndex((item) => item.sourceIndex === sourceIndex);
              return (
                <g key={`${definition.label}-${seriesIndex}`} style={{ color }}>
                  {points.map((point) => {
                    const resolved = TREMOR_CHART_HEX[definition.colorForValue?.(point.value, point.datum) ?? definition.color ?? tremorChartColor(seriesIndex)];
                    const x = point.x - groupWidth / 2 + (stacked ? 0 : barIndex * barWidth);
                    return <rect key={point.dataIndex} class="fd-series-bar" x={x} y={Math.min(point.y, point.baseY)} width={Math.max(2, barWidth - 2)} height={Math.max(1, Math.abs(point.baseY - point.y))} rx={barRadius} ry={barRadius} style={{ color: resolved, ...(barGradient ? { fill: `url(#${gradientPrefix}-bar-${barIndex})` } : {}) }} />;
                  })}
                </g>
              );
            }
            const segments = contiguousSeriesSegments(points);
            return (
              <g key={`${definition.label}-${seriesIndex}`} style={{ color }}>
                {segments.map((segment, segmentIndex) => {
                  const line = segment.map((point) => `${point.x},${point.y}`).join(" ");
                  const lower = [...segment].reverse().map((point) => `${point.x},${stacked ? point.baseY : zeroY}`).join(" L");
                  const area = `M${line.replaceAll(" ", " L")} L${lower} Z`;
                  return <g key={segmentIndex}>
                    {definition.kind === "area" ? <path class="fd-series-area" d={area} style={fill === "gradient" ? { fill: `url(#${gradientPrefix}-area-${seriesIndex})` } : undefined} /> : null}
                    {segment.length > 1 ? <polyline class="fd-series-line" points={line} /> : <circle class="fd-series-isolated" cx={segment[0]!.x} cy={segment[0]!.y} r="2.5" />}
                  </g>;
                })}
              </g>
            );
          })}
        </svg>
        {data.map((datum, dataIndex) => {
          const entries = usableSeries.flatMap(({ definition, sourceIndex }, seriesIndex) => {
            const value = datum.values[sourceIndex];
            if (value === undefined || !Number.isFinite(value)) return [];
            const projected = projectedValues[dataIndex]?.[seriesIndex];
            if (projected === undefined || !Number.isFinite(projected)) return [];
            return [{
              color: TREMOR_CHART_HEX[definition.colorForValue?.(value, datum) ?? definition.color ?? tremorChartColor(seriesIndex)],
              definition,
              plotValue: stacked ? stackBase(projectedValues[dataIndex]!, seriesIndex) + projected : projected,
              value,
            }];
          });
          if (entries.length === 0) return null;
          const previousX = dataIndex === 0 ? 0 : (pointX(dataIndex - 1) + pointX(dataIndex)) / 2;
          const nextX = dataIndex === data.length - 1 ? WIDTH : (pointX(dataIndex) + pointX(dataIndex + 1)) / 2;
          const categoryX = (pointX(dataIndex) - previousX) / Math.max(1, nextX - previousX) * 100;
          const accessible = `${datum.label}. ${entries.map((entry) => `${entry.definition.label}: ${formatValue(entry.value)}`).join(". ")}${datum.detail ? `. ${datum.detail}` : ""}`;
          return (
            <Tooltip
              key={`${datum.label}-${dataIndex}`}
              content={customTooltip?.(datum, entries.map((entry) => ({ label: entry.definition.label, value: entry.value, color: entry.color }))) ??
                <span class="fd-series-tooltip">
                  <strong>{datum.label}</strong>
                  {entries.map((entry) => (
                    <span key={entry.definition.label}>
                      <i style={{ "--series-color": entry.color }} />
                      <span>{entry.definition.label}</span>
                      <b>{formatValue(entry.value)}</b>
                    </span>
                  ))}
                  {datum.detail ? <small>{datum.detail}</small> : null}
                </span>
              }
              placement="right"
              anchorClassName="fd-series-slice-anchor"
              anchorStyle={{
                "--series-slice-left": `${previousX / WIDTH * 100}%`,
                "--series-slice-width": `${(nextX - previousX) / WIDTH * 100}%`,
              }}
            >
              <button
                type="button"
                class="fd-series-slice"
                aria-label={accessible}
                aria-pressed={selectedIndex === dataIndex}
                data-selected={selectedIndex === dataIndex ? "true" : undefined}
                style={{ "--series-category-x": `${categoryX}%` }}
                onPointerEnter={() => onActiveDatumChange?.(datum)}
                onPointerLeave={() => onActiveDatumChange?.(null)}
                onFocus={() => onActiveDatumChange?.(datum)}
                onBlur={() => onActiveDatumChange?.(null)}
                onClick={() => setSelectedIndex((current) => {
                  const next = current === dataIndex ? null : dataIndex;
                  onValueChange?.(next === null ? null : datum);
                  return next;
                })}
              >
                {entries.map((entry) => (
                  <i
                    key={entry.definition.label}
                    style={{
                      "--series-color": entry.color,
                      "--series-point-y": `${(pointY(entry.plotValue) - PAD_TOP) / plotHeight * 100}%`,
                    }}
                  />
                ))}
              </button>
            </Tooltip>
          );
        })}
        {showYAxis ? <div class="fd-series-y-axis" aria-hidden="true" style={{ "--series-axis-left": `${padLeft / WIDTH * 100}%` }}>
          <span>{formatValue(maximum)}</span>
          <span>{formatValue(minimum + range / 2)}</span>
          <span>{formatValue(minimum)}</span>
        </div> : null}
        {showXAxis ? <div class="fd-series-x-axis" aria-hidden="true" style={{ "--series-axis-left": `${padLeft / WIDTH * 100}%`, "--series-axis-right": `${padRight / WIDTH * 100}%` }}>
          {visibleTickIndices(data.length, startEndOnly ? 2 : xAxisTickCount).map((index) => <span key={`${data[index]!.label}-${index}`} data-edge={index === 0 ? "start" : index === data.length - 1 ? "end" : undefined} style={{ "--series-tick-x": `${data.length === 1 ? 50 : index / (data.length - 1) * 100}%` }}>{data[index]!.label}</span>)}
        </div> : null}
        {xAxisLabel ? <span class="fd-series-x-title">{xAxisLabel}</span> : null}
        {yAxisLabel ? <span class="fd-series-y-title">{yAxisLabel}</span> : null}
      </div>
      {showLegend ? <div class="fd-series-legend" aria-hidden="true">
        {usableSeries.map(({ definition }, index) => {
          const color = TREMOR_CHART_HEX[definition.color ?? tremorChartColor(index)];
          return <span key={`${definition.label}-${index}`}><i style={{ "--series-color": color }} />{definition.label}</span>;
        })}
      </div> : null}
    </figure>
  );
}

function withKind(
  series: readonly SeriesDefinition[],
  kind: ComboSeriesDefinition["kind"],
): readonly ComboSeriesDefinition[] {
  return series.map((item) => ({ ...item, kind }));
}

export function availableSeriesIndices(
  data: readonly SeriesDatum[],
  seriesCount: number,
): readonly number[] {
  return Array.from({ length: seriesCount }, (_, index) => index).filter((seriesIndex) =>
    data.some((datum) => Number.isFinite(datum.values[seriesIndex])),
  );
}

export function visibleTickIndices(length: number, requestedCount: number): readonly number[] {
  if (length <= 0) return [];
  const count = Math.max(2, Math.min(length, Math.floor(requestedCount)));
  return [...new Set(Array.from({ length: count }, (_, index) =>
    Math.round(index / Math.max(1, count - 1) * (length - 1)),
  ))];
}

export function projectSeriesValues(
  data: readonly SeriesDatum[],
  sourceIndices: readonly number[],
  type: SeriesChartType,
): readonly (readonly number[])[] {
  return data.map((datum) => {
    const row = sourceIndices.map((sourceIndex) => {
      const value = datum.values[sourceIndex];
      return value === undefined || !Number.isFinite(value) ? Number.NaN : value;
    });
    if (type !== "percent") return row;
    const total = row.reduce((sum, value) => Number.isFinite(value) ? sum + value : sum, 0);
    return row.map((value) => !Number.isFinite(value) ? Number.NaN : total === 0 ? 0 : value / total * 100);
  });
}

export function seriesBounds(
  rows: readonly (readonly number[])[],
  type: SeriesChartType,
): { readonly minimum: number; readonly maximum: number } {
  if (type === "percent") return { minimum: 0, maximum: 100 };
  if (type === "stacked") {
    const negative = rows.map((row) => row.reduce((sum, value) => Number.isFinite(value) && value < 0 ? sum + value : sum, 0));
    const positive = rows.map((row) => row.reduce((sum, value) => Number.isFinite(value) && value > 0 ? sum + value : sum, 0));
    return { minimum: Math.min(0, ...negative), maximum: Math.max(0, ...positive) };
  }
  const finite = rows.flatMap((row) => row.filter(Number.isFinite));
  return { minimum: Math.min(0, ...finite), maximum: Math.max(0, ...finite) };
}

function stackBase(row: readonly number[], seriesIndex: number): number {
  const value = row[seriesIndex];
  if (value === undefined || !Number.isFinite(value)) return 0;
  return row.slice(0, seriesIndex).reduce((sum, candidate) => {
    if (!Number.isFinite(candidate) || Math.sign(candidate) !== Math.sign(value)) return sum;
    return sum + candidate;
  }, 0);
}

export function percentSeriesDataIsValid(
  data: readonly SeriesDatum[],
  sourceIndices: readonly number[],
): boolean {
  return data.every((datum) => sourceIndices.every((sourceIndex) => {
    const value = datum.values[sourceIndex];
    return value === undefined || !Number.isFinite(value) || value >= 0;
  }));
}

export function contiguousSeriesSegments<T extends { readonly dataIndex: number }>(
  points: readonly T[],
): readonly (readonly T[])[] {
  return points.reduce<T[][]>((segments, point) => {
    const current = segments.at(-1);
    if (!current || current.at(-1)!.dataIndex + 1 !== point.dataIndex) segments.push([point]);
    else current.push(point);
    return segments;
  }, []);
}

interface VerticalBarChartProps {
  readonly title: string;
  readonly description: string | undefined;
  readonly data: readonly SeriesDatum[];
  readonly usableSeries: readonly {
    readonly definition: ComboSeriesDefinition;
    readonly sourceIndex: number;
  }[];
  readonly projectedValues: readonly (readonly number[])[];
  readonly formatValue: (value: number) => string;
  readonly className: string | undefined;
  readonly showHeader: boolean;
  readonly showLegend: boolean;
  readonly showXAxis: boolean;
  readonly showYAxis: boolean;
  readonly showGridLines: boolean;
  readonly xAxisLabel: string | undefined;
  readonly yAxisLabel: string | undefined;
  readonly minimum: number;
  readonly maximum: number;
  readonly type: SeriesChartType;
  readonly customTooltip: SeriesTooltipRenderer | undefined;
  readonly barRadius: number;
  readonly barGradient: boolean;
  readonly gradientPrefix: string;
  readonly onActiveDatumChange: ((datum: SeriesDatum | null) => void) | undefined;
  readonly onValueChange: ((datum: SeriesDatum | null) => void) | undefined;
  readonly selectedIndex: number | null;
  readonly setSelectedIndex: (next: (current: number | null) => number | null) => void;
  readonly yAxisWidth: number;
}

function renderVerticalBarChart({
  title,
  description,
  data,
  usableSeries,
  projectedValues,
  formatValue,
  className,
  showHeader,
  showLegend,
  showXAxis,
  showYAxis,
  showGridLines,
  xAxisLabel,
  yAxisLabel,
  minimum,
  maximum,
  type,
  customTooltip,
  barRadius,
  barGradient,
  gradientPrefix,
  onActiveDatumChange,
  onValueChange,
  selectedIndex,
  setSelectedIndex,
  yAxisWidth,
}: VerticalBarChartProps) {
  const range = Math.max(1, maximum - minimum);
  const padLeft = showYAxis ? Math.max(42, Math.min(96, yAxisWidth)) : 12;
  const padRight = 12;
  const plotWidth = WIDTH - padLeft - padRight;
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const valueX = (value: number) => padLeft + (value - minimum) / range * plotWidth;
  const zeroX = valueX(Math.max(minimum, Math.min(maximum, 0)));
  const rowHeight = plotHeight / Math.max(1, data.length);
  const groupHeight = Math.max(8, rowHeight * .62);
  const stacked = type !== "default";
  const barHeight = stacked ? groupHeight : groupHeight / Math.max(1, usableSeries.length);
  return (
    <figure class={`fd-series-chart is-vertical${className ? ` ${className}` : ""}`} data-type={type} data-layout="vertical">
      {showHeader ? <figcaption class="fd-chart-head"><span><strong>{title}</strong>{description ? <small>{description}</small> : null}</span></figcaption> : null}
      <div class="fd-series-plot" role="group" aria-label={description ?? title}>
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true" preserveAspectRatio="none">
          {barGradient ? <defs>{usableSeries.map(({ definition }, index) => {
            const color = TREMOR_CHART_HEX[definition.color ?? tremorChartColor(index)];
            return <linearGradient key={definition.label} id={`${gradientPrefix}-vertical-${index}`} x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color={color} stop-opacity=".62" /><stop offset="1" stop-color={color} /></linearGradient>;
          })}</defs> : null}
          {showGridLines ? <path class="fd-chart-grid" d={`M${padLeft} ${PAD_TOP}V${HEIGHT - PAD_BOTTOM} M${padLeft + plotWidth / 2} ${PAD_TOP}V${HEIGHT - PAD_BOTTOM} M${WIDTH - padRight} ${PAD_TOP}V${HEIGHT - PAD_BOTTOM}`} /> : null}
          {data.flatMap((datum, dataIndex) => usableSeries.flatMap(({ definition, sourceIndex }, seriesIndex) => {
            const projected = projectedValues[dataIndex]?.[seriesIndex];
            const raw = datum.values[sourceIndex];
            if (projected === undefined || raw === undefined || !Number.isFinite(projected) || !Number.isFinite(raw)) return [];
            const base = stacked ? stackBase(projectedValues[dataIndex]!, seriesIndex) : 0;
            const start = valueX(base);
            const end = valueX(base + projected);
            const resolved = TREMOR_CHART_HEX[definition.colorForValue?.(raw, datum) ?? definition.color ?? tremorChartColor(seriesIndex)];
            const y = PAD_TOP + dataIndex * rowHeight + (rowHeight - groupHeight) / 2 + (stacked ? 0 : seriesIndex * barHeight);
            return [<rect key={`${datum.label}-${definition.label}`} class="fd-series-bar" x={Math.min(start, end)} y={y} width={Math.max(1, Math.abs(end - start))} height={Math.max(2, barHeight - 2)} rx={barRadius} ry={barRadius} style={{ color: resolved, ...(barGradient ? { fill: `url(#${gradientPrefix}-vertical-${seriesIndex})` } : {}) }} />];
          }))}
          <path class="fd-chart-reference" d={`M${zeroX} ${PAD_TOP}V${HEIGHT - PAD_BOTTOM}`} />
        </svg>
        {data.map((datum, dataIndex) => {
          const entries = usableSeries.flatMap(({ definition, sourceIndex }, seriesIndex) => {
            const value = datum.values[sourceIndex];
            if (value === undefined || !Number.isFinite(value)) return [];
            return [{ label: definition.label, value, color: TREMOR_CHART_HEX[definition.colorForValue?.(value, datum) ?? definition.color ?? tremorChartColor(seriesIndex)] }];
          });
          const accessible = `${datum.label}. ${entries.map((entry) => `${entry.label}: ${formatValue(entry.value)}`).join(". ")}`;
          return <Tooltip key={`${datum.label}-${dataIndex}`} content={customTooltip?.(datum, entries) ?? <span class="fd-series-tooltip"><strong>{datum.label}</strong>{entries.map((entry) => <span key={entry.label}><i style={{ "--series-color": entry.color }} /><span>{entry.label}</span><b>{formatValue(entry.value)}</b></span>)}</span>} placement="right" anchorClassName="fd-series-row-anchor" anchorStyle={{ "--series-row-top": `${(PAD_TOP + dataIndex * rowHeight) / HEIGHT * 100}%`, "--series-row-height": `${rowHeight / HEIGHT * 100}%` }}><button type="button" class="fd-series-row" aria-label={accessible} aria-pressed={selectedIndex === dataIndex} data-selected={selectedIndex === dataIndex ? "true" : undefined} onPointerEnter={() => onActiveDatumChange?.(datum)} onPointerLeave={() => onActiveDatumChange?.(null)} onFocus={() => onActiveDatumChange?.(datum)} onBlur={() => onActiveDatumChange?.(null)} onClick={() => setSelectedIndex((current) => { const next = current === dataIndex ? null : dataIndex; onValueChange?.(next === null ? null : datum); return next; })} /></Tooltip>;
        })}
        {showYAxis ? <div class="fd-series-category-axis" aria-hidden="true" style={{ "--series-category-width": `${padLeft / WIDTH * 100}%` }}>{data.map((datum) => <span key={datum.label}>{datum.label}</span>)}</div> : null}
        {showXAxis ? <div class="fd-series-value-axis" aria-hidden="true" style={{ "--series-value-left": `${padLeft / WIDTH * 100}%`, "--series-value-right": `${padRight / WIDTH * 100}%` }}><span>{formatValue(minimum)}</span><span>{formatValue(minimum + range / 2)}</span><span>{formatValue(maximum)}</span></div> : null}
        {xAxisLabel ? <span class="fd-series-x-title">{xAxisLabel}</span> : null}
        {yAxisLabel ? <span class="fd-series-y-title">{yAxisLabel}</span> : null}
      </div>
      {showLegend ? <div class="fd-series-legend" aria-hidden="true">{usableSeries.map(({ definition }, index) => <span key={definition.label}><i style={{ "--series-color": TREMOR_CHART_HEX[definition.color ?? tremorChartColor(index)] }} />{definition.label}</span>)}</div> : null}
    </figure>
  );
}
