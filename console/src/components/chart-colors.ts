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

export const TREMOR_CHART_CATALOG = [
  "Area Chart",
  "Area Chart with stacked categories",
  "Area Chart with percentages",
  "Area Chart with axis titles",
  "Area Chart with only start and end x-axis labels",
  "Area Chart with tooltip callback",
  "Bar Chart",
  "Bar Chart with stacked categories",
  "Bar Chart with percentages",
  "Bar Chart with axis titles",
  "Vertical Bar Chart",
  "Bar Chart with only start and end x-axis labels",
  "Grouped Bar Chart",
  "Bar Chart with conditional formatting",
  "Bar Chart with custom styling",
  "Bar Chart with rounded-sm top corner bars",
  "Bar Chart with gradient bars",
  "Line Chart",
  "Line Chart with axis titles",
  "Line Chart with only start and end x-axis labels",
  "Line Chart with custom tooltip",
  "ComboChart",
  "Donut Chart",
  "Donut Chart as pie variant",
  "Donut Chart with tooltip callback",
  "Progress Circle",
  "Progress Circle with its default variants",
  "Progress Circle complemented by a metric",
  "Spark Chart",
  "Category Bar",
  "Category Bar with marker",
  "Tracker",
  "Bar List",
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
