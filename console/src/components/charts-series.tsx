import { Tooltip } from "./tooltip";
import {
  TREMOR_CHART_HEX,
  tremorChartColor,
  type TremorChartColor,
} from "./chart-colors";

export interface SeriesDefinition {
  readonly label: string;
  readonly color?: TremorChartColor;
}

export interface ComboSeriesDefinition extends SeriesDefinition {
  readonly kind: "area" | "bar" | "line";
}

export interface SeriesDatum {
  readonly label: string;
  readonly values: readonly number[];
  readonly detail?: string;
}

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
  readonly onActiveDatumChange?: (datum: SeriesDatum | null) => void;
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
  onActiveDatumChange,
}: SeriesChartProps) {
  const usableSeries = availableSeriesIndices(data, series.length).map((sourceIndex) => ({
    definition: series[sourceIndex]!,
    sourceIndex,
  }));
  const values = data.flatMap((datum) =>
    usableSeries.flatMap(({ sourceIndex }) => {
      const value = datum.values[sourceIndex];
      return value === undefined || !Number.isFinite(value) ? [] : [value];
    }),
  );
  if (data.length === 0 || usableSeries.length === 0 || values.length === 0) return null;
  const minimum = minValue ?? Math.min(0, ...values);
  const requestedMaximum = maxValue ?? Math.max(0, ...values);
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
  const barWidth = groupWidth / Math.max(1, barSeries.length);

  return (
    <figure class={`fd-series-chart${className ? ` ${className}` : ""}`}>
      {showHeader ? <figcaption class="fd-chart-head">
        <span><strong>{title}</strong>{description ? <small>{description}</small> : null}</span>
      </figcaption> : null}
      <div class="fd-series-plot" role="group" aria-label={description ?? title}>
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true" preserveAspectRatio="none">
          {showGridLines ? <path class="fd-chart-grid" d={`M${padLeft} ${PAD_TOP}H${WIDTH - padRight} M${padLeft} ${PAD_TOP + plotHeight / 2}H${WIDTH - padRight} M${padLeft} ${zeroY}H${WIDTH - padRight}`} /> : null}
          {usableSeries.map(({ definition, sourceIndex }, seriesIndex) => {
            const color = TREMOR_CHART_HEX[definition.color ?? tremorChartColor(seriesIndex)];
            const points = data.flatMap((datum, dataIndex) => {
              const value = datum.values[sourceIndex];
              return value === undefined || !Number.isFinite(value)
                ? []
                : [{ dataIndex, x: pointX(dataIndex), y: pointY(value), value }];
            });
            if (definition.kind === "bar") {
              const barIndex = barSeries.findIndex((item) => item.sourceIndex === sourceIndex);
              return (
                <g key={`${definition.label}-${seriesIndex}`} style={{ color }}>
                  {points.map((point) => {
                    const x = point.x - groupWidth / 2 + barIndex * barWidth;
                    return <rect key={point.dataIndex} class="fd-series-bar" x={x} y={Math.min(point.y, zeroY)} width={Math.max(2, barWidth - 2)} height={Math.max(1, Math.abs(zeroY - point.y))} />;
                  })}
                </g>
              );
            }
            const line = points.map((point) => `${point.x},${point.y}`).join(" ");
            const area = points.length === 0 ? "" : `M${points[0]!.x} ${zeroY} L${line.replaceAll(" ", " L")} L${points.at(-1)!.x} ${zeroY} Z`;
            return (
              <g key={`${definition.label}-${seriesIndex}`} style={{ color }}>
                {definition.kind === "area" ? <path class="fd-series-area" d={area} /> : null}
                <polyline class="fd-series-line" points={line} />
              </g>
            );
          })}
        </svg>
        {data.map((datum, dataIndex) => {
          const entries = usableSeries.flatMap(({ definition, sourceIndex }, seriesIndex) => {
            const value = datum.values[sourceIndex];
            if (value === undefined || !Number.isFinite(value)) return [];
            return [{
              color: TREMOR_CHART_HEX[definition.color ?? tremorChartColor(seriesIndex)],
              definition,
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
              content={
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
                style={{ "--series-category-x": `${categoryX}%` }}
                onPointerEnter={() => onActiveDatumChange?.(datum)}
                onPointerLeave={() => onActiveDatumChange?.(null)}
                onFocus={() => onActiveDatumChange?.(datum)}
                onBlur={() => onActiveDatumChange?.(null)}
              >
                {entries.map((entry) => (
                  <i
                    key={entry.definition.label}
                    style={{
                      "--series-color": entry.color,
                      "--series-point-y": `${(pointY(entry.value) - PAD_TOP) / plotHeight * 100}%`,
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
