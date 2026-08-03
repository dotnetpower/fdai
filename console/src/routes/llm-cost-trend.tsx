import { useState } from "preact/hooks";
import { UnavailableState } from "../components/ui";
import { t } from "./i18n/llm-cost";

export interface LlmUsageTrendRow {
  readonly key: string;
  readonly prompt_tokens: number;
  readonly completion_tokens: number;
  readonly total_tokens: number;
}

interface Props {
  readonly rows: readonly LlmUsageTrendRow[];
  readonly auditHref: string;
  readonly locale: string;
  readonly windowLabel: string;
  readonly hourly: boolean;
}

const WIDTH = 640;
const HEIGHT = 190;
const LEFT = 46;
const RIGHT = 626;
const TOP = 12;
const BOTTOM = 166;

function niceStep(maximum: number): number {
  const rough = maximum / 3;
  const power = 10 ** Math.floor(Math.log10(rough));
  const normalized = rough / power;
  const factor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return factor * power;
}

function selectedLabelIndexes(length: number): readonly number[] {
  const count = Math.min(7, length);
  return Array.from({ length: count }, (_, index) =>
    Math.round((index / Math.max(1, count - 1)) * (length - 1))
  );
}

export function LlmCostTrend({ rows, auditHref, locale, windowLabel, hourly }: Props) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const visibleRows = [...rows].sort((left, right) => left.key.localeCompare(right.key));
  if (visibleRows.length < 2) {
    return (
      <section class="llm-cost-panel" aria-labelledby="llm-token-trend-title">
        <div class="llm-cost-panel-head">
          <div><h3 id="llm-token-trend-title">{t("llmCost.tokenTrend", { window: windowLabel })}</h3><p>{t(hourly ? "llmCost.hourlyTrendSubtitle" : "llmCost.dailyTrendSubtitle")}</p></div>
          <a href={auditHref}>{t("llmCost.viewEvidence")}</a>
        </div>
        <UnavailableState message={t("llmCost.trendUnavailable")} />
      </section>
    );
  }

  const highest = Math.max(...visibleRows.map((row) => row.total_tokens));
  const step = niceStep(highest);
  const maximum = step * 3;
  const x = (index: number) => LEFT + (index / (visibleRows.length - 1)) * (RIGHT - LEFT);
  const y = (value: number) => BOTTOM - (value / maximum) * (BOTTOM - TOP);
  const coordinates = visibleRows.map((row, index) => [x(index), y(row.total_tokens)] as const);
  const linePath = coordinates.map(([pointX, pointY], index) => `${index === 0 ? "M" : "L"}${pointX} ${pointY}`).join(" ");
  const areaPath = `M${LEFT} ${BOTTOM} ${coordinates.map(([pointX, pointY]) => `L${pointX} ${pointY}`).join(" ")} L${RIGHT} ${BOTTOM} Z`;
  const number = new Intl.NumberFormat(locale);
  const compact = new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 });
  const labelFormatter = new Intl.DateTimeFormat(locale, hourly
    ? { month: "short", day: "numeric", hour: "2-digit", timeZone: "UTC" }
    : { month: "short", day: "numeric", timeZone: "UTC" });
  const fullFormatter = new Intl.DateTimeFormat(locale, hourly
    ? { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }
    : { dateStyle: "medium", timeZone: "UTC" });
  const labels = selectedLabelIndexes(visibleRows.length);
  const active = activeIndex === null ? null : visibleRows[activeIndex] ?? null;
  const activeX = activeIndex === null ? 0 : x(activeIndex);
  const activeY = active === null ? 0 : y(active.total_tokens);
  const total = visibleRows.reduce((value, row) => value + row.total_tokens, 0);

  return (
    <section class="llm-cost-panel llm-cost-trend-panel" aria-labelledby="llm-token-trend-title">
      <div class="llm-cost-panel-head">
        <div><h3 id="llm-token-trend-title">{t("llmCost.tokenTrend", { window: windowLabel })}</h3><p>{t(hourly ? "llmCost.hourlyTrendSubtitle" : "llmCost.dailyTrendSubtitle")}</p></div>
        <div class="llm-cost-trend-meta">
          <a href={auditHref}>{t("llmCost.viewEvidence")}</a>
          <span>{t("llmCost.rangeTotal", { window: windowLabel })}<strong>{compact.format(total)}</strong></span>
        </div>
      </div>
      <div class="llm-cost-chart-wrap">
        <svg class="llm-cost-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={t("llmCost.dailyTrendAria")}>
          {[0, step, step * 2, step * 3].map((value) => (
            <g>
              <line class="llm-cost-chart-grid" x1={LEFT} x2={RIGHT} y1={y(value)} y2={y(value)} />
              <text class="llm-cost-chart-axis" x={LEFT - 8} y={y(value) + 3} text-anchor="end">{compact.format(value)}</text>
            </g>
          ))}
          <path class="llm-cost-chart-area" d={areaPath} />
          <path class="llm-cost-chart-line" d={linePath} />
          {active !== null ? <line class="llm-cost-chart-guide" x1={activeX} x2={activeX} y1={TOP} y2={BOTTOM} /> : null}
          {visibleRows.map((row, index) => (
            <g>
              <circle
                class="llm-cost-chart-hit"
                cx={x(index)} cy={y(row.total_tokens)} r={Math.max(6, Math.min(18, (RIGHT - LEFT) / (visibleRows.length * 2)))}
                tabIndex={0} role="button"
                aria-label={`${fullFormatter.format(new Date(row.key))}: ${number.format(row.total_tokens)} ${t("llmCost.tokensUnit")}`}
                onMouseEnter={() => setActiveIndex(index)} onMouseLeave={() => setActiveIndex(null)}
                onFocus={() => setActiveIndex(index)} onBlur={() => setActiveIndex(null)}
              />
              <circle class={`llm-cost-chart-point${activeIndex === index ? " is-active" : ""}`} cx={x(index)} cy={y(row.total_tokens)} r="3.5" />
            </g>
          ))}
        </svg>
        {active !== null ? (
          <div class="llm-cost-chart-tooltip" style={{ left: `${Math.min(86, Math.max(14, (activeX / WIDTH) * 100))}%`, top: `${Math.max(58, (activeY / HEIGHT) * 190)}px` }} role="status">
            <strong>{fullFormatter.format(new Date(active.key))}</strong>
            <span>{t("llmCost.inputTokens")}<b>{number.format(active.prompt_tokens)}</b></span>
            <span>{t("llmCost.outputTokens")}<b>{number.format(active.completion_tokens)}</b></span>
            <span>{t("llmCost.totalTokens")}<b>{number.format(active.total_tokens)}</b></span>
          </div>
        ) : null}
        <div class="llm-cost-chart-labels" style={{ gridTemplateColumns: `repeat(${labels.length}, 1fr)` }} aria-hidden="true">
          {labels.map((index) => <span>{labelFormatter.format(new Date(visibleRows[index]!.key))}</span>)}
        </div>
      </div>
    </section>
  );
}
