import type { ComponentChildren, JSX } from "preact";
import { useState } from "preact/hooks";
import { Tooltip } from "./tooltip";
import {
  TREMOR_CHART_HEX,
  tremorChartColor,
  type TremorChartColor,
} from "./chart-colors";

export interface DonutChartSegment {
  readonly label: string;
  readonly value: number;
  readonly color?: TremorChartColor;
  readonly detail?: string;
}

interface DonutChartProps {
  readonly label: string;
  readonly segments: readonly DonutChartSegment[];
  readonly formatValue: (value: number) => string;
  readonly showLabel?: boolean;
  readonly variant?: "donut" | "pie";
  readonly onActiveSegmentChange?: (segment: DonutChartSegment | null) => void;
}

export interface SparkChartPoint {
  readonly label: string;
  readonly value: number;
}

interface SparkChartProps {
  readonly label: string;
  readonly points: readonly SparkChartPoint[];
  readonly formatValue: (value: number) => string;
  readonly color?: TremorChartColor;
}

interface ProgressChartProps {
  readonly label: string;
  readonly value: number;
  readonly formatValue?: (value: number) => string;
  readonly color?: TremorChartColor;
  readonly variant?: "default" | "error" | "success" | "warning";
  readonly radius?: number;
  readonly children?: ComponentChildren;
}

export interface TrackerBlock {
  readonly label: string;
  readonly color?: TremorChartColor;
  readonly detail?: string;
}

interface TrackerProps {
  readonly label: string;
  readonly blocks: readonly TrackerBlock[];
}

const SPARK_WIDTH = 120;
const SPARK_HEIGHT = 48;

