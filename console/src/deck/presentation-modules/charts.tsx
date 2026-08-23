import { Tooltip } from "../../components/tooltip";
import { getLocale, t } from "../../i18n";
import type {
  PresentationBlock,
  PresentationChartItem,
  PresentationTableData,
} from "../backend-types";
import type { PresentationModuleProps } from "./types";
import { presentationTimestamp } from "../presentation-value";
import { PresentationTable } from "./table";
import {
  AreaChart,
  BarChart,
  BarList,
  CategoryBar,
  ComparisonBarChart,
  DensityHeatmap,
  DonutChart,
  LineChart,
  ScatterChart,
} from "../../components/charts";

export function ChartModule({ block }: PresentationModuleProps) {
  if (block.kind === "bar" || block.kind === "coverage") return <BarOrCoverage block={block} />;
  if (block.kind === "time_series") return <TimeSeries block={block} />;
  if (block.kind === "comparison") return <Comparison block={block} />;
  if (block.kind === "scatter") return <Scatter block={block} />;
  if (block.kind === "heatmap") return <Heatmap block={block} />;
  return null;
}

export function ExactTableDisclosure({ data }: { readonly data: PresentationTableData }) {
  return (
    <details class="deck-presentation-exact-values">
      <summary>{t("deck.presentation.exactValues")}</summary>
      <PresentationTable data={data} />
    </details>
  );
}

export function timeSeriesStyle(pointCount: number): Record<string, string | number> {
  return { "--series-count": pointCount };
}

export function comparisonTrackStyle(
  values: readonly number[],
  value: number,
): Record<string, string> {
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(0, ...values);
  const range = Math.max(1, maximum - minimum);
  const zero = (-minimum / range) * 100;
  const endpoint = ((value - minimum) / range) * 100;
  return {
    "--comparison-zero": `${zero}%`,
    "--comparison-start": `${Math.min(zero, endpoint)}%`,
    "--comparison-width": `${Math.max(value === 0 ? 0 : 2, Math.abs(endpoint - zero))}%`,
  };
}

function BarOrCoverage({
  block,
}: {
  readonly block: Extract<PresentationBlock, { kind: "bar" | "coverage" }>;
}) {
  const accessible = "description" in block.data;
  const items = block.data.items;
  const denominator = block.kind === "coverage" && accessible
    ? 1
    : block.kind === "coverage"
    ? Math.max(1, items.reduce((sum, item) => sum + item.value, 0))
    : Math.max(1, ...items.map((item) => item.value));
  const chartItems = items.map((item) => {
    const exact = block.kind === "coverage" && accessible && "total" in item
      ? `${item.value} / ${item.total}`
      : `${item.value}`;
    return { label: item.label, value: item.value, formattedValue: exact };
  });
  if (block.kind === "bar") {
    const data = block.data;
    if ("description" in data && data.visualization === "donut") {
      return (
        <div class="deck-presentation-accessible-chart">
          <p>{data.description}</p>
          <DonutChart label={data.description} segments={items} formatValue={(value) => `${value} ${data.unit}`} />
          <ExactTableDisclosure data={data.exactTable} />
        </div>
      );
    }
    if ("description" in data && data.visualization === "bar") {
      return (
        <div class="deck-presentation-accessible-chart">
          <p>{data.description}</p>
          <BarChart
            title={data.description}
            data={items.map((item) => ({ label: item.label, values: [item.value] }))}
            series={[{ label: data.unit, color: "blue" }]}
            formatValue={(value) => `${value} ${data.unit}`}
            showLegend={false}
          />
          <ExactTableDisclosure data={data.exactTable} />
        </div>
      );
    }
  }
  if (block.kind === "coverage") {
    const data = block.data;
    if ("description" in data && data.visualization === "category_bar") {
      return (
        <div class="deck-presentation-accessible-chart">
          <p>{data.description}</p>
          {items.map((item) => "total" in item ? (
            <div key={item.label} class="deck-presentation-category-row">
              <strong>{item.label}</strong>
              <CategoryBar
                label={item.label}
                segments={[
                  { label: item.label, value: item.value },
                  { label: data.unit, value: item.total - item.value },
                ]}
                formatValue={(value) => `${value}`}
              />
            </div>
          ) : null)}
          <ExactTableDisclosure data={data.exactTable} />
        </div>
      );
    }
  }
  return (
    <div class="deck-presentation-accessible-chart">
      {accessible ? <p>{block.data.description}</p> : null}
      <BarList label={accessible ? block.data.description : block.kind} items={chartItems} maximum={denominator} formatValue={(value) => `${value}`} />
      {accessible ? <ExactTableDisclosure data={block.data.exactTable} /> : null}
    </div>
  );
}

