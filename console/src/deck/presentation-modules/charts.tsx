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
import { ComparisonBarChart, TrendChart } from "../../components/charts";

export function ChartModule({ block }: PresentationModuleProps) {
  if (block.kind === "bar" || block.kind === "coverage") return <BarOrCoverage block={block} />;
  if (block.kind === "time_series") return <TimeSeries block={block} />;
  if (block.kind === "comparison") return <Comparison block={block} />;
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
  return (
    <div class="deck-presentation-accessible-chart">
      {accessible ? <p>{block.data.description}</p> : null}
      <ComparisonBarChart label={accessible ? block.data.description : block.kind} items={chartItems} maximum={denominator} formatValue={(value) => `${value}`} />
      {accessible ? <ExactTableDisclosure data={block.data.exactTable} /> : null}
    </div>
  );
}

function TimeSeries({ block }: { readonly block: Extract<PresentationBlock, { kind: "time_series" }> }) {
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  return (
    <div class="deck-presentation-accessible-chart">
      <TrendChart
        title={block.data.description}
        points={block.data.points.map((point) => {
          const timestamp = presentationTimestamp(point.timestamp, locale);
          return {
            label: timestamp ? `${timestamp.date} ${timestamp.time}` : point.timestamp,
            value: point.value,
            detail: point.timestamp,
          };
        })}
        formatValue={(value) => `${value} ${block.data.unit}`}
        summary={`${block.data.points.at(-1)!.value} ${block.data.unit}`}
        referenceLabel={t("deck.rich.median")}
        compact
      />
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