export function DonutChart({
  label,
  segments,
  formatValue,
  showLabel = true,
  variant = "donut",
  onActiveSegmentChange,
}: DonutChartProps) {
  const [activeSegment, setActiveSegment] = useState<DonutChartSegment | null>(null);
  const finite = segments.filter((segment) => Number.isFinite(segment.value) && segment.value >= 0);
  const total = finite.reduce((sum, segment) => sum + segment.value, 0);
  let offset = 0;
  const stops = finite.map((segment, index) => {
    const color = TREMOR_CHART_HEX[segment.color ?? tremorChartColor(index)];
    const start = total === 0 ? 0 : offset / total * 100;
    offset += segment.value;
    const end = total === 0 ? 0 : offset / total * 100;
    return `${color} ${start}% ${end}%`;
  });
  const background = total === 0 ? "var(--tremor-gray)" : `conic-gradient(from 0deg, ${stops.join(", ")})`;
  const formattedTotal = formatValue(total);
  const tooltipSegments = activeSegment ? [activeSegment] : finite;

  function activate(segment: DonutChartSegment | null): void {
    setActiveSegment((current) => {
      if (current === segment) return current;
      onActiveSegmentChange?.(segment);
      return segment;
    });
  }

  function activatePointerSegment(event: JSX.TargetedPointerEvent<HTMLButtonElement>): void {
    if (total === 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left - rect.width / 2;
    const y = event.clientY - rect.top - rect.height / 2;
    if (variant === "donut" && Math.hypot(x, y) < rect.width * .29) {
      activate(null);
      return;
    }
    const ratio = (Math.atan2(y, x) + Math.PI / 2 + Math.PI * 2) % (Math.PI * 2) / (Math.PI * 2);
    let cumulative = 0;
    activate(finite.find((segment) => {
      cumulative += segment.value / total;
      return ratio <= cumulative;
    }) ?? finite.at(-1) ?? null);
  }

  function activateKeyboardSegment(event: JSX.TargetedKeyboardEvent<HTMLButtonElement>): void {
    if (finite.length === 0 || !["ArrowDown", "ArrowLeft", "ArrowRight", "ArrowUp", "End", "Home"].includes(event.key)) return;
    event.preventDefault();
    const currentIndex = activeSegment === null ? -1 : finite.indexOf(activeSegment);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? finite.length - 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? (currentIndex <= 0 ? finite.length : currentIndex) - 1
          : (currentIndex + 1) % finite.length;
    activate(finite[nextIndex] ?? null);
  }
  return (
    <div class="fd-donut-chart" aria-label={label}>
      <Tooltip
        content={
          <span class="fd-series-tooltip">
            <strong>{label}</strong>
            {tooltipSegments.map((segment, index) => (
              <span key={`${segment.label}-${index}`}>
                <i style={{ "--series-color": TREMOR_CHART_HEX[segment.color ?? tremorChartColor(index)] }} />
                <span>{segment.label}</span>
                <b>{formatValue(segment.value)}</b>
              </span>
            ))}
          </span>
        }
        placement="top"
        anchorClassName="fd-donut-tooltip"
      >
        <button type="button" class={`fd-donut-visual is-${variant}`} aria-label={activeSegment ? `${label}: ${activeSegment.label}, ${formatValue(activeSegment.value)}` : `${label}: ${formattedTotal}`} style={{ "--donut-background": background }} onPointerMove={activatePointerSegment} onPointerLeave={() => activate(null)} onKeyDown={activateKeyboardSegment} onBlur={() => activate(null)}>
          {showLabel && variant === "donut" ? <strong>{formattedTotal}</strong> : null}
        </button>
      </Tooltip>
      <div class="fd-donut-legend" role="list">
        {finite.map((segment, index) => {
          const color = TREMOR_CHART_HEX[segment.color ?? tremorChartColor(index)];
          const exact = formatValue(segment.value);
          const accessible = `${segment.label}: ${exact}${segment.detail ? `. ${segment.detail}` : ""}`;
          return (
            <div role="listitem" key={`${segment.label}-${index}`}>
              <Tooltip content={accessible} placement="top">
                <button type="button" aria-label={accessible} style={{ "--series-color": color }} onPointerEnter={() => activate(segment)} onPointerLeave={() => activate(null)} onFocus={() => activate(segment)} onBlur={() => activate(null)}>
                  <i />
                  <span>{segment.label}</span>
                  <strong>{exact}</strong>
                </button>
              </Tooltip>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SparkAreaChart(props: SparkChartProps) {
  return <SparkChart {...props} type="area" />;
}

export function SparkLineChart(props: SparkChartProps) {
  return <SparkChart {...props} type="line" />;
}

export function SparkBarChart(props: SparkChartProps) {
  return <SparkChart {...props} type="bar" />;
}

function SparkChart({
  label,
  points,
  formatValue,
  color = "blue",
  type,
}: SparkChartProps & { readonly type: "area" | "bar" | "line" }) {
  const finite = points.filter((point) => Number.isFinite(point.value));
  if (finite.length === 0) return null;
  const values = finite.map((point) => point.value);
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(0, ...values);
  const range = Math.max(1, maximum - minimum);
  const x = (index: number) => finite.length === 1 ? SPARK_WIDTH / 2 : index / (finite.length - 1) * SPARK_WIDTH;
  const y = (value: number) => SPARK_HEIGHT - (value - minimum) / range * SPARK_HEIGHT;
  const zeroY = y(0);
  const line = finite.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const area = `M0 ${zeroY} L${line.replaceAll(" ", " L")} L${SPARK_WIDTH} ${zeroY} Z`;
  const seriesColor = TREMOR_CHART_HEX[color];
  const barWidth = Math.max(3, SPARK_WIDTH / Math.max(1, finite.length) * .56);
  return (
    <div class="fd-spark-chart" role="group" aria-label={label} style={{ "--series-color": seriesColor }}>
      <svg viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`} aria-hidden="true" preserveAspectRatio="none">
        {type === "area" ? <path class="fd-spark-area" d={area} /> : null}
        {type === "bar" ? finite.map((point, index) => <rect key={index} class="fd-spark-bar" x={x(index) - barWidth / 2} y={Math.min(y(point.value), zeroY)} width={barWidth} height={Math.max(1, Math.abs(zeroY - y(point.value)))} />) : <polyline class="fd-spark-line" points={line} />}
      </svg>
      {finite.map((point, index) => {
        const accessible = `${point.label}: ${formatValue(point.value)}`;
        return (
          <Tooltip key={`${point.label}-${index}`} content={accessible} placement="top">
            <button type="button" aria-label={accessible} style={{ "--spark-x": `${x(index) / SPARK_WIDTH * 100}%`, "--spark-y": `${y(point.value) / SPARK_HEIGHT * 100}%` }} />
          </Tooltip>
        );
      })}
    </div>
  );
}

export function ProgressBar({
  label,
  value,
  formatValue = (current) => `${Math.round(current * 100)}%`,
  color = "blue",
}: ProgressChartProps) {
  const ratio = clampRatio(value);
  const exact = formatValue(ratio);
  return (
    <Tooltip content={`${label}: ${exact}`} placement="top" anchorClassName="fd-progress-tooltip">
      <div class="fd-progress-chart" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={1} aria-valuenow={ratio} style={{ "--series-color": TREMOR_CHART_HEX[color], "--progress-value": ratio }}>
        <span><i /></span><strong>{exact}</strong>
      </div>
    </Tooltip>
  );
}

export function ProgressCircle({
  label,
  value,
  formatValue = (current) => `${Math.round(current * 100)}%`,
  color,
  variant = "default",
  radius = 44,
  children,
}: ProgressChartProps) {
  const ratio = clampRatio(value);
  const circumference = Math.PI * 2 * 16;
  const exact = formatValue(ratio);
  const diameter = Math.max(48, Math.min(160, radius * 2));
  const resolvedColor = color ?? ({ default: "blue", error: "pink", success: "emerald", warning: "amber" } as const)[variant];
  return (
    <Tooltip content={`${label}: ${exact}`} placement="top" anchorClassName="fd-progress-circle-tooltip" anchorStyle={{ "--progress-diameter": `${diameter}px` }}>
      <div class="fd-progress-circle" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={1} aria-valuenow={ratio} data-variant={variant} style={{ "--series-color": TREMOR_CHART_HEX[resolvedColor], "--progress-diameter": `${diameter}px` }}>
        <svg viewBox="0 0 40 40" aria-hidden="true">
          <circle class="fd-progress-circle-track" cx="20" cy="20" r="16" />
          <circle class="fd-progress-circle-value" cx="20" cy="20" r="16" stroke-dasharray={`${circumference * ratio} ${circumference}`} />
        </svg>
        <strong>{children ?? exact}</strong>
      </div>
    </Tooltip>
  );
}

export function Tracker({ label, blocks }: TrackerProps) {
  return (
    <div class="fd-tracker" role="list" aria-label={label}>
      {blocks.map((block, index) => {
        const color = TREMOR_CHART_HEX[block.color ?? "gray"];
        const accessible = `${block.label}${block.detail ? `: ${block.detail}` : ""}`;
        return (
          <div role="listitem" key={`${block.label}-${index}`}>
            <Tooltip content={accessible} placement="top">
              <button type="button" aria-label={accessible} style={{ "--series-color": color }} />
            </Tooltip>
          </div>
        );
      })}
    </div>
  );
}

function clampRatio(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}