function TimeSeries({ block }: { readonly block: Extract<PresentationBlock, { kind: "time_series" }> }) {
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  const data = block.data.points.map((point) => {
    const timestamp = presentationTimestamp(point.timestamp, locale);
    return {
      label: timestamp ? `${timestamp.date} ${timestamp.time}` : point.timestamp,
      values: [point.value],
      detail: point.timestamp,
    };
  });
  const Chart = block.data.visualization === "area" ? AreaChart : LineChart;
  return (
    <div class="deck-presentation-accessible-chart">
      <Chart
        title={block.data.description}
        data={data}
        series={[{ label: block.data.metric, color: "blue" }]}
        formatValue={(value) => `${value} ${block.data.unit}`}
        showLegend={false}
        showYAxis
        startEndOnly={data.length > 8}
      />
      <ExactTableDisclosure data={block.data.exactTable} />
    </div>
  );
}

function Scatter({ block }: { readonly block: Extract<PresentationBlock, { kind: "scatter" }> }) {
  return (
    <div class="deck-presentation-accessible-chart">
      <p>{block.data.description}</p>
      <ScatterChart
        label={block.data.description}
        points={block.data.points}
        formatX={(value) => `${value} ${block.data.xLabel}`}
        formatY={(value) => `${value} ${block.data.yLabel}`}
      />
      <ExactTableDisclosure data={block.data.exactTable} />
    </div>
  );
}

function Heatmap({ block }: { readonly block: Extract<PresentationBlock, { kind: "heatmap" }> }) {
  const columns = [...new Set(block.data.cells.map((cell) => cell.column))];
  const rows = [...new Set(block.data.cells.map((cell) => cell.row))].map((row) => ({
    label: row,
    cells: columns.map((column) => {
      const cell = block.data.cells.find((candidate) => candidate.row === row && candidate.column === column);
      return { label: column, value: cell?.value ?? Number.NaN };
    }),
  }));
  return (
    <div class="deck-presentation-accessible-chart">
      <p>{block.data.description}</p>
      <DensityHeatmap label={block.data.description} rows={rows} formatValue={(value) => Number.isFinite(value) ? `${value}` : "-"} />
      <ExactTableDisclosure data={block.data.exactTable} />
    </div>
  );
}

function Comparison({
  block,
}: {
  readonly block: Extract<PresentationBlock, { kind: "comparison" }>;
}) {
  const values = block.data.items.map((item) => item.value);
  return (
    <div class="deck-presentation-accessible-chart">
      <p>{block.data.description}</p>
      <dl class="deck-presentation-comparison">
        {block.data.items.map((item) => {
          const label = `${item.label}: ${item.value} ${block.data.unit}`;
          return (
            <div key={item.role} data-role={item.role}>
              <dt>{item.label}</dt>
              <dd>
                <Tooltip content={label}>
                  <span
                    class="deck-presentation-comparison-track"
                    tabIndex={0}
                    role="img"
                    aria-label={label}
                    data-sign={item.value < 0 ? "negative" : item.value > 0 ? "positive" : "zero"}
                    style={comparisonTrackStyle(values, item.value)}
                  >
                    <span />
                  </span>
                </Tooltip>
                <strong>{item.value} {block.data.unit}</strong>
              </dd>
            </div>
          );
        })}
      </dl>
      <ExactTableDisclosure data={block.data.exactTable} />
    </div>
  );
}
