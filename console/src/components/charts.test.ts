import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { positionTrendPoints } from "./charts";
import { availableSeriesIndices, visibleTickIndices } from "./charts-series";
import {
  TREMOR_CHART_COLORS,
  TREMOR_CHART_COMPONENTS,
  TREMOR_CHART_COMPOSITIONS,
  TREMOR_CHART_HEX,
  tremorChartColor,
} from "./chart-colors";

const source = readFileSync(fileURLToPath(new URL("./charts.tsx", import.meta.url)), "utf8");
const styles = readFileSync(fileURLToPath(new URL("./charts.css", import.meta.url)), "utf8");

describe("shared chart primitives", () => {
  test("uses the exact Tremor Raw chart palette and order", () => {
    expect(TREMOR_CHART_COLORS).toEqual([
      "blue", "emerald", "violet", "amber", "gray", "cyan", "pink", "lime", "fuchsia",
    ]);
    expect(TREMOR_CHART_HEX).toEqual({
      blue: "#3b82f6",
      emerald: "#10b981",
      violet: "#8b5cf6",
      amber: "#f59e0b",
      gray: "#6b7280",
      cyan: "#06b6d4",
      pink: "#ec4899",
      lime: "#84cc16",
      fuchsia: "#d946ef",
    });
    expect(tremorChartColor(9)).toBe("blue");
    for (const [color, hex] of Object.entries(TREMOR_CHART_HEX)) {
      expect(styles).toContain(`--tremor-${color}: ${hex}`);
    }
  });

  test("declares every official Tremor Raw chart and data visualization", () => {
    expect(TREMOR_CHART_COMPONENTS).toEqual([
      "AreaChart", "BarChart", "BarList", "CategoryBar", "ComboChart", "DonutChart",
      "LineChart", "ProgressBar", "ProgressCircle", "SparkAreaChart", "SparkBarChart",
      "SparkLineChart", "Tracker",
    ]);
    for (const component of TREMOR_CHART_COMPONENTS) {
      expect(source).toContain(component);
    }
  });

  test("declares and exports every supported Tremor showcase composition family", () => {
    expect(TREMOR_CHART_COMPOSITIONS).toEqual([
      "PortfolioPerformance", "InteractiveKpiArea", "ComparisonLine",
      "AllocationDonut", "CustomTooltipBar", "ResponsiveMonitoringArea",
      "UptimeCategory",
    ]);
    const composedSource = readFileSync(fileURLToPath(new URL("./charts-composed.tsx", import.meta.url)), "utf8");
    for (const component of ["MetricChartFrame", "MetricSeriesChart", "MetricDonutChart"]) {
      expect(composedSource).toContain(`export function ${component}`);
      expect(source).toContain(component);
    }
    expect(composedSource).toContain("valueForDatum");
    expect(composedSource).toContain("detailForDatum");
    expect(styles).toContain(".fd-metric-chart-head");
  });

  test("maps finite trend values into one stable bounded viewport", () => {
    const points = positionTrendPoints([
      { label: "A", value: 10 },
      { label: "bad", value: Number.NaN },
      { label: "B", value: 30 },
      { label: "C", value: 20 },
    ]);

    expect(points).toHaveLength(3);
    expect(points.map((point) => point.label)).toEqual(["A", "B", "C"]);
    expect(points[0]?.x).toBe(18);
    expect(points.at(-1)?.x).toBe(342);
    expect(Math.min(...points.map((point) => point.y))).toBe(20);
    expect(Math.max(...points.map((point) => point.y))).toBe(126);
  });

  test("keeps trend values keyboard inspectable with explicit peak and current roles", () => {
    expect(source).toContain('class="fd-chart-point"');
    expect(source).toContain('anchorClassName="fd-chart-slice-anchor"');
    expect(source).toContain('data-role={role}');
    expect(source).toContain('type="button"');
    expect(source).toContain('point.index === current.index ? "current"');
    expect(source).toContain('point.index === peak.index ? "peak"');
    expect(source).toContain("referenceLabel");
  });

  test("exports every full-size Tremor chart type through one shared coordinate system", () => {
    const seriesSource = readFileSync(fileURLToPath(new URL("./charts-series.tsx", import.meta.url)), "utf8");
    for (const component of ["AreaChart", "LineChart", "BarChart", "ComboChart"]) {
      expect(seriesSource).toContain(`export function ${component}`);
      expect(source).toContain(component);
    }
    expect(seriesSource).toContain('kind: "area" | "bar" | "line"');
    expect(seriesSource).toContain('class="fd-series-slice"');
    expect(seriesSource).toContain('class="fd-series-tooltip"');
    expect(seriesSource).toContain("entries.map((entry)");
    for (const option of [
      "showHeader", "showLegend", "showXAxis", "showYAxis", "showGridLines",
      "startEndOnly", "xAxisTickCount", "yAxisWidth", "minValue", "maxValue", "onActiveDatumChange",
    ]) {
      expect(seriesSource).toContain(option);
    }
    expect(seriesSource).toContain('class="fd-series-y-axis"');
    expect(seriesSource).toContain('class="fd-series-x-axis"');
    expect(styles).toContain(".fd-series-slice:focus-visible");
    expect(styles).toContain(".fd-series-slice:hover::before");
    expect(styles).not.toContain("canvas");
  });

  test("preserves source indices when a middle series has no finite values", () => {
    expect(availableSeriesIndices([
      { label: "A", values: [10, Number.NaN, 30] },
      { label: "B", values: [12, Number.NaN, 28] },
    ], 3)).toEqual([0, 2]);
  });

  test("bounds dense date-axis ticks while preserving both edges", () => {
    expect(visibleTickIndices(17, 6)).toEqual([0, 3, 6, 10, 13, 16]);
    expect(visibleTickIndices(7, 7)).toEqual([0, 1, 2, 3, 4, 5, 6]);
    expect(visibleTickIndices(1, 2)).toEqual([0]);
  });

  test("exports every compact Tremor chart and tracking visualization", () => {
    const compactSource = readFileSync(fileURLToPath(new URL("./charts-compact.tsx", import.meta.url)), "utf8");
    for (const component of [
      "DonutChart", "SparkAreaChart", "SparkLineChart", "SparkBarChart",
      "ProgressBar", "ProgressCircle", "Tracker",
    ]) {
      expect(compactSource).toContain(`export function ${component}`);
      expect(source).toContain(component);
    }
    expect(compactSource).toContain("conic-gradient(from 0deg");
    expect(compactSource).toContain('variant?: "donut" | "pie"');
    expect(compactSource).toContain('type: "area" | "bar" | "line"');
    expect(compactSource).toContain('anchorClassName="fd-donut-tooltip"');
    expect(compactSource).toContain('anchorClassName="fd-progress-tooltip"');
    expect(compactSource).toContain('anchorClassName="fd-progress-circle-tooltip"');
    expect(styles).toContain(".fd-donut-legend button:focus-visible");
    expect(styles).toContain(".fd-donut-visual:focus-visible");
    expect(styles).toContain(".fd-progress-chart:focus-visible");
    expect(styles).toContain(".fd-tracker button:focus-visible");
  });

  test("keeps FDAI scatter and Tremor categorical aliases in the same palette layer", () => {
    const scatterSource = readFileSync(fileURLToPath(new URL("./charts-scatter.tsx", import.meta.url)), "utf8");
    expect(scatterSource).toContain("export function ScatterChart");
    expect(scatterSource).toContain("tremorChartColor(groupIndex)");
    expect(scatterSource).toContain('type="button"');
    expect(source).toContain("export const BarList = ComparisonBarChart");
    expect(source).toContain("export const CategoryBar = DistributionBar");
    expect(styles).toContain(".fd-scatter-chart button:focus-visible");
  });

  test("keeps exact categorical and distribution values outside color encoding", () => {
    expect(source).toContain('class="fd-bar-label"');
    expect(source).toContain("{current}</strong>");
    expect(source).toContain('class="fd-distribution-legend"');
    expect(source).toContain("<dd>{formatValue(segment.value)}</dd>");
    expect(source).toContain("total === 0 ? 0");
  });

  test("uses a native table and focusable exact values for density", () => {
    expect(source).toContain('<table class="fd-heatmap">');
    expect(source).toContain('<th scope="row">{row.label}</th>');
    expect(source).toContain("<caption class=\"sr-only\">{label}</caption>");
    expect(source).toContain("aria-label={accessible}");
  });

  test("has visible focus and a motion-free fallback", () => {
    expect(styles).toContain(".fd-chart-point:focus-visible");
    expect(styles).toContain(".fd-series-slice:focus-visible");
    expect(styles).toContain(".fd-bar-track:focus-visible");
    expect(styles).toContain(".fd-heatmap td button:focus-visible");
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
    expect(styles).not.toContain("canvas");
  });
});
