import { Tooltip } from "../../components/tooltip";
import { t } from "../../i18n";
import type {
  PresentationBlock,
  PresentationChartItem,
  PresentationTableData,
} from "../backend-types";
import type { PresentationModuleProps } from "./types";
import { PresentationTable } from "./table";

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
  return (
    <div class="deck-presentation-accessible-chart">
      {accessible ? <p>{block.data.description}</p> : null}
      <div class="deck-presentation-bars">
        {items.map((item) => {
          const total = block.kind === "coverage" && accessible && "total" in item
            ? item.total
            : denominator;
          const width = item.value === 0 ? 0 : Math.max(2, (item.value / total) * 100);
          const exact = block.kind === "coverage" && accessible && "total" in item
            ? `${item.value} / ${item.total}`
            : `${item.value}`;
          return (
            <div key={item.label} class="deck-presentation-bar-row" data-tone={item.tone}>
              <span class="deck-presentation-bar-label">{item.label}</span>
              <Tooltip content={`${item.label}: ${exact}`}>
                <span
                  class="deck-presentation-bar-track"
                  tabIndex={0}
                  role="img"
                  aria-label={`${item.label}: ${exact}`}
                >
                  <span style={{ width: `${width}%` }} />
                </span>
              </Tooltip>
              <strong>{exact}</strong>
            </div>
          );
        })}
      </div>
      {accessible ? <ExactTableDisclosure data={block.data.exactTable} /> : null}
    </div>
  );
}

function TimeSeries({ block }: { readonly block: Extract<PresentationBlock, { kind: "time_series" }> }) {
  const values = block.data.points.map((point) => point.value);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = Math.max(1, maximum - minimum);
  return (
    <div class="deck-presentation-accessible-chart">
      <p>{block.data.description}</p>
      <ol class="deck-presentation-series" aria-label={block.data.description}>
        {block.data.points.map((point) => {
          const height = 18 + ((point.value - minimum) / range) * 72;
          const label = `${point.timestamp}: ${point.value} ${block.data.unit}`;
          return (
            <li key={point.timestamp}>
              <span class="deck-presentation-series-column" aria-hidden="true">
                <span style={{ height: `${height}%` }} />
              </span>
              <Tooltip content={label}>
                <span class="deck-presentation-series-point" tabIndex={0} role="img" aria-label={label} />
              </Tooltip>
              <strong>{point.value}</strong>
              <time dateTime={point.timestamp}>{point.timestamp}</time>
            </li>
          );
        })}
      </ol>
      <ExactTableDisclosure data={block.data.exactTable} />
    </div>
  );
}

function Comparison({
  block,
}: {
  readonly block: Extract<PresentationBlock, { kind: "comparison" }>;
}) {
  const maximum = Math.max(1, ...block.data.items.map((item) => Math.abs(item.value)));
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
                  <span class="deck-presentation-comparison-track" tabIndex={0} role="img" aria-label={label}>
                    <span style={{ width: `${Math.max(2, Math.abs(item.value) / maximum * 100)}%` }} />
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
