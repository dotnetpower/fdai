import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { DonutChart, type DonutChartSegment } from "./charts-compact";
import {
  ComboChart,
  type ComboSeriesDefinition,
  type SeriesDatum,
} from "./charts-series";
import { TREMOR_CHART_HEX, type TremorChartColor } from "./chart-colors";

export interface MetricSummaryItem {
  readonly label: string;
  readonly value: ComponentChildren;
  readonly color?: TremorChartColor;
}

interface MetricChartFrameProps {
  readonly label: string;
  readonly value: ComponentChildren;
  readonly detail?: ComponentChildren;
  readonly summaries?: readonly MetricSummaryItem[];
  readonly children: ComponentChildren;
  readonly className?: string;
}

interface MetricSeriesChartProps {
  readonly label: string;
  readonly value: ComponentChildren;
  readonly detail?: ComponentChildren;
  readonly description?: string;
  readonly data: readonly SeriesDatum[];
  readonly series: readonly ComboSeriesDefinition[];
  readonly formatValue: (value: number) => string;
  readonly valueForDatum?: (datum: SeriesDatum) => ComponentChildren;
  readonly detailForDatum?: (datum: SeriesDatum) => ComponentChildren;
  readonly summaries?: readonly MetricSummaryItem[];
  readonly showLegend?: boolean;
  readonly showYAxis?: boolean;
  readonly showGridLines?: boolean;
  readonly startEndOnly?: boolean;
  readonly xAxisTickCount?: number;
  readonly yAxisWidth?: number;
  readonly minValue?: number;
  readonly maxValue?: number;
  readonly className?: string;
}

interface MetricDonutChartProps {
  readonly label: string;
  readonly value: ComponentChildren;
  readonly detail?: ComponentChildren;
  readonly segments: readonly DonutChartSegment[];
  readonly formatValue: (value: number) => string;
  readonly summaries?: readonly MetricSummaryItem[];
  readonly className?: string;
}

/** Frames one metric and its exact chart without adding another visual card boundary. */
export function MetricChartFrame({
  label,
  value,
  detail,
  summaries,
  children,
  className,
}: MetricChartFrameProps) {
  return (
    <section class={`fd-metric-chart${className ? ` ${className}` : ""}`} aria-label={label}>
      <header class="fd-metric-chart-head">
        <span>{label}</span>
        <strong>{value}</strong>
        {detail ? <small>{detail}</small> : null}
      </header>
      {summaries && summaries.length > 0 ? <dl class="fd-metric-chart-summaries">
        {summaries.map((item, index) => (
          <div key={`${item.label}-${index}`} style={{ "--series-color": TREMOR_CHART_HEX[item.color ?? "gray"] }}>
            <dt><i />{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
      </dl> : null}
      {children}
    </section>
  );
}

/** Composes a KPI header with any line, area, bar, or mixed series definition. */
export function MetricSeriesChart({
  label,
  value,
  detail,
  description,
  data,
  series,
  formatValue,
  valueForDatum,
  detailForDatum,
  summaries,
  showLegend = true,
  showYAxis = true,
  showGridLines = true,
  startEndOnly = false,
  xAxisTickCount,
  yAxisWidth = 52,
  minValue,
  maxValue,
  className,
}: MetricSeriesChartProps) {
  const [activeDatum, setActiveDatum] = useState<SeriesDatum | null>(null);
  const displayDatum = activeDatum ?? data.at(-1) ?? null;
  const displayValue = displayDatum && valueForDatum ? valueForDatum(displayDatum) : value;
  const displayDetail = displayDatum && detailForDatum ? detailForDatum(displayDatum) : detail;
  return (
    <MetricChartFrame
      label={label}
      value={displayValue}
      {...(displayDetail === undefined ? {} : { detail: displayDetail })}
      {...(summaries === undefined ? {} : { summaries })}
      className={`fd-metric-series${className ? ` ${className}` : ""}`}
    >
      <ComboChart
        title={label}
        {...(description === undefined ? {} : { description })}
        data={data}
        series={series}
        formatValue={formatValue}
        showHeader={false}
        showLegend={showLegend}
        showYAxis={showYAxis}
        showGridLines={showGridLines}
        startEndOnly={startEndOnly}
        {...(xAxisTickCount === undefined ? {} : { xAxisTickCount })}
        yAxisWidth={yAxisWidth}
        {...(minValue === undefined ? {} : { minValue })}
        {...(maxValue === undefined ? {} : { maxValue })}
        onActiveDatumChange={setActiveDatum}
        className="fd-metric-series-plot"
      />
    </MetricChartFrame>
  );
}

/** Composes a KPI header with an exact-value donut and its accessible legend. */
export function MetricDonutChart({
  label,
  value,
  detail,
  segments,
  formatValue,
  summaries,
  className,
}: MetricDonutChartProps) {
  return (
    <MetricChartFrame label={label} value={value} {...(detail === undefined ? {} : { detail })} {...(summaries === undefined ? {} : { summaries })} className={`fd-metric-donut${className ? ` ${className}` : ""}`}>
      <DonutChart label={label} segments={segments} formatValue={formatValue} showLabel={false} />
    </MetricChartFrame>
  );
}
