export const TREMOR_CHART_COLORS = [
  "blue",
  "emerald",
  "violet",
  "amber",
  "gray",
  "cyan",
  "pink",
  "lime",
  "fuchsia",
] as const;

export type TremorChartColor = (typeof TREMOR_CHART_COLORS)[number];

export const TREMOR_CHART_COMPONENTS = [
  "AreaChart",
  "BarChart",
  "BarList",
  "CategoryBar",
  "ComboChart",
  "DonutChart",
  "LineChart",
  "ProgressBar",
  "ProgressCircle",
  "SparkAreaChart",
  "SparkBarChart",
  "SparkLineChart",
  "Tracker",
] as const;

export const TREMOR_CHART_COMPOSITIONS = [
  "PortfolioPerformance",
  "InteractiveKpiArea",
  "ComparisonLine",
  "AllocationDonut",
  "CustomTooltipBar",
  "ResponsiveMonitoringArea",
  "UptimeCategory",
] as const;

export const TREMOR_CHART_HEX: Readonly<Record<TremorChartColor, string>> = {
  blue: "#3b82f6",
  emerald: "#10b981",
  violet: "#8b5cf6",
  amber: "#f59e0b",
  gray: "#6b7280",
  cyan: "#06b6d4",
  pink: "#ec4899",
  lime: "#84cc16",
  fuchsia: "#d946ef",
};

export function tremorChartColor(index: number): TremorChartColor {
  return TREMOR_CHART_COLORS[index % TREMOR_CHART_COLORS.length] ?? "gray";
}
